from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class InteractionToolDefinition(BaseModel):
    """Read-only capability facts exposed by a governed tool registry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    input_schema: dict[str, object]
    read_only: bool
    planning_safe: bool
    safely_retryable: bool
    emits_verified_artifact: bool = False


class InteractionToolCallValidation(BaseModel):
    """Deterministic registry/schema validation; never repairs semantic payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted", "capability_missing", "invalid_arguments"]
    message: str = ""


__all__ = ["InteractionToolCallValidation", "InteractionToolDefinition"]
