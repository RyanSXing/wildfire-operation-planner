import asyncio
from collections.abc import Callable

import pytest

from wildfireops.api.event_bus import EventBus
from wildfireops.api.postgres_events import (
    MAX_NOTIFICATION_BYTES,
    decode_notification,
    relay_postgres_events,
)


_INCIDENT_ID = "00000000-0000-0000-0000-000000000123"
_INCIDENT_PAYLOAD = (
    '{"data":{"incidentId":"' + _INCIDENT_ID + '"},"name":"incident-updated"}'
)


Listener = Callable[[object, int, str, str], object]


class _FakeConnection:
    def __init__(self) -> None:
        self.listener: Listener | None = None
        self.listener_added = asyncio.Event()
        self.closed = False
        self.remove_calls = 0

    async def add_listener(self, channel: str, listener: Listener) -> None:
        assert channel == "wildfireops_events"
        self.listener = listener
        self.listener_added.set()

    async def remove_listener(self, channel: str, listener: Listener) -> None:
        assert channel == "wildfireops_events"
        assert listener is self.listener
        self.remove_calls += 1
        self.listener = None

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True

    def emit(self, payload: str) -> None:
        assert self.listener is not None
        self.listener(self, 1, "wildfireops_events", payload)


class _CapturingLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **values: object) -> None:
        self.events.append((event, values))


@pytest.mark.parametrize(
    "payload",
    (
        None,
        "not-json",
        "[]",
        '{"data":{},"name":"unknown"}',
        '{"data":{"incidentId":"not-a-uuid"},"name":"incident-updated"}',
        '{"data":{"sourceName":1},"name":"source-status-updated"}',
        '{"data":{"sourceName":"   "},"name":"source-status-updated"}',
        '{"data":{"extra":true},"name":"resync-required"}',
        '{"data":{"value":NaN},"name":"source-status-updated"}',
        "x" * (MAX_NOTIFICATION_BYTES + 1),
    ),
)
def test_notification_codec_rejects_malformed_or_oversized_payloads(
    payload: object,
) -> None:
    assert decode_notification(payload) is None


def test_notification_codec_accepts_only_the_frozen_event_shapes() -> None:
    assert decode_notification(_INCIDENT_PAYLOAD) == (
        "incident-updated",
        {"incidentId": _INCIDENT_ID},
    )
    assert decode_notification(
        '{"name":"source-status-updated","data":{"sourceName":"nws"}}'
    ) == ("source-status-updated", {"sourceName": "nws"})
    assert decode_notification('{"data":{},"name":"resync-required"}') == (
        "resync-required",
        {},
    )


@pytest.mark.asyncio
async def test_relay_forwards_valid_events_ignores_bad_payload_and_closes_on_cancel() -> (
    None
):
    connection = _FakeConnection()
    connected_dsn: list[str] = []

    async def connect(dsn: str) -> _FakeConnection:
        connected_dsn.append(dsn)
        return connection

    bus = EventBus()
    async with bus.subscribe() as queue:
        task = asyncio.create_task(
            relay_postgres_events(
                "postgresql+asyncpg://user:pass@db:5432/wildfireops",
                bus,
                connector=connect,
                poll_seconds=0.01,
                retry_seconds=0.01,
            )
        )
        await asyncio.wait_for(connection.listener_added.wait(), timeout=1)
        assert (await asyncio.wait_for(queue.get(), timeout=1)).name == (
            "resync-required"
        )
        queue.task_done()

        connection.emit("not-json")
        connection.emit(_INCIDENT_PAYLOAD)
        forwarded = await asyncio.wait_for(queue.get(), timeout=1)
        queue.task_done()

        assert forwarded.name == "incident-updated"
        assert forwarded.data == {"incidentId": _INCIDENT_ID}
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert connected_dsn == ["postgresql://user:pass@db:5432/wildfireops"]
    assert connection.remove_calls == 1
    assert connection.closed


@pytest.mark.asyncio
async def test_connection_failure_waits_before_retrying() -> None:
    connection = _FakeConnection()
    logger = _CapturingLogger()
    attempts = 0
    retry_started = asyncio.Event()
    allow_retry = asyncio.Event()

    async def connect(_dsn: str) -> _FakeConnection:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("database unavailable: password=super-secret")
        return connection

    async def sleep(delay: float) -> None:
        assert delay in {0.25, 60.0}
        if delay == 0.25:
            retry_started.set()
            await allow_retry.wait()
        else:
            await asyncio.Event().wait()

    task = asyncio.create_task(
        relay_postgres_events(
            "postgresql+asyncpg://user:pass@db/database",
            EventBus(),
            connector=connect,
            sleep=sleep,
            logger=logger,
            poll_seconds=60.0,
            retry_seconds=0.25,
        )
    )
    await asyncio.wait_for(retry_started.wait(), timeout=1)
    assert attempts == 1
    assert logger.events == [
        (
            "postgres_event_listener_retry",
            {"failure_type": "OSError"},
        )
    ]
    assert "super-secret" not in repr(logger.events)
    allow_retry.set()
    await asyncio.wait_for(connection.listener_added.wait(), timeout=1)
    assert attempts == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_connection_drop_reconnects_and_emits_resync_again() -> None:
    first = _FakeConnection()
    second = _FakeConnection()
    connections = iter((first, second))
    poll_released = asyncio.Event()
    retry_released = asyncio.Event()

    async def connect(_dsn: str) -> _FakeConnection:
        return next(connections)

    async def sleep(delay: float) -> None:
        if delay == 60.0:
            await poll_released.wait()
            poll_released.clear()
        else:
            await retry_released.wait()
            retry_released.clear()

    bus = EventBus()
    async with bus.subscribe() as queue:
        task = asyncio.create_task(
            relay_postgres_events(
                "postgresql+asyncpg://user:pass@db/database",
                bus,
                connector=connect,
                sleep=sleep,
                poll_seconds=60.0,
                retry_seconds=0.25,
            )
        )
        await asyncio.wait_for(first.listener_added.wait(), timeout=1)
        assert (await asyncio.wait_for(queue.get(), timeout=1)).name == (
            "resync-required"
        )
        queue.task_done()

        first.closed = True
        poll_released.set()
        retry_released.set()
        await asyncio.wait_for(second.listener_added.wait(), timeout=1)
        assert (await asyncio.wait_for(queue.get(), timeout=1)).name == (
            "resync-required"
        )
        queue.task_done()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert first.closed
    assert second.closed
