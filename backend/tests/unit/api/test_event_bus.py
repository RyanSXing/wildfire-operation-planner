import asyncio
from threading import get_ident

import pytest

from wildfireops.api.event_bus import EventBus
from wildfireops.api.routes.events import stream_events


@pytest.mark.asyncio
async def test_publish_preserves_order_and_isolates_subscribers() -> None:
    bus = EventBus(queue_size=3)

    async with bus.subscribe() as first, bus.subscribe() as second:
        bus.publish("incident-updated", {"incidentId": "incident-1"})
        bus.publish("source-status-updated", {"sourceName": "nws"})

        first_events = [first.get_nowait(), first.get_nowait()]
        second_events = [second.get_nowait(), second.get_nowait()]

    assert [event.name for event in first_events] == [
        "incident-updated",
        "source-status-updated",
    ]
    assert [event.name for event in second_events] == [
        "incident-updated",
        "source-status-updated",
    ]
    assert first_events[0].data == {"incidentId": "incident-1"}
    assert first_events[0] is not second_events[0]
    assert bus.subscriber_count == 0


@pytest.mark.asyncio
async def test_full_queue_collapses_to_one_resync_marker() -> None:
    bus = EventBus(queue_size=2)

    async with bus.subscribe() as queue:
        bus.publish("source-status-updated", {"sourceName": "nws"})
        bus.publish("incident-updated", {"incidentId": "incident-old"})
        bus.publish("incident-updated", {"incidentId": "incident-new"})
        bus.publish("source-status-updated", {"sourceName": "nasa_firms"})

        events = [queue.get_nowait()]

    assert [(event.name, dict(event.data)) for event in events] == [
        ("resync-required", {}),
    ]


@pytest.mark.asyncio
async def test_sse_serializes_resync_with_named_event_format() -> None:
    bus = EventBus(queue_size=2)
    stream = stream_events(bus, heartbeat_seconds=1)
    pending = asyncio.create_task(anext(stream))
    for _ in range(10):
        if bus.subscriber_count == 1:
            break
        await asyncio.sleep(0)

    bus.publish("resync-required", {})

    try:
        assert await pending == "event: resync-required\ndata: {}\n\n"
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_sse_stream_emits_named_events_heartbeat_and_cleans_up() -> None:
    bus = EventBus(queue_size=2)
    stream = stream_events(bus, heartbeat_seconds=0.01)

    first_chunk = asyncio.create_task(anext(stream))
    for _ in range(10):
        if bus.subscriber_count == 1:
            break
        await asyncio.sleep(0)
    assert bus.subscriber_count == 1
    bus.publish("incident-updated", {"incidentId": "incident-1"})

    assert await first_chunk == (
        'event: incident-updated\ndata: {"incidentId":"incident-1"}\n\n'
    )
    assert await asyncio.wait_for(anext(stream), timeout=0.1) == ": heartbeat\n\n"

    await stream.aclose()
    assert bus.subscriber_count == 0


def test_queue_size_must_be_a_positive_integer() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        EventBus(queue_size=0)
    with pytest.raises(ValueError, match="positive integer"):
        EventBus(queue_size=True)


def test_event_names_are_bounded_and_payloads_are_defensively_copied() -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="event name"):
        bus.publish("incident-updated\nevent: injected", {})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_subscribers_cannot_mutate_each_others_nested_event_data() -> None:
    bus = EventBus()
    payload: dict[str, object] = {"nested": {"value": "original"}}

    async with bus.subscribe() as first, bus.subscribe() as second:
        bus.publish("incident-updated", payload)
        payload["nested"] = {"value": "caller-mutated"}
        first_event = first.get_nowait()
        second_event = second.get_nowait()

    first_nested = first_event.data["nested"]
    assert isinstance(first_nested, dict)
    first_nested["value"] = "subscriber-mutated"
    assert second_event.data == {"nested": {"value": "original"}}


@pytest.mark.asyncio
async def test_sse_escapes_lone_surrogate_as_utf8_safe_ascii() -> None:
    bus = EventBus()
    stream = stream_events(bus, heartbeat_seconds=1)
    pending_chunk = asyncio.create_task(anext(stream))
    for _ in range(10):
        if bus.subscriber_count == 1:
            break
        await asyncio.sleep(0)
    bus.publish("incident-updated", {"value": "\ud800"})

    try:
        chunk = await pending_chunk
        assert "\\ud800" in chunk
        chunk.encode("utf-8")
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_publish_from_another_thread_and_loop_wakes_subscriber_safely() -> None:
    bus = EventBus()
    owner_thread = get_ident()
    async with bus.subscribe() as queue:
        original_put = queue.put_nowait

        def checked_put(item: object) -> None:
            assert get_ident() == owner_thread
            original_put(item)  # type: ignore[arg-type]

        setattr(queue, "put_nowait", checked_put)

        def publish_from_other_loop() -> None:
            async def publish() -> None:
                bus.publish("incident-updated", {"incidentId": "cross-loop"})

            asyncio.run(publish())

        await asyncio.to_thread(publish_from_other_loop)
        event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event.data == {"incidentId": "cross-loop"}


@pytest.mark.asyncio
async def test_coalescing_never_temporarily_completes_queue_join() -> None:
    class JoinProbe(asyncio.Event):
        def __init__(self) -> None:
            super().__init__()
            self.set_calls = 0

        def set(self) -> None:
            self.set_calls += 1
            super().set()

    bus = EventBus(queue_size=2)
    async with bus.subscribe() as queue:
        bus.publish("source-status-updated", {"sourceName": "nws"})
        bus.publish("incident-updated", {"incidentId": "old"})
        probe = JoinProbe()
        setattr(queue, "_finished", probe)

        bus.publish("incident-updated", {"incidentId": "new"})

        assert probe.set_calls == 0
        join_task = asyncio.create_task(queue.join())
        await asyncio.sleep(0)
        assert not join_task.done()
        event = queue.get_nowait()
        assert event.name == "resync-required"
        queue.task_done()
        await asyncio.wait_for(join_task, timeout=1)
