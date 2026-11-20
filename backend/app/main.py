"""InsightForge API - application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from elasticsearch import ApiError, TransportError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import alerts, auth, health, ingest, logs, stats, stream
from app.container import Container
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_var
from app.default_rules import default_rules
from app.middleware import RequestContextMiddleware
from app.services import elastic
from app.services.alert_engine import AlertEngine
from app.services.alert_manager import AlertManager
from app.services.broker import LogBroker
from app.services.ingest_buffer import IngestBuffer
from app.services.notifier import Notifier
from app.services.queries import QueryError
from app.services.stores import AlertStore, RuleStore

logger = logging.getLogger("insightforge")


def create_app(settings: Settings | None = None, *, es_client: Any = None, bootstrap: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        es = es_client if es_client is not None else elastic.create_client(settings)
        created: set[str] = set()
        if bootstrap:
            created = await elastic.bootstrap(es, settings)

        rule_store = RuleStore(es, settings.rules_index)
        alert_store = AlertStore(es, settings.alerts_index)
        if settings.rules_index in created:
            for rule in default_rules():
                await rule_store.save(rule)
            logger.info("seeded default alert rules")

        notifier = Notifier(settings)
        manager = AlertManager(
            AlertEngine(), alert_store, notifier, sweep_interval=settings.alert_sweep_interval_seconds
        )
        await manager.start(await rule_store.list())

        buffer = IngestBuffer(
            elastic.make_bulk_sink(es, settings.logs_data_stream),
            batch_size=settings.ingest_batch_size,
            flush_interval=settings.ingest_flush_interval_seconds,
            max_queue_size=settings.ingest_queue_max_size,
            max_retries=settings.ingest_max_retries,
        )
        await buffer.start()

        app.state.container = Container(
            settings=settings,
            es=es,
            buffer=buffer,
            broker=LogBroker(settings.stream_subscriber_queue_size),
            alert_manager=manager,
            rules=rule_store,
            alerts=alert_store,
            notifier=notifier,
        )
        logger.info("InsightForge API started", extra={"version": __version__, "env": settings.environment})
        try:
            yield
        finally:
            # Order matters: stop accepting/flush logs first, then alerts, then close clients.
            await buffer.stop()
            await manager.stop()
            await notifier.aclose()
            await es.close()
            logger.info("InsightForge API stopped")

    app = FastAPI(
        title="InsightForge API",
        version=__version__,
        description="Real-time log ingestion, search and alerting.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,  # bearer tokens, not cookies
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(RequestContextMiddleware)

    for router in (
        health.router,
        auth.router,
        ingest.router,
        logs.router,
        stats.router,
        alerts.alerts_router,
        alerts.rules_router,
        alerts.notifications_router,
        stream.router,
    ):
        app.include_router(router)

    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(QueryError)
    async def _query_error(_: Request, exc: QueryError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ApiError)
    async def _es_api_error(_: Request, exc: ApiError) -> JSONResponse:
        logger.error("elasticsearch error", extra={"status": exc.meta.status, "error": str(exc)})
        status = 503 if exc.meta.status in (429, 502, 503, 504) else 502
        return JSONResponse(
            status_code=status,
            content={"detail": "search backend error", "request_id": request_id_var.get()},
        )

    @app.exception_handler(TransportError)
    async def _es_transport_error(_: Request, exc: TransportError) -> JSONResponse:
        logger.error("elasticsearch unreachable", extra={"error": str(exc)})
        return JSONResponse(
            status_code=503,
            content={"detail": "search backend unavailable", "request_id": request_id_var.get()},
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500, content={"detail": "internal server error", "request_id": request_id_var.get()}
        )


app = create_app()
