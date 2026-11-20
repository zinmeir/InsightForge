from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, status

from app.api.deps import ContainerDep, IngestClient
from app.container import Container
from app.core import metrics
from app.schemas import IngestResponse, LogEntryIn, utcnow
from app.services.ingest_buffer import BufferFullError

router = APIRouter(tags=["ingest"])


def accept_entries(container: Container, entries: list[LogEntryIn]) -> int:
    received_at = utcnow()
    docs = [entry.to_document(received_at) for entry in entries]
    try:
        container.buffer.submit(docs)
    except BufferFullError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc}; retry shortly",
            headers={"Retry-After": "1"},
        ) from exc
    for doc in docs:
        metrics.LOGS_RECEIVED.labels(level=doc["level"]).inc()
        container.broker.publish(doc)
        container.alert_manager.process(doc)
    return len(docs)


@router.post(
    "/api/v1/logs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    summary="Ingest a single log",
)
async def ingest_one(entry: LogEntryIn, container: ContainerDep, _client: IngestClient) -> IngestResponse:
    return IngestResponse(accepted=accept_entries(container, [entry]))


@router.post(
    "/api/v1/logs/bulk",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    summary="Ingest a batch of logs",
    description="Accepts a JSON array of log entries. The whole batch is accepted or rejected atomically.",
)
async def ingest_bulk(
    entries: Annotated[list[LogEntryIn], Body(min_length=1)],
    container: ContainerDep,
    _client: IngestClient,
) -> IngestResponse:
    limit = container.settings.ingest_max_bulk_request_items
    if len(entries) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"batch too large: {len(entries)} > {limit} entries",
        )
    return IngestResponse(accepted=accept_entries(container, entries))


@router.post(
    "/api/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    deprecated=True,
    summary="Legacy v0 ingest endpoint (use POST /api/v1/logs)",
)
async def ingest_legacy(entry: LogEntryIn, container: ContainerDep, _client: IngestClient) -> IngestResponse:
    return IngestResponse(accepted=accept_entries(container, [entry]))
