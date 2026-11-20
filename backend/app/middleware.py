"""Pure-ASGI middleware: request IDs, access logs and HTTP metrics.

Written as raw ASGI (not BaseHTTPMiddleware) so streaming responses such as SSE are untouched.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.logging import request_id_var

logger = logging.getLogger("insightforge.access")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
_QUIET_PATHS = {"/healthz", "/readyz", "/metrics"}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - started
            route = _route_template(scope)
            method = scope.get("method", "GET")
            metrics.HTTP_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
            metrics.HTTP_LATENCY.labels(method=method, route=route).observe(duration)
            if scope.get("path") not in _QUIET_PATHS:
                logger.info(
                    "%s %s %d",
                    method,
                    scope.get("path"),
                    status_code,
                    extra={"status": status_code, "duration_ms": round(duration * 1000, 2), "route": route},
                )
            request_id_var.reset(token)


def _route_template(scope: Scope) -> str:
    """Low-cardinality route label (``/api/v1/rules/{rule_id}``, not the concrete path)."""
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    app = scope.get("app")
    for candidate in getattr(getattr(app, "router", None), "routes", []):
        match, _ = candidate.matches(scope)
        if match == Match.FULL:
            return getattr(candidate, "path", "unknown")
    return "unmatched"
