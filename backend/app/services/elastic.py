"""Elasticsearch client factory, cluster bootstrap and the bulk-write sink."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch import ConnectionError as ESConnectionError

from app.core.config import Settings
from app.services.ingest_buffer import SinkResult

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def create_client(settings: Settings) -> AsyncElasticsearch:
    kwargs: dict[str, Any] = {
        "request_timeout": settings.elasticsearch_request_timeout,
        "retry_on_timeout": True,
        "max_retries": 2,
    }
    if settings.elasticsearch_api_key:
        kwargs["api_key"] = settings.elasticsearch_api_key.get_secret_value()
    elif settings.elasticsearch_username and settings.elasticsearch_password:
        kwargs["basic_auth"] = (
            settings.elasticsearch_username,
            settings.elasticsearch_password.get_secret_value(),
        )
    if settings.elasticsearch_url.startswith("https"):
        kwargs["verify_certs"] = settings.elasticsearch_verify_certs
        if settings.elasticsearch_ca_certs:
            kwargs["ca_certs"] = settings.elasticsearch_ca_certs
    return AsyncElasticsearch(settings.elasticsearch_url, **kwargs)


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

LOG_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "@timestamp": {"type": "date"},
        "ingested_at": {"type": "date"},
        "event_id": {"type": "keyword"},
        "level": {"type": "keyword"},
        "service": {"type": "keyword"},
        "message": {"type": "text"},
        "host": {"type": "keyword"},
        "environment": {"type": "keyword"},
        "trace_id": {"type": "keyword"},
        "span_id": {"type": "keyword"},
        "attributes": {"type": "flattened", "ignore_above": 1024},
    },
}

ALERT_MAPPINGS: dict[str, Any] = {
    "dynamic": "strict",
    "properties": {
        "id": {"type": "keyword"},
        "fingerprint": {"type": "keyword"},
        "rule_id": {"type": "keyword"},
        "rule_name": {"type": "keyword"},
        "severity": {"type": "keyword"},
        "service": {"type": "keyword"},
        "status": {"type": "keyword"},
        "summary": {"type": "text"},
        "sample_message": {"type": "text", "index": False},
        "count": {"type": "long"},
        "first_seen": {"type": "date"},
        "last_seen": {"type": "date"},
        "acknowledged_by": {"type": "keyword"},
        "acknowledged_at": {"type": "date"},
        "resolved_at": {"type": "date"},
        "resolved_reason": {"type": "keyword"},
    },
}

RULE_MAPPINGS: dict[str, Any] = {
    # Rules are read back whole; only index what we filter/sort on.
    "dynamic": False,
    "properties": {
        "id": {"type": "keyword"},
        "name": {"type": "keyword"},
        "enabled": {"type": "boolean"},
        "created_at": {"type": "date"},
    },
}


async def wait_for_cluster(es: AsyncElasticsearch, retries: int) -> None:
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            health = await es.cluster.health(wait_for_status="yellow", timeout="5s")
            logger.info("connected to Elasticsearch", extra={"cluster_status": health["status"]})
            return
        except (ESConnectionError, TimeoutError) as exc:
            logger.warning("waiting for Elasticsearch (%d/%d): %s", attempt, retries, exc)
        except Exception as exc:
            logger.warning("Elasticsearch not ready (%d/%d): %s", attempt, retries, exc)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 10.0)
    raise RuntimeError(f"Elasticsearch unreachable after {retries} attempts")


async def bootstrap(es: AsyncElasticsearch, settings: Settings) -> set[str]:
    """Idempotently create the ILM policy, index template, data stream and state indices.

    Returns the names of the indices that were newly created.
    """
    created: set[str] = set()
    await wait_for_cluster(es, settings.elasticsearch_bootstrap_retries)
    prefix = settings.index_prefix
    policy = f"{prefix}-logs-policy"

    await es.ilm.put_lifecycle(
        name=policy,
        policy={
            "phases": {
                "hot": {
                    "actions": {
                        "rollover": {
                            "max_age": settings.rollover_max_age,
                            "max_primary_shard_size": settings.rollover_max_primary_shard_size,
                        }
                    }
                },
                "delete": {
                    "min_age": f"{settings.log_retention_days}d",
                    "actions": {"delete": {}},
                },
            }
        },
    )
    await es.indices.put_index_template(
        name=f"{prefix}-logs-template",
        index_patterns=[f"{settings.logs_data_stream}*"],
        data_stream={},
        priority=500,
        template={
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": settings.index_replicas,
                "index.lifecycle.name": policy,
                "refresh_interval": "1s",
            },
            "mappings": LOG_MAPPINGS,
        },
        meta={"managed_by": "insightforge"},
    )
    try:
        await es.indices.get_data_stream(name=settings.logs_data_stream)
    except NotFoundError:
        await es.indices.create_data_stream(name=settings.logs_data_stream)
        logger.info("created data stream %s", settings.logs_data_stream)

    for index, mappings in (
        (settings.alerts_index, ALERT_MAPPINGS),
        (settings.rules_index, RULE_MAPPINGS),
    ):
        if not await es.indices.exists(index=index):
            await es.indices.create(
                index=index,
                settings={"number_of_shards": 1, "number_of_replicas": settings.index_replicas},
                mappings=mappings,
            )
            created.add(index)
            logger.info("created index %s", index)
    return created


def make_bulk_sink(es: AsyncElasticsearch, data_stream: str):
    """Return a coroutine that writes documents with the bulk API and classifies failures."""

    async def sink(docs: list[dict[str, Any]]) -> SinkResult:
        operations: list[dict[str, Any]] = []
        for doc in docs:
            operations.append({"create": {"_index": data_stream}})  # data streams are append-only
            operations.append(doc)
        resp = await es.bulk(operations=operations)
        if not resp.get("errors"):
            return SinkResult(written=len(docs))

        result = SinkResult()
        for doc, item in zip(docs, resp["items"], strict=True):
            outcome = item.get("create", {})
            status = outcome.get("status", 500)
            if status < 300:
                result.written += 1
            elif status in RETRYABLE_STATUSES:
                result.retryable.append(doc)
            else:
                result.rejected += 1
                logger.warning(
                    "log rejected by Elasticsearch",
                    extra={"status": status, "error": outcome.get("error"), "service": doc.get("service")},
                )
        return result

    return sink
