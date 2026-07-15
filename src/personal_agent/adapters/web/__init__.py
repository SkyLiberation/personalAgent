"""Web adapter exports without application-construction import side effects."""

from __future__ import annotations


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from personal_agent.adapters.web import api

        return getattr(api, name)
    raise AttributeError(name)

__all__ = ["app", "create_app"]
