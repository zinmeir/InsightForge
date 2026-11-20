from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.container import Container
from app.core.security import InvalidTokenError, decode_access_token, verify_api_key
from app.schemas import Principal

bearer_scheme = HTTPBearer(auto_error=False, description="JWT from POST /api/v1/auth/login")
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, description="Ingestion API key")

_ANONYMOUS_ADMIN = Principal(subject="anonymous", role="admin", auth_method="disabled")


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def _principal_from_jwt(token: str, container: Container) -> Principal:
    s = container.settings
    try:
        claims = decode_access_token(token, secret=s.jwt_secret.get_secret_value(), algorithm=s.jwt_algorithm)
    except InvalidTokenError as exc:
        raise _unauthorized("Invalid or expired token") from exc
    return Principal(subject=claims["sub"], role=claims["role"], auth_method="jwt")


async def current_user(
    container: ContainerDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> Principal:
    if not container.settings.auth_enabled:
        return _ANONYMOUS_ADMIN
    if creds is None:
        raise _unauthorized()
    return _principal_from_jwt(creds.credentials, container)


async def require_admin(principal: Annotated[Principal, Depends(current_user)]) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return principal


async def ingest_client(
    container: ContainerDep,
    api_key: Annotated[str | None, Security(api_key_scheme)],
    creds: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> Principal:
    """Ingestion accepts an API key (for services) or an admin JWT (for the dashboard's test buttons)."""
    if not container.settings.auth_enabled:
        return _ANONYMOUS_ADMIN
    if api_key:
        if verify_api_key(api_key, container.settings.ingest_api_key_list):
            return Principal(subject="api-key", role="ingest", auth_method="api_key")
        raise _unauthorized("Invalid API key")
    if creds:
        principal = _principal_from_jwt(creds.credentials, container)
        if principal.is_admin:
            return principal
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required to ingest")
    raise _unauthorized("Provide an X-API-Key header or a bearer token")


CurrentUser = Annotated[Principal, Depends(current_user)]
AdminUser = Annotated[Principal, Depends(require_admin)]
IngestClient = Annotated[Principal, Depends(ingest_client)]
