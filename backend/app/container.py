from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.services.alert_manager import AlertManager
from app.services.broker import LogBroker
from app.services.ingest_buffer import IngestBuffer
from app.services.notifier import Notifier
from app.services.stores import AlertStore, RuleStore


@dataclass
class Container:
    """Long-lived services shared by all requests (stored on ``app.state.container``)."""

    settings: Settings
    es: Any  # AsyncElasticsearch (Any so tests can inject a fake)
    buffer: IngestBuffer
    broker: LogBroker
    alert_manager: AlertManager
    rules: RuleStore
    alerts: AlertStore
    notifier: Notifier
