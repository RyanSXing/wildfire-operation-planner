import asyncio

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
async def test_slow_subscriber_replaces_oldest_incident_and_preserves_source_order(
) -> None:
    bus = EventBus(queue_size=2)

    async with bus.subscribe() as queue:
        bus.publish("source-status-updated", {"sourceName": "nws"})
        bus.publish("incident-updated", {"incidentId": "incident-old"})
        bus.publish("incident-updated", {"incidentId": "incident-new"})

        events = [queue.get_nowait(), queue.get_nowait()]

    assert [(event.name, dict(event.data)) for event in events] == [
        ("source-status-updated", {"sourceName": "nws"}),
        ("incident-updated", {"incidentId": "incident-new"}),
    ]


@pytest.mark.asyncio
async def test_full_source_only_queue_drops_new_incident_without_blocking() -> None:
    bus = EventBus(queue_size=2)

    async with bus.subscribe() as queue:
        bus.publish("source-status-updated", {"sourceName": "nws"})
        bus.publish("source-status-updated", {"sourceName": "nasa_firms"})
        bus.publish("incident-updated", {"incidentId": "incident-dropped"})

        events = [queue.get_nowait(), queue.get_nowait()]

    assert [dict(event.data) for event in events] == [
        {"sourceName": "nws"},
        {"sourceName": "nasa_firms"},
    ]


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
        "event: incident-updated\n"
        'data: {"incidentId":"incident-1"}\n\n'
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
