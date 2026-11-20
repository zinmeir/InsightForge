"""A tiny in-memory stand-in for AsyncElasticsearch, covering what InsightForge uses."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any


class FakeNotFound(Exception):
    pass


def _matches(query: dict[str, Any] | None, doc: dict[str, Any]) -> bool:
    if not query or "match_all" in query:
        return True
    if "term" in query:
        [(field, value)] = query["term"].items()
        return doc.get(field) == value
    if "terms" in query:
        [(field, values)] = query["terms"].items()
        return doc.get(field) in values
    if "bool" in query:
        clauses = query["bool"].get("filter", []) + query["bool"].get("must", [])
        should = query["bool"].get("should")
        if should and not any(_matches(c, doc) for c in should):
            return False
        return all(_matches(c, doc) for c in clauses)
    if "range" in query:
        [(field, bounds)] = query["range"].items()
        value = doc.get(field, "")
        return bounds.get("gte", "") <= value <= bounds.get("lte", "￿")
    if "wildcard" in query:
        import fnmatch

        [(field, spec)] = query["wildcard"].items()
        return fnmatch.fnmatchcase(doc.get(field, ""), spec["value"])
    if "simple_query_string" in query:
        needle = query["simple_query_string"]["query"].lower()
        return all(word in doc.get("message", "").lower() for word in needle.split())
    raise NotImplementedError(query)


def _millis(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


class _Indices:
    def __init__(self, es: FakeES) -> None:
        self._es = es

    async def exists(self, index: str) -> bool:
        return index in self._es.docs


class FakeES:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.bulk_calls = 0
        self.indices = _Indices(self)
        self.closed = False

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self.closed = True

    async def index(self, index: str, id: str, document: dict[str, Any], refresh: Any = None) -> dict:
        self.docs[index][id] = document
        return {"result": "created"}

    async def get(self, index: str, id: str) -> dict:
        try:
            return {"_source": self.docs[index][id]}
        except KeyError:
            raise FakeNotFound(id) from None

    async def delete(self, index: str, id: str, refresh: Any = None) -> dict:
        if id not in self.docs[index]:
            raise FakeNotFound(id)
        del self.docs[index][id]
        return {"result": "deleted"}

    async def bulk(self, operations: list[dict[str, Any]]) -> dict:
        self.bulk_calls += 1
        items = []
        for action, doc in zip(operations[::2], operations[1::2], strict=True):
            index = action["create"]["_index"]
            self.docs[index][doc["event_id"]] = doc
            items.append({"create": {"status": 201}})
        return {"errors": False, "items": items}

    async def search(self, index: str, query: dict | None = None, size: int = 10, **kwargs: Any) -> dict:
        docs = [d for d in self.docs.get(index, {}).values() if _matches(query, d)]
        if index.endswith("-logs"):
            docs.sort(key=lambda d: (_millis(d["@timestamp"]), d["event_id"]), reverse=True)
            if after := kwargs.get("search_after"):
                docs = [d for d in docs if (_millis(d["@timestamp"]), d["event_id"]) < tuple(after)]
        total = len(docs)
        hits = [
            {"_source": d, "sort": [_millis(d["@timestamp"]), d["event_id"]] if "@timestamp" in d else []}
            for d in docs[: size or 0]
        ]
        resp: dict[str, Any] = {"hits": {"total": {"value": total, "relation": "eq"}, "hits": hits}}
        if aggs := kwargs.get("aggs"):
            resp["aggregations"] = {name: self._agg(spec, docs) for name, spec in aggs.items()}
        return resp

    def _agg(self, spec: dict[str, Any], docs: list[dict[str, Any]]) -> dict[str, Any]:
        if "terms" in spec:
            field = spec["terms"]["field"]
            groups: dict[str, list] = defaultdict(list)
            for d in docs:
                groups[d.get(field)].append(d)
            buckets = []
            for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                bucket = {"key": key, "doc_count": len(members)}
                for sub_name, sub in spec.get("aggs", {}).items():
                    bucket[sub_name] = self._agg(sub, members)
                buckets.append(bucket)
            return {"buckets": buckets}
        if "cardinality" in spec:
            return {"value": len(Counter(d.get(spec["cardinality"]["field"]) for d in docs))}
        if "date_histogram" in spec:
            return {"buckets": []}
        raise NotImplementedError(spec)
