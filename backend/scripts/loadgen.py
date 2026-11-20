"""Realistic traffic simulator for InsightForge.

Sends batches of logs from a handful of fake microservices, with occasional incidents
(error bursts, latency spikes, a critical outage) so dashboards and alert rules have
something interesting to show.

    python -m scripts.loadgen --url http://localhost:8000 --api-key <key> --rate 50
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import signal
import time
import uuid
from datetime import datetime, timezone

import httpx

SERVICES = {
    "api-gateway": ["GET /v1/orders 200 in {ms}ms", "POST /v1/cart 201 in {ms}ms", "GET /v1/products 200 in {ms}ms"],
    "auth-service": ["user {user} logged in", "token refreshed for {user}", "session expired for {user}"],
    "payment-gateway": ["charge {id} captured", "refund {id} issued", "3DS challenge completed for {id}"],
    "inventory": ["stock reserved for sku {sku}", "reservation {id} released", "reindexed {n} products"],
    "notification-worker": ["email queued for {user}", "push delivered to {user}", "sms sent ({ms}ms)"],
    "search-service": ["query '{q}' returned {n} hits in {ms}ms", "index refreshed in {ms}ms"],
}
WARNINGS = [
    "slow query detected: {ms}ms on orders table",
    "retrying upstream call (attempt {n}/3)",
    "connection pool at {pct}% capacity",
    "cache miss ratio high: {pct}%",
]
ERRORS = [
    "upstream returned 503 Service Unavailable",
    "timeout after {ms}ms calling {dep}",
    "database deadlock detected; transaction rolled back",
    "failed to deserialize message from queue",
]
CRITICALS = [
    "CRITICAL: Stripe API timeout detected",
    "CRITICAL: primary database unreachable",
    "CRITICAL: disk usage at 98% on /var/lib/data",
]
QUERIES = ["red shoes", "laptop stand", "usb-c hub", "coffee grinder", "desk lamp"]
DEPS = ["postgres", "redis", "stripe", "kafka", "s3"]


def fill(template: str) -> str:
    return template.format(
        ms=random.randint(3, 900),
        user=f"user_{random.randint(1000, 9999)}",
        id=uuid.uuid4().hex[:10],
        sku=random.randint(10000, 99999),
        n=random.randint(1, 500),
        q=random.choice(QUERIES),
        pct=random.randint(70, 99),
        dep=random.choice(DEPS),
    )


class Simulator:
    def __init__(self) -> None:
        self.incident_service: str | None = None
        self.incident_until = 0.0

    def maybe_start_incident(self, chance: float) -> None:
        now = time.monotonic()
        if self.incident_service and now > self.incident_until:
            print(f"[loadgen] incident on {self.incident_service} resolved")
            self.incident_service = None
        if not self.incident_service and random.random() < chance:
            self.incident_service = random.choice(list(SERVICES))
            self.incident_until = now + random.uniform(20, 60)
            print(f"[loadgen] incident started on {self.incident_service}")

    def make_log(self) -> dict:
        service = random.choice(list(SERVICES))
        in_incident = service == self.incident_service
        roll = random.random()
        if in_incident and roll < 0.03:
            level, message = "CRITICAL", random.choice(CRITICALS)
        elif in_incident and roll < 0.5:
            level, message = "ERROR", fill(random.choice(ERRORS))
        elif roll < 0.01:
            level, message = "ERROR", fill(random.choice(ERRORS))
        elif roll < 0.06:
            level, message = "WARN", fill(random.choice(WARNINGS))
        elif roll < 0.10:
            level, message = "DEBUG", f"cache lookup key={uuid.uuid4().hex[:8]}"
        else:
            level, message = "INFO", fill(random.choice(SERVICES[service]))
        if service == "payment-gateway" and in_incident and level == "ERROR" and random.random() < 0.4:
            message = f"timeout after {random.randint(5000, 30000)}ms calling stripe"
        return {
            "level": level,
            "service": service,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "host": f"{service}-{random.randint(1, 3)}",
            "environment": "demo",
            "trace_id": uuid.uuid4().hex,
            "attributes": {"region": random.choice(["eu-west-1", "us-east-1"]), "version": "1.4.2"},
        }


async def run(url: str, api_key: str, rate: float, incident_chance: float, batch_interval: float) -> None:
    sim = Simulator()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    endpoint = f"{url.rstrip('/')}/api/v1/logs/bulk"
    sent = 0
    async with httpx.AsyncClient(timeout=10, headers={"X-API-Key": api_key}) as client:
        print(f"[loadgen] sending ~{rate:.0f} logs/s to {endpoint}")
        while not stop.is_set():
            sim.maybe_start_incident(incident_chance)
            n = max(1, int(random.gauss(rate * batch_interval, rate * batch_interval * 0.2)))
            batch = [sim.make_log() for _ in range(min(n, 1000))]
            try:
                resp = await client.post(endpoint, json=batch)
                if resp.status_code == 202:
                    sent += len(batch)
                elif resp.status_code == 503:
                    await asyncio.sleep(float(resp.headers.get("Retry-After", "1")))
                else:
                    print(f"[loadgen] HTTP {resp.status_code}: {resp.text[:200]}")
            except httpx.HTTPError as exc:
                print(f"[loadgen] backend not reachable yet ({exc.__class__.__name__}); retrying")
                await asyncio.sleep(2)
            if sent and sent % 1000 < len(batch):
                print(f"[loadgen] {sent} logs sent")
            try:
                await asyncio.wait_for(stop.wait(), timeout=batch_interval)
            except TimeoutError:
                pass
    print(f"[loadgen] stopped after {sent} logs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.getenv("LOADGEN_TARGET_URL", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("LOADGEN_API_KEY", ""))
    parser.add_argument("--rate", type=float, default=float(os.getenv("LOADGEN_RATE", "20")), help="logs per second")
    parser.add_argument("--incident-chance", type=float, default=0.02, help="chance per batch of starting an incident")
    parser.add_argument("--batch-interval", type=float, default=1.0, help="seconds between batches")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.api_key, args.rate, args.incident_chance, args.batch_interval))


if __name__ == "__main__":
    main()
