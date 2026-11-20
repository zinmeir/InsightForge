"""Pydantic models shared by the API and the services layer.

This module intentionally depends on pydantic only, so it can be unit-tested in isolation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_MESSAGE_LENGTH = 32_768
MAX_ATTRIBUTES = 64

AttributeValue = str | int | float | bool | None


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


LEVEL_ALIASES = {
    "WARNING": "WARN",
    "ERR": "ERROR",
    "FATAL": "CRITICAL",
    "CRIT": "CRITICAL",
    "TRACE": "DEBUG",
}


def normalize_level(value: Any) -> Any:
    if isinstance(value, str):
        upper = value.strip().upper()
        return LEVEL_ALIASES.get(upper, upper)
    return value


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


class LogEntryIn(BaseModel):
    """A single log event as sent by a client."""

    model_config = ConfigDict(extra="forbid")

    level: LogLevel
    service: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._\-/:]+$")
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)
    timestamp: datetime | None = None
    host: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=64)
    trace_id: str | None = Field(default=None, max_length=128)
    span_id: str | None = Field(default=None, max_length=128)
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    @field_validator("level", mode="before")
    @classmethod
    def _normalize_level(cls, value: Any) -> Any:
        return normalize_level(value)

    @field_validator("timestamp")
    @classmethod
    def _ensure_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @field_validator("attributes")
    @classmethod
    def _limit_attributes(cls, value: dict[str, AttributeValue]) -> dict[str, AttributeValue]:
        if len(value) > MAX_ATTRIBUTES:
            raise ValueError(f"at most {MAX_ATTRIBUTES} attributes are allowed")
        for key in value:
            if not key or len(key) > 128 or key.startswith("_"):
                raise ValueError(f"invalid attribute key: {key!r}")
        return value

    def to_document(self, received_at: datetime | None = None) -> dict[str, Any]:
        """Convert to the Elasticsearch document shape (ECS-ish, with @timestamp)."""
        received = received_at or utcnow()
        doc: dict[str, Any] = {
            "event_id": uuid.uuid4().hex,
            "@timestamp": (self.timestamp or received).isoformat(),
            "ingested_at": received.isoformat(),
            "level": self.level.value,
            "service": self.service,
            "message": self.message,
        }
        for optional in ("host", "environment", "trace_id", "span_id"):
            val = getattr(self, optional)
            if val:
                doc[optional] = val
        if self.attributes:
            # `flattened` fields index leaf values as keywords; stringify for consistency.
            doc["attributes"] = {k: ("" if v is None else str(v)) for k, v in self.attributes.items()}
        return doc


class LogRecord(BaseModel):
    """A log as returned by the API."""

    id: str
    timestamp: datetime
    level: LogLevel
    service: str
    message: str
    host: str | None = None
    environment: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> LogRecord:
        return cls(
            id=doc.get("event_id", ""),
            timestamp=doc["@timestamp"],
            level=normalize_level(doc.get("level", "INFO")),
            service=doc.get("service", "unknown"),
            message=doc.get("message", ""),
            host=doc.get("host"),
            environment=doc.get("environment"),
            trace_id=doc.get("trace_id"),
            span_id=doc.get("span_id"),
            attributes=doc.get("attributes") or {},
        )


class IngestResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    accepted: int


class LogPage(BaseModel):
    items: list[LogRecord]
    total: int
    total_is_lower_bound: bool = False
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class LevelCounts(BaseModel):
    DEBUG: int = 0
    INFO: int = 0
    WARN: int = 0
    ERROR: int = 0
    CRITICAL: int = 0


class OverviewStats(BaseModel):
    total: int
    by_level: LevelCounts
    error_rate: float = Field(description="Share of ERROR + CRITICAL logs, 0..1")
    services: int
    open_alerts: int


class HistogramBucket(LevelCounts):
    time: datetime


class Histogram(BaseModel):
    interval: str
    buckets: list[HistogramBucket]


class ServiceStat(BaseModel):
    service: str
    total: int
    by_level: LevelCounts
    error_rate: float


class LogPattern(BaseModel):
    pattern: str = Field(description="Message template with <num>, <hex>, <ip>, ... placeholders")
    count: int
    share: float = Field(description="Share of the analysed sample, 0..1")
    by_level: LevelCounts
    services: list[str] = Field(description="Up to three services emitting this pattern")
    service_count: int
    first_seen: datetime
    last_seen: datetime
    example: str
    query: str = Field(description="Full-text query that finds these logs in /api/v1/logs")
    trend: Literal["new", "rising", "steady", "falling"]


class PatternReport(BaseModel):
    patterns: list[LogPattern]
    sample_size: int
    total: int
    sampled: bool = Field(description="True when more logs matched than were analysed")


# ---------------------------------------------------------------------------
# Alert rules & alerts
# ---------------------------------------------------------------------------

Severity = Literal["info", "warning", "critical"]
NotifyChannel = Literal["slack", "pagerduty", "webhook"]


class RuleCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: list[LogLevel] = Field(default_factory=list, description="Empty = any level")
    services: list[str] = Field(default_factory=list, description="Empty = any service")
    message_contains: str | None = Field(default=None, max_length=256)
    threshold: int = Field(default=1, ge=1, le=1_000_000)
    window_seconds: int = Field(default=60, ge=1, le=86_400)

    @field_validator("levels", mode="before")
    @classmethod
    def _normalize_levels(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [normalize_level(v) for v in value]
        return value


class AlertRuleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    enabled: bool = True
    severity: Severity = "warning"
    condition: RuleCondition = Field(default_factory=RuleCondition)
    group_by_service: bool = Field(default=True, description="Track thresholds per service")
    cooldown_seconds: int = Field(default=300, ge=0, le=86_400)
    auto_resolve_seconds: int = Field(
        default=900, ge=0, le=7 * 86_400, description="Resolve after this long without matches; 0 = never"
    )
    notify: list[NotifyChannel] = Field(default_factory=list)


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1_000)
    enabled: bool | None = None
    severity: Severity | None = None
    condition: RuleCondition | None = None
    group_by_service: bool | None = None
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86_400)
    auto_resolve_seconds: int | None = Field(default=None, ge=0, le=7 * 86_400)
    notify: list[NotifyChannel] | None = None


class AlertRule(AlertRuleBase):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def apply_update(self, update: AlertRuleUpdate) -> AlertRule:
        data = self.model_dump()
        data.update(update.model_dump(exclude_unset=True))
        data["updated_at"] = utcnow()
        return AlertRule.model_validate(data)


AlertStatus = Literal["firing", "acknowledged", "resolved"]


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    fingerprint: str
    rule_id: str
    rule_name: str
    severity: Severity
    service: str | None = None
    status: AlertStatus = "firing"
    summary: str
    sample_message: str | None = None
    count: int = 1
    first_seen: datetime = Field(default_factory=utcnow)
    last_seen: datetime = Field(default_factory=utcnow)
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Alert:
        if self.last_seen < self.first_seen:
            self.last_seen = self.first_seen
        return self


class AlertPage(BaseModel):
    items: list[Alert]
    total: int


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

Role = Literal["admin", "viewer"]


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    role: Role
    username: str


class Principal(BaseModel):
    subject: str
    role: Role | Literal["ingest"]
    auth_method: Literal["jwt", "api_key", "disabled"]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
