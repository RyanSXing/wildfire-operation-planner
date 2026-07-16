import asyncio
from collections.abc import AsyncIterator
import json
from math import isfinite
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from wildfireops.api.dependencies import get_event_bus, get_event_heartbeat_seconds
from wildfireops.api.event_bus import EventBus


router = APIRouter(tags=["events"])


async def stream_events(
    bus: EventBus,
    *,
    heartbeat_seconds: float = 20.0,
) -> AsyncIterator[str]:
    if not isfinite(heartbeat_seconds) or heartbeat_seconds <= 0:
        raise ValueError("heartbeat_seconds must be finite and positive")
    async with bus.subscribe() as queue:
        while True:
            try:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            queue.task_done()
            data = json.dumps(
                dict(event.data),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            yield f"event: {event.name}\ndata: {data}\n\n"


@router.get("/api/events", response_class=StreamingResponse)
async def events(
    bus: Annotated[EventBus, Depends(get_event_bus)],
    heartbeat_seconds: Annotated[float, Depends(get_event_heartbeat_seconds)],
) -> StreamingResponse:
    return StreamingResponse(
        stream_events(bus, heartbeat_seconds=heartbeat_seconds),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
