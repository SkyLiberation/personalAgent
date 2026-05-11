from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None


class BaseTool(ABC):
    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        ...
