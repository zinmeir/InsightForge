"""Elasticsearch-backed persistence for alert rules and alerts."""

from __future__ import annotations

from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError

from app.schemas import Alert, AlertRule

OPEN_STATUSES = ("firing", "acknowledged")


class RuleStore:
    def __init__(self, es: AsyncElasticsearch, index: str) -> None:
        self._es = es
        self._index = index

    async def list(self) -> list[AlertRule]:
        resp = await self._es.search(
            index=self._index, query={"match_all": {}}, size=1_000, sort=[{"created_at": "asc"}]
        )
        return [AlertRule.model_validate(hit["_source"]) for hit in resp["hits"]["hits"]]

    async def get(self, rule_id: str) -> AlertRule | None:
        try:
            resp = await self._es.get(index=self._index, id=rule_id)
        except NotFoundError:
            return None
        return AlertRule.model_validate(resp["_source"])

    async def save(self, rule: AlertRule) -> AlertRule:
        await self._es.index(
            index=self._index, id=rule.id, document=rule.model_dump(mode="json"), refresh="wait_for"
        )
        return rule

    async def delete(self, rule_id: str) -> bool:
        try:
            await self._es.delete(index=self._index, id=rule_id, refresh="wait_for")
        except NotFoundError:
            return False
        return True


class AlertStore:
    def __init__(self, es: AsyncElasticsearch, index: str) -> None:
        self._es = es
        self._index = index

    async def save(self, alert: Alert, *, refresh: bool = False) -> None:
        await self._es.index(
            index=self._index,
            id=alert.id,
            document=alert.model_dump(mode="json"),
            refresh="wait_for" if refresh else False,
        )

    async def get(self, alert_id: str) -> Alert | None:
        try:
            resp = await self._es.get(index=self._index, id=alert_id)
        except NotFoundError:
            return None
        return Alert.model_validate(resp["_source"])

    async def list_open(self) -> list[Alert]:
        resp = await self._es.search(
            index=self._index, query={"terms": {"status": list(OPEN_STATUSES)}}, size=10_000
        )
        return [Alert.model_validate(hit["_source"]) for hit in resp["hits"]["hits"]]

    async def search(
        self,
        *,
        statuses: list[str] | None = None,
        severity: str | None = None,
        service: str | None = None,
        size: int = 50,
        offset: int = 0,
    ) -> tuple[list[Alert], int]:
        filters: list[dict[str, Any]] = []
        if statuses:
            filters.append({"terms": {"status": statuses}})
        if severity:
            filters.append({"term": {"severity": severity}})
        if service:
            filters.append({"term": {"service": service}})
        resp = await self._es.search(
            index=self._index,
            query={"bool": {"filter": filters}} if filters else {"match_all": {}},
            sort=[{"last_seen": "desc"}],
            size=size,
            from_=offset,
            track_total_hits=True,
        )
        items = [Alert.model_validate(hit["_source"]) for hit in resp["hits"]["hits"]]
        return items, resp["hits"]["total"]["value"]
