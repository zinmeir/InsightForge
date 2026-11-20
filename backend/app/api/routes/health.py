from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import __version__
from app.api.deps import ContainerDep, CurrentUser
from app.core import metrics
from app.schemas import NotifyChannel

router = APIRouter(tags=["system"])


@router.get("/healthz", include_in_schema=False)
async def liveness() -> dict[str, str]:
    """Process is up. Never touches dependencies, so it can't cause restart storms."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readiness(container: ContainerDep) -> JSONResponse:
    checks: dict[str, object] = {}
    try:
        checks["elasticsearch"] = bool(await container.es.ping())
    except Exception:
        checks["elasticsearch"] = False
    checks["ingest_buffer"] = container.buffer.running
    checks["buffer_depth"] = container.buffer.depth
    ready = bool(checks["elasticsearch"]) and bool(checks["ingest_buffer"])
    return JSONResponse({"ready": ready, "checks": checks}, status_code=200 if ready else 503)


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(metrics.generate_latest(), media_type=metrics.CONTENT_TYPE_LATEST)


class SystemInfo(BaseModel):
    name: str
    version: str
    environment: str
    auth_enabled: bool
    retention_days: int
    notification_channels: list[NotifyChannel]
    buffer_depth: int
    buffer_capacity: int
    stream_subscribers: int
    last_flush_error: str | None


@router.get("/api/v1/system/info", response_model=SystemInfo)
async def system_info(container: ContainerDep, _user: CurrentUser) -> SystemInfo:
    s = container.settings
    return SystemInfo(
        name=s.app_name,
        version=__version__,
        environment=s.environment,
        auth_enabled=s.auth_enabled,
        retention_days=s.log_retention_days,
        notification_channels=container.notifier.configured_channels,
        buffer_depth=container.buffer.depth,
        buffer_capacity=container.buffer.capacity,
        stream_subscribers=container.broker.subscriber_count,
        last_flush_error=container.buffer.last_flush_error,
    )
