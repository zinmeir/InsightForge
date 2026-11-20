"""Log pattern mining: collapse similar messages into templates.

``"timeout after 12043ms calling stripe"`` and ``"timeout after 98ms calling stripe"`` both become
``"timeout after <num>ms calling stripe"``. Variable parts (numbers, ids, IPs, URLs, quoted
strings, ...) are masked with typed placeholders, then messages are grouped by template.

This runs over a bounded sample of the newest matching logs, so it stays fast and predictable;
results are flagged as sampled when the full match set is larger than the sample.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.schemas import LevelCounts, LogPattern

Trend = Literal["new", "rising", "steady", "falling"]

MAX_TEMPLATE_LENGTH = 300
PLACEHOLDER = re.compile(r"<(?:url|email|uuid|ip|hex|str|num)>")

# Order matters: specific shapes first, generic numbers last.
_MASKS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bhttps?://\S+"), "<url>"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    # hex ids / hashes: 8+ hex chars containing at least one digit and one letter
    (re.compile(r"\b(?=[0-9a-fA-F]*\d)(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{8,}\b"), "<hex>"),
    # quoted values; the word-boundary guards keep apostrophes in "can't ... don't" intact
    (re.compile(r"(?<!\w)'[^']{0,200}'(?!\w)"), "'<str>'"),
    (re.compile(r'(?<!\w)"[^"]{0,200}"(?!\w)'), '"<str>"'),
    # numbers not glued to a preceding letter: keeps "v1"/"s3" but masks "user_4821", "42ms", "98%"
    (re.compile(r"(?<![A-Za-z<])-?\d+(?:\.\d+)?"), "<num>"),
]
_WHITESPACE = re.compile(r"\s+")


def to_template(message: str) -> str:
    template = message.strip()
    for regex, replacement in _MASKS:
        template = regex.sub(replacement, template)
    template = _WHITESPACE.sub(" ", template)
    return template[:MAX_TEMPLATE_LENGTH]


def search_query_for(template: str) -> str:
    """Build a full-text query that finds the logs behind a template.

    Static fragments between placeholders become quoted phrases. Words glued to a placeholder
    (``ms`` in ``<num>ms``) are dropped because the analyzer indexes ``12043ms`` as one token.
    """
    phrases: list[str] = []
    pieces = PLACEHOLDER.split(template)
    for i, piece in enumerate(pieces):
        words = piece.split(" ")
        if i > 0 and piece and not piece[0].isspace():
            words = words[1:]  # glued to the placeholder before it
        if i < len(pieces) - 1 and piece and not piece[-1].isspace():
            words = words[:-1]  # glued to the placeholder after it
        cleaned = " ".join(w for w in words if w).strip(" '\"")
        cleaned = cleaned.replace('"', "")
        if sum(ch.isalnum() for ch in cleaned) >= 3:
            phrases.append(f'"{cleaned}"')
    return " ".join(phrases[:6]) or template.replace('"', "")[:100]


@dataclass
class _Group:
    template: str
    count: int = 0
    early: int = 0
    late: int = 0
    levels: Counter[str] = field(default_factory=Counter)
    services: Counter[str] = field(default_factory=Counter)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    example: str = ""


def _trend(group: _Group, span_seconds: float) -> Trend:
    if span_seconds < 1 or group.count < 2:
        return "steady"
    if group.early == 0:
        return "new"
    ratio = group.late / group.early
    if ratio >= 2:
        return "rising"
    if ratio <= 0.5:
        return "falling"
    return "steady"


def extract_patterns(docs: list[dict[str, Any]], *, limit: int = 20) -> list[LogPattern]:
    """Group documents (ES ``_source`` dicts) by message template, most frequent first."""
    if not docs:
        return []
    stamps = [datetime.fromisoformat(d["@timestamp"]) for d in docs]
    oldest, newest = min(stamps), max(stamps)
    span = (newest - oldest).total_seconds()
    midpoint = oldest + (newest - oldest) / 2

    groups: dict[str, _Group] = {}
    for doc, ts in zip(docs, stamps, strict=True):
        message = doc.get("message", "")
        template = to_template(message)
        group = groups.get(template)
        if group is None:
            group = groups[template] = _Group(template=template, example=message[:1_000])
        group.count += 1
        if ts > midpoint:
            group.late += 1
        else:
            group.early += 1
        group.levels[doc.get("level", "INFO")] += 1
        group.services[doc.get("service", "unknown")] += 1
        if group.first_seen is None or ts < group.first_seen:
            group.first_seen = ts
        if group.last_seen is None or ts > group.last_seen:
            group.last_seen = ts
            group.example = message[:1_000]  # newest occurrence is the most useful example

    total = len(docs)
    ranked = sorted(groups.values(), key=lambda g: (-g.count, g.template))[:limit]
    return [
        LogPattern(
            pattern=g.template,
            count=g.count,
            share=round(g.count / total, 4),
            by_level=LevelCounts(**{k: v for k, v in g.levels.items() if k in LevelCounts.model_fields}),
            services=[name for name, _ in g.services.most_common(3)],
            service_count=len(g.services),
            first_seen=g.first_seen or oldest,
            last_seen=g.last_seen or newest,
            example=g.example,
            query=search_query_for(g.template),
            trend=_trend(g, span),
        )
        for g in ranked
    ]
