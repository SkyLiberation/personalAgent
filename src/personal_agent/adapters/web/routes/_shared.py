from __future__ import annotations

from fastapi import Request

from personal_agent.kernel.config import Settings


def resolve_user_id(request: Request, settings: Settings) -> str:
    return getattr(request.state, "user_id", settings.default_user)


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
