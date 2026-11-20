"""End-to-end API tests against an in-memory Elasticsearch fake.

Requires the full runtime dependencies (FastAPI, elasticsearch, httpx); skipped otherwise.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("elasticsearch")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import stores  # noqa: E402
from tests.fake_es import FakeES, FakeNotFound  # noqa: E402

API_KEY = "test-ingest-key"


@pytest.fixture(autouse=True)
def _fake_not_found(monkeypatch):
    # Stores catch elasticsearch.NotFoundError; make them catch the fake's error too.
    monkeypatch.setattr(stores, "NotFoundError", FakeNotFound)


def make_settings(**overrides) -> Settings:
    base = dict(
        environment="test",
        log_format="console",
        log_level="WARNING",
        jwt_secret="x" * 40,
        admin_password="s3cret-pass",
        viewer_username="viewer",
        viewer_password="viewer-pass",
        ingest_api_keys=API_KEY,
        ingest_flush_interval_seconds=0.02,
        ingest_max_bulk_request_items=5,
        alert_sweep_interval_seconds=3600,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


@pytest.fixture
def es():
    return FakeES()


@pytest.fixture
def client(es):
    app = create_app(make_settings(), es_client=es, bootstrap=False)
    with TestClient(app) as c:
        yield c


def login(client, username="admin", password="s3cret-pass") -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def ingest(client, **fields):
    body = {"level": "INFO", "service": "api", "message": "hello", **fields}
    return client.post("/api/v1/logs", json=body, headers={"X-API-Key": API_KEY})


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_health_and_metrics(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["ready"] is True
    assert client.get("/metrics").status_code == 200
    assert "x-request-id" in client.get("/healthz").headers


def test_login_and_roles(client):
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    admin = login(client)
    assert client.get("/api/v1/auth/me", headers=admin).json()["role"] == "admin"
    viewer = login(client, "viewer", "viewer-pass")
    assert client.get("/api/v1/auth/me", headers=viewer).json()["role"] == "viewer"
    assert client.get("/api/v1/logs").status_code == 401
    assert client.get("/api/v1/logs", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_ingest_requires_credentials(client):
    body = {"level": "INFO", "service": "api", "message": "x"}
    assert client.post("/api/v1/logs", json=body).status_code == 401
    assert client.post("/api/v1/logs", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    viewer = login(client, "viewer", "viewer-pass")
    assert client.post("/api/v1/logs", json=body, headers=viewer).status_code == 403
    assert client.post("/api/v1/logs", json=body, headers=login(client)).status_code == 202


def test_ingest_validation_and_bulk_limits(client):
    assert ingest(client, level="NOPE").status_code == 422
    headers = {"X-API-Key": API_KEY}
    batch = [{"level": "INFO", "service": "api", "message": str(i)} for i in range(6)]
    assert client.post("/api/v1/logs/bulk", json=batch, headers=headers).status_code == 413
    resp = client.post("/api/v1/logs/bulk", json=batch[:5], headers=headers)
    assert resp.status_code == 202 and resp.json() == {"status": "accepted", "accepted": 5}
    assert client.post("/api/v1/logs/bulk", json=[], headers=headers).status_code == 422


def test_legacy_endpoint_still_works(client):
    resp = client.post(
        "/api/ingest",
        json={"level": "ERROR", "service": "payment-gateway", "message": "CRITICAL: Stripe API timeout"},
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 202


def test_search_pagination_and_filters(client, es):
    for i in range(3):
        assert ingest(client, message=f"request {i}").status_code == 202
    assert ingest(client, level="ERROR", service="db", message="deadlock detected").status_code == 202
    wait_for(lambda: len(es.docs["insightforge-logs"]) == 4)
    auth = login(client)
    params = {"from": "now-1h", "to": "now"}

    page1 = client.get("/api/v1/logs", params={**params, "size": 2}, headers=auth).json()
    assert page1["total"] == 4 and len(page1["items"]) == 2 and page1["next_cursor"]
    page2 = client.get("/api/v1/logs", params={**params, "size": 2, "cursor": page1["next_cursor"]}, headers=auth)
    ids = {i["id"] for i in page1["items"]} | {i["id"] for i in page2.json()["items"]}
    assert len(ids) == 4

    errors = client.get("/api/v1/logs", params={**params, "level": "ERROR"}, headers=auth).json()
    assert [i["service"] for i in errors["items"]] == ["db"]
    found = client.get("/api/v1/logs", params={**params, "q": "deadlock"}, headers=auth).json()
    assert found["total"] == 1
    one = client.get(f"/api/v1/logs/{found['items'][0]['id']}", headers=auth)
    assert one.json()["message"] == "deadlock detected"
    assert client.get("/api/v1/logs/missing", headers=auth).status_code == 404

    assert client.get("/api/v1/logs", params={"from": "garbage"}, headers=auth).status_code == 400
    assert client.get("/api/v1/logs", params={"cursor": "bad"}, headers=auth).status_code == 400


def test_stats_endpoints(client, es):
    ingest(client, level="ERROR", service="db")
    ingest(client, level="INFO", service="api")
    wait_for(lambda: len(es.docs["insightforge-logs"]) == 2)
    auth = login(client)
    overview = client.get("/api/v1/stats/overview", headers=auth).json()
    assert overview["total"] == 2 and overview["error_rate"] == 0.5 and overview["services"] == 2
    services = client.get("/api/v1/stats/services", headers=auth).json()
    assert {s["service"] for s in services} == {"db", "api"}
    hist = client.get("/api/v1/stats/histogram", params={"from": "now-15m"}, headers=auth).json()
    assert hist["interval"] == "30s"


def test_export_csv_escapes_formulas(client, es):
    ingest(client, message="=HYPERLINK(evil)")
    wait_for(lambda: len(es.docs["insightforge-logs"]) == 1)
    resp = client.get("/api/v1/logs/export", params={"format": "csv"}, headers=login(client))
    assert resp.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK(evil)" in resp.text


def test_rule_crud_and_alert_lifecycle(client):
    admin = login(client)
    viewer = login(client, "viewer", "viewer-pass")
    rule_body = {"name": "Crit", "severity": "critical", "condition": {"levels": ["CRITICAL"]}}
    assert client.post("/api/v1/rules", json=rule_body, headers=viewer).status_code == 403
    created = client.post("/api/v1/rules", json=rule_body, headers=admin)
    assert created.status_code == 201
    rule_id = created.json()["id"]
    assert [r["id"] for r in client.get("/api/v1/rules", headers=viewer).json()] == [rule_id]

    for _ in range(3):
        ingest(client, level="CRITICAL", service="payments", message="card processor down")
    wait_for(lambda: client.get("/api/v1/alerts", headers=viewer).json()["total"] == 1)
    alert = client.get("/api/v1/alerts", headers=viewer).json()["items"][0]
    wait_for(lambda: client.get(f"/api/v1/alerts/{alert['id']}", headers=viewer).json()["count"] == 3)
    assert alert["service"] == "payments" and alert["severity"] == "critical"

    acked = client.post(f"/api/v1/alerts/{alert['id']}/acknowledge", headers=viewer).json()
    assert acked["status"] == "acknowledged" and acked["acknowledged_by"] == "viewer"
    resolved = client.post(f"/api/v1/alerts/{alert['id']}/resolve", headers=admin).json()
    assert resolved["status"] == "resolved"
    assert client.post(f"/api/v1/alerts/{alert['id']}/resolve", headers=admin).status_code == 409
    history = client.get("/api/v1/alerts", params={"status": "resolved"}, headers=viewer).json()
    assert history["total"] == 1

    patched = client.patch(f"/api/v1/rules/{rule_id}", json={"enabled": False}, headers=admin).json()
    assert patched["enabled"] is False and patched["name"] == "Crit"
    assert client.delete(f"/api/v1/rules/{rule_id}", headers=admin).status_code == 204
    assert client.delete(f"/api/v1/rules/{rule_id}", headers=admin).status_code == 404


def test_notification_channels(client):
    auth = login(client)
    assert client.get("/api/v1/notifications/channels", headers=auth).json()["configured"] == []
    resp = client.post("/api/v1/notifications/test", json={"channel": "slack"}, headers=auth)
    assert resp.status_code == 400


def test_auth_can_be_disabled(es):
    app = create_app(make_settings(auth_enabled=False), es_client=es, bootstrap=False)
    with TestClient(app) as c:
        assert c.get("/api/v1/logs").status_code == 200
        assert c.post("/api/v1/logs", json={"level": "INFO", "service": "a", "message": "b"}).status_code == 202


def test_production_refuses_insecure_defaults():
    with pytest.raises(ValueError, match="Insecure production configuration"):
        Settings(_env_file=None, environment="production")


def test_patterns_endpoint(client, es):
    for ms in (120, 340, 9000):
        ingest(client, level="ERROR", service="payments", message=f"timeout after {ms}ms calling stripe")
    ingest(client, level="INFO", service="api", message="GET /v1/orders 200 in 12ms")
    wait_for(lambda: len(es.docs["insightforge-logs"]) == 4)
    auth = login(client)
    report = client.get("/api/v1/stats/patterns", params={"level": "ERROR"}, headers=auth).json()
    assert report["sample_size"] == 3 and report["sampled"] is False
    [top] = report["patterns"]
    assert top["pattern"] == "timeout after <num>ms calling stripe" and top["count"] == 3
    assert top["query"] == '"timeout after" "calling stripe"'
    everything = client.get("/api/v1/stats/patterns", headers=auth).json()
    assert len(everything["patterns"]) == 2
