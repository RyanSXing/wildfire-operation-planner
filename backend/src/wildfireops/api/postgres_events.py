import asyncio
from collections.abc import Awaitable, Callable
import json
from typing import Protocol, cast
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
import structlog

from wildfireops.api.event_bus import EventBus, EventName


CHANNEL = "wildfireops_events"
MAX_NOTIFICATION_BYTES = 7_999


type Listener = Callable[[object, int, str, str], object]


class Connection(Protocol):
    async def add_listener(self, channel: str, listener: Listener) -> None: ...

    async def remove_listener(self, channel: str, listener: Listener) -> None: ...

    def is_closed(self) -> bool: ...

    async def close(self) -> None: ...


type Connector = Callable[[str], Awaitable[Connection]]
type Sleep = Callable[[float], Awaitable[None]]


class EventLogger(Protocol):
    def warning(self, event: str, **values: object) -> object: ...


def decode_notification(payload: object) -> tuple[EventName, dict[str, object]] | None:
    if not isinstance(payload, str):
        return None
    try:
        if len(payload.encode("utf-8")) > MAX_NOTIFICATION_BYTES:
            return None
        envelope = json.loads(
            payload,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (RecursionError, TypeError, ValueError, UnicodeError):
        return None
    if not isinstance(envelope, dict) or set(envelope) != {"name", "data"}:
        return None

    name = envelope["name"]
    data = envelope["data"]
    if not isinstance(name, str) or not isinstance(data, dict):
        return None
    if name == "incident-updated":
        incident_id = data.get("incidentId")
        if set(data) != {"incidentId"} or not _is_canonical_uuid(incident_id):
            return None
    elif name == "source-status-updated":
        source_name = data.get("sourceName")
        if (
            set(data) != {"sourceName"}
            or not isinstance(source_name, str)
            or not source_name.strip()
        ):
            return None
    elif name == "resync-required":
        if data:
            return None
    else:
        return None
    return cast(EventName, name), cast(dict[str, object], data)


async def relay_postgres_events(
    database_url: str,
    bus: EventBus,
    *,
    connector: Connector | None = None,
    sleep: Sleep = asyncio.sleep,
    logger: EventLogger | None = None,
    poll_seconds: float = 1.0,
    retry_seconds: float = 1.0,
) -> None:
    connect = connector or _connect
    event_logger = logger or structlog.get_logger("wildfireops.api")
    dsn = _direct_asyncpg_dsn(database_url)
    while True:
        connection: Connection | None = None
        listener: Listener | None = None
        try:
            connection = await connect(dsn)

            def receive(
                _connection: object,
                _pid: int,
                _channel: str,
                payload: str,
            ) -> None:
                decoded = decode_notification(payload)
                if decoded is not None:
                    bus.publish(*decoded)

            listener = receive
            await connection.add_listener(CHANNEL, listener)
            bus.publish("resync-required", {})
            while not connection.is_closed():
                await sleep(poll_seconds)
            event_logger.warning(
                "postgres_event_listener_retry",
                failure_type="ConnectionClosed",
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            event_logger.warning(
                "postgres_event_listener_retry",
                failure_type=type(error).__name__,
            )
        finally:
            if connection is not None and not connection.is_closed():
                if listener is not None:
                    try:
                        await connection.remove_listener(CHANNEL, listener)
                    except Exception:
                        pass
                try:
                    await connection.close()
                except Exception:
                    pass
        await sleep(retry_seconds)


async def _connect(dsn: str) -> Connection:
    return await asyncpg.connect(dsn)


def _direct_asyncpg_dsn(database_url: str) -> str:
    prefix = "postgresql+asyncpg://"
    if not database_url.startswith(prefix):
        raise ValueError("database URL must use postgresql+asyncpg")
    return "postgresql://" + database_url[len(prefix) :]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False
