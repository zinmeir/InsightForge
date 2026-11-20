from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import AdminUser, ContainerDep, CurrentUser
from app.schemas import Alert, AlertPage, AlertRule, AlertRuleCreate, AlertRuleUpdate, NotifyChannel
from app.services.alert_manager import AlertConflictError

alerts_router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
rules_router = APIRouter(prefix="/api/v1/rules", tags=["alert rules"])
notifications_router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

StatusFilter = Literal["open", "firing", "acknowledged", "resolved", "all"]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@alerts_router.get("", response_model=AlertPage)
async def list_alerts(
    container: ContainerDep,
    _user: CurrentUser,
    status_: Annotated[StatusFilter, Query(alias="status")] = "open",
    severity: Annotated[Literal["info", "warning", "critical"] | None, Query()] = None,
    service: str | None = None,
    size: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> AlertPage:
    if status_ == "open":
        # Served from memory: always up to date, including not-yet-persisted counters.
        items = [
            a
            for a in container.alert_manager.open_alerts
            if (severity is None or a.severity == severity) and (service is None or a.service == service)
        ]
        return AlertPage(items=items[offset : offset + size], total=len(items))
    statuses: list[str] | None = None if status_ == "all" else [status_]
    items, total = await container.alerts.search(
        statuses=statuses, severity=severity, service=service, size=size, offset=offset
    )
    return AlertPage(items=items, total=total)


@alerts_router.get("/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str, container: ContainerDep, _user: CurrentUser) -> Alert:
    alert = await container.alert_manager.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    return alert


@alerts_router.post("/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge_alert(alert_id: str, container: ContainerDep, user: CurrentUser) -> Alert:
    try:
        return await container.alert_manager.acknowledge(alert_id, user.subject)
    except AlertConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@alerts_router.post("/{alert_id}/resolve", response_model=Alert)
async def resolve_alert(alert_id: str, container: ContainerDep, user: CurrentUser) -> Alert:
    try:
        return await container.alert_manager.resolve(alert_id, user.subject)
    except AlertConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


async def _get_rule_or_404(container: ContainerDep, rule_id: str) -> AlertRule:
    rule = await container.rules.get(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule


@rules_router.get("", response_model=list[AlertRule])
async def list_rules(container: ContainerDep, _user: CurrentUser) -> list[AlertRule]:
    return await container.rules.list()


@rules_router.post("", response_model=AlertRule, status_code=status.HTTP_201_CREATED)
async def create_rule(body: AlertRuleCreate, container: ContainerDep, _admin: AdminUser) -> AlertRule:
    rule = AlertRule(**body.model_dump())
    await container.rules.save(rule)
    container.alert_manager.engine.upsert_rule(rule)
    return rule


@rules_router.get("/{rule_id}", response_model=AlertRule)
async def get_rule(rule_id: str, container: ContainerDep, _user: CurrentUser) -> AlertRule:
    return await _get_rule_or_404(container, rule_id)


@rules_router.patch("/{rule_id}", response_model=AlertRule)
async def update_rule(
    rule_id: str, body: AlertRuleUpdate, container: ContainerDep, _admin: AdminUser
) -> AlertRule:
    rule = (await _get_rule_or_404(container, rule_id)).apply_update(body)
    await container.rules.save(rule)
    container.alert_manager.engine.upsert_rule(rule)
    if not rule.enabled:
        await container.alert_manager.resolve_for_rule(rule.id, "rule_disabled")
    return rule


@rules_router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(rule_id: str, container: ContainerDep, _admin: AdminUser) -> None:
    if not await container.rules.delete(rule_id):
        raise HTTPException(status_code=404, detail="rule not found")
    await container.alert_manager.resolve_for_rule(rule_id, "rule_deleted")
    container.alert_manager.engine.remove_rule(rule_id)


# ---------------------------------------------------------------------------
# Notification channels
# ---------------------------------------------------------------------------


class ChannelsResponse(BaseModel):
    available: list[NotifyChannel]
    configured: list[NotifyChannel]


class TestNotificationRequest(BaseModel):
    channel: NotifyChannel


class TestNotificationResponse(BaseModel):
    channel: NotifyChannel
    delivered: bool


@notifications_router.get("/channels", response_model=ChannelsResponse)
async def channels(container: ContainerDep, _user: CurrentUser) -> ChannelsResponse:
    return ChannelsResponse(
        available=["slack", "pagerduty", "webhook"], configured=container.notifier.configured_channels
    )


@notifications_router.post("/test", response_model=TestNotificationResponse)
async def test_notification(
    body: TestNotificationRequest, container: ContainerDep, admin: AdminUser
) -> TestNotificationResponse:
    if body.channel not in container.notifier.configured_channels:
        raise HTTPException(status_code=400, detail=f"channel '{body.channel}' is not configured")
    alert = Alert(
        fingerprint="test:insightforge",
        rule_id="test",
        rule_name="Test notification",
        severity="info",
        service="insightforge",
        summary=f"Test notification sent by {admin.subject}",
        sample_message="If you can read this, InsightForge alert delivery works.",
    )
    delivered = await container.notifier.send(body.channel, alert, "opened")
    if delivered and body.channel == "pagerduty":
        await container.notifier.send(body.channel, alert, "resolved")  # don't leave a test incident open
    return TestNotificationResponse(channel=body.channel, delivered=delivered)
