from __future__ import annotations

from fastapi import Request

from personal_agent.kernel.config import Settings


def resolve_user_id(request: Request, settings: Settings) -> str:
    return getattr(request.state, "user_id", settings.default_user)


def is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))
