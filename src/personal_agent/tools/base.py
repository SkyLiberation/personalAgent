from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Known JSON Schema type keywords for simple validation
_SCHEMA_TYPE_MAP: dict[str, type | tuple] = {
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "array": list,
    "object": dict,
}


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"  # low / medium / high
    requires_confirmation: bool = False
    writes_longterm: bool = False
    accesses_external: bool = False


@dataclass(slots=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    evidence: list | None = None


class BaseTool(ABC):
    @property
    @abstractmethod
    def spec(self) -> ToolSpec:
        ...

    @abstractmethod
    def execute(self, **kwargs: Any) -> ToolResult:
        ...


def validate_tool_input(schema: dict[str, Any], kwargs: dict[str, Any]) -> list[str]:
    """Validate kwargs against a JSON Schema style input_schema.

    Returns a list of error message strings (empty = valid).
    Supports a pragmatic subset: type, required, properties.
    """
    errors: list[str] = []

    if not schema or schema.get("type") != "object":
        return errors

    required: list[str] = schema.get("required", [])
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})

    for key in required:
        if key not in kwargs or kwargs[key] is None:
            errors.append(f"缺少必需参数: {key}")

    for key, value in kwargs.items():
        prop_schema = properties.get(key)
        if prop_schema is None:
            continue
        expected_type = prop_schema.get("type")
        if expected_type is None:
            continue
        python_type = _SCHEMA_TYPE_MAP.get(expected_type)
        if python_type is None:
            continue
        if value is not None and not isinstance(value, python_type):
            errors.append(
                f"参数 {key!r} 类型错误: 期望 {expected_type}，实际 {type(value).__name__}"
            )

    return errors
