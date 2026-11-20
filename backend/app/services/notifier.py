"""Delivers alert notifications to Slack, PagerDuty and generic webhooks."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core import metrics
from app.core.config import Settings
from app.schemas import Alert, NotifyChannel
from app.services import notify_payloads as payloads

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, max_attempts: int = 3):
        self._settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.notification_timeout_seconds)
        self._max_attempts = max_attempts
        self._inflight: set[asyncio.Task[bool]] = set()

    @property
    def configured_channels(self) -> list[NotifyChannel]:
        s = self._settings
        channels: list[NotifyChannel] = []
        if s.slack_webhook_url:
            channels.append("slack")
        if s.pagerduty_routing_key:
            channels.append("pagerduty")
        if s.alert_webhook_url:
            channels.append("webhook")
        return channels

    def dispatch(self, alert: Alert, event: payloads.Event, channels: list[NotifyChannel]) -> None:
        """Fire-and-forget delivery; never blocks the caller."""
        for channel in set(channels) & set(self.configured_channels):
            task = asyncio.create_task(self.send(channel, alert, event), name=f"notify-{channel}")
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def send(self, channel: NotifyChannel, alert: Alert, event: payloads.Event) -> bool:
        url, body, headers = self._build(channel, alert, event)
        for attempt in range(1, self._max_attempts + 1):
            try:
                resp = await self._client.post(url, content=body, headers=headers)
                if resp.status_code < 300:
                    metrics.NOTIFICATIONS.labels(channel=channel, outcome="success").inc()
                    return True
                retryable = resp.status_code == 429 or resp.status_code >= 500
                logger.warning(
                    "notification rejected",
                    extra={"channel": channel, "status": resp.status_code, "attempt": attempt},
                )
                if not retryable:
                    break
            except httpx.HTTPError as exc:
                logger.warning("notification failed", extra={"channel": channel, "error": str(exc)})
            if attempt < self._max_attempts:
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
        metrics.NOTIFICATIONS.labels(channel=channel, outcome="failure").inc()
        return False

    def _build(self, channel: NotifyChannel, alert: Alert, event: payloads.Event) -> tuple[str, bytes, dict[str, str]]:
        s = self._settings
        headers = {"Content-Type": "application/json", "User-Agent": "InsightForge-Alerting/2.0"}
        payload: dict[str, Any]
        if channel == "slack":
            assert s.slack_webhook_url
            url = s.slack_webhook_url.get_secret_value()
            payload = payloads.slack_payload(alert, event, s.public_dashboard_url)
        elif channel == "pagerduty":
            assert s.pagerduty_routing_key
            url = s.pagerduty_events_url
            payload = payloads.pagerduty_payload(
                alert, event, s.pagerduty_routing_key.get_secret_value(), s.public_dashboard_url
            )
        else:
            assert s.alert_webhook_url
            url = s.alert_webhook_url
            payload = payloads.webhook_payload(alert, event)
        body = payloads.encode_json(payload)
        if channel == "webhook" and s.alert_webhook_secret:
            headers["X-InsightForge-Signature"] = payloads.sign_body(body, s.alert_webhook_secret.get_secret_value())
        return url, body, headers

    async def aclose(self, timeout: float = 5.0) -> None:
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=timeout)
        await self._client.aclose()
