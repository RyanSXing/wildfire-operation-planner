import asyncio
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from threading import Lock
from types import MappingProxyType
from typing import Literal, cast

from pydantic import JsonValue


type EventName = Literal["incident-updated", "source-status-updated"]


@dataclass(frozen=True, slots=True)
class EventBusEvent:
    name: EventName
    _encoded_data: str

    @property
    def data(self) -> Mapping[str, JsonValue]:
        decoded = json.loads(self._encoded_data)
        return MappingProxyType(cast(dict[str, JsonValue], decoded))

    @property
    def encoded_data(self) -> str:
        return self._encoded_data


class EventQueue(asyncio.Queue[EventBusEvent]):
    def offer(self, event: EventBusEvent) -> None:
        if not self.full():
            self.put_nowait(event)
            return

        queued = cast(deque[EventBusEvent], getattr(self, "_queue"))
        incident_index = next(
            (
                index
                for index, queued_event in enumerate(queued)
                if queued_event.name == "incident-updated"
            ),
            None,
        )
        if incident_index is None:
            return
        del queued[incident_index]
        queued.append(event)


@dataclass(frozen=True, slots=True, eq=False)
class _Subscription:
    queue: EventQueue
    loop: asyncio.AbstractEventLoop


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
        self._subscribers: set[_Subscription] = set()
        self._subscribers_lock = Lock()

    @property
    def subscriber_count(self) -> int:
        with self._subscribers_lock:
            return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[EventQueue]:
        subscription = _Subscription(
            queue=EventQueue(maxsize=self._queue_size),
            loop=asyncio.get_running_loop(),
        )
        with self._subscribers_lock:
            self._subscribers.add(subscription)
        try:
            yield subscription.queue
        finally:
            with self._subscribers_lock:
                self._subscribers.discard(subscription)

    def publish(self, name: EventName, data: Mapping[str, object]) -> None:
        if name not in {"incident-updated", "source-status-updated"}:
            raise ValueError("event name is not supported")
        encoded_data = _canonical_payload(data)
        with self._subscribers_lock:
            subscribers = tuple(self._subscribers)
        try:
            publishing_loop = asyncio.get_running_loop()
        except RuntimeError:
            publishing_loop = None
        for subscription in subscribers:
            event = EventBusEvent(
                name=name,
                _encoded_data=encoded_data,
            )
            if publishing_loop is subscription.loop:
                self._offer_if_subscribed(subscription, event)
                continue
            try:
                subscription.loop.call_soon_threadsafe(
                    self._offer_if_subscribed,
                    subscription,
                    event,
                )
            except RuntimeError:
                with self._subscribers_lock:
                    self._subscribers.discard(subscription)

    def _offer_if_subscribed(
        self,
        subscription: _Subscription,
        event: EventBusEvent,
    ) -> None:
        with self._subscribers_lock:
            if subscription not in self._subscribers:
                return
        subscription.queue.offer(event)


def _canonical_payload(data: Mapping[str, object]) -> str:
    if not isinstance(data, Mapping) or any(not isinstance(key, str) for key in data):
        raise ValueError("event data must be a string-keyed JSON object")
    try:
        encoded = json.dumps(
            dict(data),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        raise ValueError("event data must be a string-keyed JSON object") from None
    if not isinstance(decoded, dict):
        raise ValueError("event data must be a string-keyed JSON object")
    return encoded
