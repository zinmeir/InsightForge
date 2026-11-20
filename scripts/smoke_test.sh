#!/usr/bin/env bash
# End-to-end smoke test against a running stack (real Elasticsearch, real nginx).
#   docker compose up -d --build --wait && ./scripts/smoke_test.sh
set -euo pipefail

UI="${UI_URL:-http://localhost:3000}"
API="${API_URL:-http://localhost:8000}"
KEY="${INGEST_API_KEY:-dev-ingest-key}"
ADMIN_USER="${ADMIN_USERNAME:-admin}"
PASS="${ADMIN_PASSWORD:-admin}"
RUN_ID="smoke-$(date +%s)"

pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; exit 1; }
need() { command -v "$1" >/dev/null || fail "missing dependency: $1"; }
need curl; need jq

echo "InsightForge smoke test ($RUN_ID)"

curl -fsS "$API/readyz" | jq -e '.ready == true' >/dev/null && pass "backend ready" || fail "backend not ready"
curl -fsS "$UI/healthz" >/dev/null && pass "frontend serving" || fail "frontend down"

TOKEN=$(curl -fsS -X POST "$UI/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$PASS\"}" | jq -r .access_token)
[[ -n "$TOKEN" && "$TOKEN" != null ]] && pass "login through nginx" || fail "login failed"
AUTH=(-H "Authorization: Bearer $TOKEN")

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/api/v1/logs" -H 'Content-Type: application/json' \
  -d '{"level":"INFO","service":"x","message":"y"}')
[[ "$code" == 401 ]] && pass "ingest without key rejected" || fail "expected 401, got $code"

curl -fsS -X POST "$API/api/v1/logs/bulk" -H "X-API-Key: $KEY" -H 'Content-Type: application/json' -d "[
  {\"level\":\"INFO\",\"service\":\"$RUN_ID\",\"message\":\"checkout started\"},
  {\"level\":\"WARN\",\"service\":\"$RUN_ID\",\"message\":\"retrying payment\",\"attributes\":{\"attempt\":2}},
  {\"level\":\"CRITICAL\",\"service\":\"$RUN_ID\",\"message\":\"CRITICAL: Stripe API timeout detected\",\"trace_id\":\"$RUN_ID-trace\"}
]" | jq -e '.accepted == 3' >/dev/null && pass "bulk ingest accepted" || fail "bulk ingest failed"

found=0
for _ in $(seq 1 20); do
  total=$(curl -fsS "${AUTH[@]}" "$UI/api/v1/logs?service=$RUN_ID&from=now-5m" | jq .total)
  [[ "$total" == 3 ]] && found=1 && break
  sleep 0.5
done
[[ $found == 1 ]] && pass "logs searchable in Elasticsearch" || fail "logs not indexed (total=$total)"

curl -fsS "${AUTH[@]}" "$UI/api/v1/logs?service=$RUN_ID&q=stripe%20timeout&from=now-5m" | jq -e '.total == 1' >/dev/null \
  && pass "full-text search" || fail "full-text search"
curl -fsS "${AUTH[@]}" "$UI/api/v1/stats/services?from=now-5m" | jq -e "map(select(.service == \"$RUN_ID\")) | .[0].total == 3" >/dev/null \
  && pass "service aggregation" || fail "service aggregation"
curl -fsS "${AUTH[@]}" "$UI/api/v1/stats/histogram?from=now-15m" | jq -e '.buckets | length > 0' >/dev/null \
  && pass "histogram" || fail "histogram"

alert=""
for _ in $(seq 1 20); do
  alert=$(curl -fsS "${AUTH[@]}" "$UI/api/v1/alerts?service=$RUN_ID" | jq -r '.items[0].id // empty')
  [[ -n "$alert" ]] && break
  sleep 0.5
done
[[ -n "$alert" ]] && pass "CRITICAL log opened an alert" || fail "no alert opened"
curl -fsS -X POST "${AUTH[@]}" "$UI/api/v1/alerts/$alert/resolve" | jq -e '.status == "resolved"' >/dev/null \
  && pass "alert resolved" || fail "resolve failed"

# Capture output first: with pipefail, `curl | grep -q` fails when grep exits early (SIGPIPE).
csv=$(curl -fsS "${AUTH[@]}" "$UI/api/v1/logs/export?format=csv&service=$RUN_ID&from=now-5m")
[[ "$csv" == *"retrying payment"* ]] && pass "CSV export" || fail "CSV export"

stream=$(curl -sN --max-time 3 "${AUTH[@]}" "$UI/api/v1/stream" || true)
[[ "$stream" == retry:* ]] && pass "live tail stream through nginx" || fail "live tail stream"

metrics=$(curl -fsS "$API/metrics")
[[ "$metrics" == *insightforge_logs_indexed_total* ]] && pass "prometheus metrics" || fail "metrics"

echo "All smoke checks passed."
