from __future__ import annotations

import asyncio
import fnmatch
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep, CurrentUser
from app.schemas import LogLevel, LogRecord

router = APIRouter(prefix="/api/v1", tags=["live tail"])

MAX_EVENTS_PER_MESSAGE = 200


@router.get(
    "/stream",
    summary="Live tail (Server-Sent Events)",
    description=(
        "Streams newly ingested logs as `event: logs` messages whose data is a JSON array of logs. "
        "Sends a comment heartbeat every few seconds so proxies keep the connection open."
    ),
    response_class=StreamingResponse,
)
async def live_tail(
    request: Request,
    container: ContainerDep,
    _user: CurrentUser,
    level: Annotated[list[LogLevel], Query()] = [],  # noqa: B006
    service: Annotated[list[str], Query()] = [],  # noqa: B006
    q: Annotated[str | None, Query(max_length=256)] = None,
) -> StreamingResponse:
    levels = {lvl.value for lvl in level}
    needle = q.lower() if q else None

    def accepts(doc: dict[str, Any]) -> bool:
        if levels and doc.get("level") not in levels:
            return False
        if service and not any(fnmatch.fnmatchcase(doc.get("service", ""), p) for p in service):
            return False
        return needle is None or needle in doc.get("message", "").lower()

    broker = container.broker
    heartbeat = container.settings.stream_heartbeat_seconds
    subscription = broker.subscribe(accepts)

    async def events() -> AsyncIterator[str]:
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    first = await asyncio.wait_for(subscription.queue.get(), timeout=heartbeat)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                batch = [first]
                while len(batch) < MAX_EVENTS_PER_MESSAGE and not subscription.queue.empty():
                    batch.append(subscription.queue.get_nowait())
                data = json.dumps([LogRecord.from_document(d).model_dump(mode="json") for d in batch])
                yield f"event: logs\ndata: {data}\n\n"
        finally:
            broker.unsubscribe(subscription)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
