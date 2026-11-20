from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ContainerDep, CurrentUser
from app.core.security import constant_time_equals, create_access_token
from app.schemas import LoginRequest, Principal, Role, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, container: ContainerDep) -> TokenResponse:
    s = container.settings
    accounts: list[tuple[str, str, Role]] = [
        (s.admin_username, s.admin_password.get_secret_value(), "admin")
    ]
    if s.viewer_username and s.viewer_password:
        accounts.append((s.viewer_username, s.viewer_password.get_secret_value(), "viewer"))

    role: Role | None = None
    for username, password, account_role in accounts:
        # Evaluate both comparisons for every account to keep timing uniform.
        user_ok = constant_time_equals(body.username, username)
        pass_ok = constant_time_equals(body.password, password)
        if user_ok and pass_ok and role is None:
            role = account_role

    if role is None:
        await asyncio.sleep(0.5)  # slow down online guessing (nginx also rate-limits this route)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token, expires_in = create_access_token(
        body.username,
        role,
        secret=s.jwt_secret.get_secret_value(),
        algorithm=s.jwt_algorithm,
        expires_minutes=s.jwt_expire_minutes,
    )
    return TokenResponse(access_token=token, expires_in=expires_in, role=role, username=body.username)


@router.get("/me", response_model=Principal)
async def me(principal: CurrentUser) -> Principal:
    return principal
