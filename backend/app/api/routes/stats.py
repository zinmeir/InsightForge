from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import ContainerDep, CurrentUser
from app.api.routes.logs import Filters
from app.schemas import Histogram, OverviewStats, PatternReport, ServiceStat
from app.services import queries
from app.services.patterns import extract_patterns

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

Interval = Literal["1s", "5s", "10s", "30s", "1m", "5m", "10m", "30m", "1h", "3h", "6h", "12h", "1d", "7d"]
DEFAULT_WINDOW = "now-1h"


@router.get("/overview", response_model=OverviewStats)
async def overview(container: ContainerDep, _user: CurrentUser, filters: Filters) -> OverviewStats:
    resp = await container.es.search(
        index=container.settings.logs_data_stream,
        query=filters.query(DEFAULT_WINDOW),
        size=0,
        track_total_hits=True,
        aggs=queries.overview_aggs(),
    )
    total, by_level, error_rate, services = queries.parse_overview(resp)
    return OverviewStats(
        total=total,
        by_level=by_level,
        error_rate=error_rate,
        services=services,
        open_alerts=len(container.alert_manager.open_alerts),
    )


@router.get("/histogram", response_model=Histogram, summary="Log volume over time, split by level")
async def histogram(
    container: ContainerDep,
    _user: CurrentUser,
    filters: Filters,
    interval: Annotated[Interval | None, Query(description="Defaults to ~60 buckets")] = None,
) -> Histogram:
    rng = filters.time_range(DEFAULT_WINDOW)
    chosen = interval or queries.pick_interval(rng.seconds)[0]
    # Guard against accidentally requesting hundreds of thousands of buckets.
    if interval:
        size = dict(queries.INTERVALS)[interval]
        if rng.seconds / size > 2_000:
            chosen = queries.pick_interval(rng.seconds, target_buckets=2_000)[0]
    resp = await container.es.search(
        index=container.settings.logs_data_stream,
        query=filters.query(DEFAULT_WINDOW),
        size=0,
        aggs=queries.histogram_aggs(rng, chosen),
    )
    return Histogram(interval=chosen, buckets=queries.parse_histogram(resp))


@router.get("/services", response_model=list[ServiceStat], summary="Volume and error rate per service")
async def services(
    container: ContainerDep,
    _user: CurrentUser,
    filters: Filters,
    size: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[ServiceStat]:
    resp = await container.es.search(
        index=container.settings.logs_data_stream,
        query=filters.query(DEFAULT_WINDOW),
        size=0,
        aggs=queries.services_aggs(size),
    )
    return queries.parse_services(resp)


@router.get(
    "/patterns",
    response_model=PatternReport,
    summary="Group similar log messages into patterns",
    description=(
        "Analyses the newest `sample` matching logs and collapses messages that differ only in "
        "numbers, ids, IPs, URLs or quoted values into templates such as "
        "`timeout after <num>ms calling stripe`. Each pattern carries a `query` usable as `q` "
        "on /api/v1/logs, and a trend comparing the newer and older half of the sample."
    ),
)
async def patterns(
    container: ContainerDep,
    _user: CurrentUser,
    filters: Filters,
    size: Annotated[int, Query(ge=1, le=100, description="Patterns to return")] = 20,
    sample: Annotated[int, Query(ge=100, le=10_000, description="Logs to analyse")] = 5_000,
) -> PatternReport:
    resp = await container.es.search(
        index=container.settings.logs_data_stream,
        query=filters.query(DEFAULT_WINDOW),
        sort=queries.LOG_SORT,
        size=sample,
        track_total_hits=True,
        source_includes=["@timestamp", "message", "service", "level"],
    )
    docs = [hit["_source"] for hit in resp["hits"]["hits"]]
    total = resp["hits"]["total"]["value"]
    return PatternReport(
        patterns=extract_patterns(docs, limit=size),
        sample_size=len(docs),
        total=total,
        sampled=total > len(docs),
    )
