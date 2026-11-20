from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import ContainerDep, CurrentUser
from app.schemas import LogLevel, LogPage, LogRecord
from app.services.queries import (
    LOG_SORT,
    TimeRange,
    build_log_query,
    decode_cursor,
    encode_cursor,
)

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])

EXPORT_LIMIT = 10_000


class LogFilters:
    """Query parameters shared by search, export and stats endpoints."""

    def __init__(
        self,
        q: Annotated[str | None, Query(max_length=512, description="Full-text query on message")] = None,
        level: Annotated[list[LogLevel], Query()] = [],  # noqa: B006 - FastAPI copies defaults
        service: Annotated[list[str], Query(description="Exact names or wildcards (payment-*)")] = [],  # noqa: B006
        trace_id: Annotated[str | None, Query(max_length=128)] = None,
        host: Annotated[str | None, Query(max_length=255)] = None,
        from_: Annotated[str | None, Query(alias="from", description="ISO-8601 or now-15m")] = None,
        to: Annotated[str | None, Query(description="ISO-8601 or now")] = None,
    ) -> None:
        self.q = q
        self.levels = level
        self.services = service
        self.trace_id = trace_id
        self.host = host
        self.from_ = from_
        self.to = to

    def time_range(self, default_start: str = "now-24h") -> TimeRange:
        return TimeRange.parse(self.from_, self.to, default_start=default_start)

    def query(self, default_start: str = "now-24h") -> dict[str, Any]:
        return build_log_query(
            time_range=self.time_range(default_start),
            text=self.q,
            levels=self.levels,
            services=self.services,
            trace_id=self.trace_id,
            host=self.host,
        )


Filters = Annotated[LogFilters, Depends()]


@router.get("", response_model=LogPage, summary="Search logs (newest first, cursor-paginated)")
async def search_logs(
    container: ContainerDep,
    _user: CurrentUser,
    filters: Filters,
    size: Annotated[int, Query(ge=1, le=500)] = 50,
    cursor: Annotated[str | None, Query(description="next_cursor from the previous page")] = None,
) -> LogPage:
    params: dict[str, Any] = {
        "index": container.settings.logs_data_stream,
        "query": filters.query(),
        "sort": LOG_SORT,
        "size": size,
        "track_total_hits": 10_000,
    }
    if cursor:
        params["search_after"] = decode_cursor(cursor)
    resp = await container.es.search(**params)
    hits = resp["hits"]["hits"]
    total = resp["hits"]["total"]
    return LogPage(
        items=[LogRecord.from_document(h["_source"]) for h in hits],
        total=total["value"],
        total_is_lower_bound=total.get("relation") == "gte",
        next_cursor=encode_cursor(hits[-1]["sort"]) if len(hits) == size else None,
    )


@router.get("/export", summary="Export matching logs as CSV or NDJSON")
async def export_logs(
    container: ContainerDep,
    _user: CurrentUser,
    filters: Filters,
    format: Annotated[Literal["csv", "ndjson"], Query()] = "csv",
    limit: Annotated[int, Query(ge=1, le=EXPORT_LIMIT)] = 1_000,
) -> StreamingResponse:
    resp = await container.es.search(
        index=container.settings.logs_data_stream, query=filters.query(), sort=LOG_SORT, size=limit
    )
    records = [LogRecord.from_document(h["_source"]) for h in resp["hits"]["hits"]]

    def as_ndjson() -> Iterator[str]:
        for r in records:
            yield r.model_dump_json() + "\n"

    def as_csv() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["timestamp", "level", "service", "host", "trace_id", "message", "attributes"])
        for r in records:
            writer.writerow(
                [
                    r.timestamp.isoformat(),
                    r.level.value,
                    r.service,
                    r.host or "",
                    r.trace_id or "",
                    _csv_safe(r.message),
                    json.dumps(r.attributes) if r.attributes else "",
                ]
            )
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
        yield buf.getvalue()

    media = "text/csv" if format == "csv" else "application/x-ndjson"
    body = as_csv() if format == "csv" else as_ndjson()
    filename = f"insightforge-logs.{format}"
    return StreamingResponse(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _csv_safe(value: str) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @ at the start of a cell)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/{log_id}", response_model=LogRecord, summary="Fetch one log by id")
async def get_log(log_id: str, container: ContainerDep, _user: CurrentUser) -> LogRecord:
    resp = await container.es.search(
        index=container.settings.logs_data_stream, query={"term": {"event_id": log_id}}, size=1
    )
    hits = resp["hits"]["hits"]
    if not hits:
        raise HTTPException(status_code=404, detail="log not found")
    return LogRecord.from_document(hits[0]["_source"])
