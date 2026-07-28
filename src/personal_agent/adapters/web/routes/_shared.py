from __future__ import annotations

from fastapi import Request

from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


def resolve_principal(
    request: Request,
    settings: Settings,
) -> AuthenticatedPrincipal:
    raw = getattr(request.state, "principal", None)
    if raw is not None:
        return AuthenticatedPrincipal.model_validate(raw)
    return AuthenticatedPrincipal(
        tenant_id="personal-agent",
        user_id=settings.default_user,
    )


def resolve_requested_principal(
    request: Request,
    settings: Settings,
    requested_user_id: str | None,
) -> AuthenticatedPrincipal:
    principal = resolve_principal(request, settings)
    if not requested_user_id or requested_user_id == principal.user_id:
        return principal
    if auth_is_disabled(settings):
        return principal.model_copy(update={"user_id": requested_user_id})
    raise PermissionError("requested user does not match authenticated principal")


def resolve_user_id(request: Request, settings: Settings) -> str:
    return resolve_principal(request, settings).user_id


def is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


def auth_is_disabled(settings: Settings) -> bool:
    return not settings.web.api_keys and not settings.web.admin_api_keys


def resolve_query_user_id(
    request: Request,
    settings: Settings,
    requested_user_id: str | None = None,
) -> str:
    if requested_user_id and (is_admin(request) or auth_is_disabled(settings)):
        return requested_user_id
    return resolve_user_id(request, settings)
