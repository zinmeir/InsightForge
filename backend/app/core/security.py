"""Token and credential primitives (framework-agnostic)."""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

TOKEN_ISSUER = "insightforge"


class InvalidTokenError(Exception):
    pass


def create_access_token(
    subject: str, role: str, *, secret: str, algorithm: str = "HS256", expires_minutes: int = 60
) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expires_in = expires_minutes * 60
    payload = {
        "sub": subject,
        "role": role,
        "iss": TOKEN_ISSUER,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    return jwt.encode(payload, secret, algorithm=algorithm), expires_in


def decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            issuer=TOKEN_ISSUER,
            options={"require": ["exp", "iat", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if claims.get("role") not in {"admin", "viewer"}:
        raise InvalidTokenError("unknown role")
    return claims


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_api_key(candidate: str | None, valid_keys: Iterable[str]) -> bool:
    if not candidate:
        return False
    # Compare against every key so timing doesn't reveal which (if any) matched.
    matched = False
    for key in valid_keys:
        matched |= constant_time_equals(candidate, key)
    return matched
