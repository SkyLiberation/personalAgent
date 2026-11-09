"""CLI 导出；独立工程子命令不提前加载产品主程序。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from personal_agent.adapters.cli.main import app as app

__all__ = ["app"]


def __getattr__(name: str) -> object:
    if name == "app":
        from personal_agent.adapters.cli.main import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
