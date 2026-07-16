import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from types import MappingProxyType
from typing import Literal, cast

from pydantic import JsonValue


type EventName = Literal["incident-updated", "source-status-updated"]
type EventQueue = asyncio.Queue["EventBusEvent"]


@dataclass(frozen=True, slots=True)
class EventBusEvent:
    name: EventName
    _encoded_data: str

    @property
    def data(self) -> Mapping[str, JsonValue]:
        decoded = json.loads(self._encoded_data)
        return MappingProxyType(cast(dict[str, JsonValue], decoded))


class EventBus:
    """Bounded, nonblocking fan-out for one API process.

    When a subscriber queue is full, the oldest queued incident update is
    evicted and the new event is appended. If the queue contains only source
    status events, the incoming event is dropped so their order is preserved.
    """

    def __init__(self, queue_size: int = 64) -> None:
        if isinstance(queue_size, bool) or not isinstance(queue_size, int):
            raise ValueError("queue_size must be a positive integer")
        if queue_size <= 0:
            raise ValueError("queue_size must be a positive integer")
        self._queue_size = queue_size
        self._subscribers: set[EventQueue] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[EventQueue]:
        queue: EventQueue = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def publish(self, name: EventName, data: Mapping[str, object]) -> None:
        if name not in {"incident-updated", "source-status-updated"}:
            raise ValueError("event name is not supported")
        encoded_data = _canonical_payload(data)
        for queue in tuple(self._subscribers):
            event = EventBusEvent(
                name=name,
                _encoded_data=encoded_data,
            )
            _offer_without_blocking(queue, event)


def _offer_without_blocking(queue: EventQueue, event: EventBusEvent) -> None:
    if not queue.full():
        queue.put_nowait(event)
        return

    queued: list[EventBusEvent] = []
    while True:
        try:
            queued.append(queue.get_nowait())
            queue.task_done()
        except asyncio.QueueEmpty:
            break
    incident_index = next(
        (
            index
            for index, queued_event in enumerate(queued)
            if queued_event.name == "incident-updated"
        ),
        None,
    )
    if incident_index is not None:
        queued.pop(incident_index)
    for queued_event in queued:
        queue.put_nowait(queued_event)
    if incident_index is not None:
        queue.put_nowait(event)


def _canonical_payload(data: Mapping[str, object]) -> str:
    if not isinstance(data, Mapping) or any(not isinstance(key, str) for key in data):
        raise ValueError("event data must be a string-keyed JSON object")
    try:
        encoded = json.dumps(
            dict(data),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        raise ValueError("event data must be a string-keyed JSON object") from None
    if not isinstance(decoded, dict):
        raise ValueError("event data must be a string-keyed JSON object")
    return encoded
