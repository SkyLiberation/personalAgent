"""Typed human-interaction contracts used by checkpoint and approval control."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InteractionOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1)
    label: str
    description: str = ""


class InteractionRequest(BaseModel):
    """A checkpointed request for clarification or explicit approval."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["clarification_required", "confirmation_required"]
    action_type: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    title: str = ""
    message: str = ""
    summary: str = ""
    description: str = ""
    resource_id: str | None = None
    original_text: str | None = None
    missing_information: tuple[str, ...] = ()
    options: tuple[InteractionOption, ...] = ()


InteractionDecision = Literal["confirmed", "rejected"]


__all__ = ["InteractionDecision", "InteractionOption", "InteractionRequest"]
