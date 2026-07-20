"""Typed human-interaction contracts used by checkpoint and approval control."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    authorization_digest: str | None = None

    @model_validator(mode="after")
    def _confirmation_binds_authorization(self) -> "InteractionRequest":
        if self.kind == "confirmation_required" and not self.authorization_digest:
            raise ValueError("confirmation request requires AuthorizationDigest")
        if self.kind == "clarification_required" and self.authorization_digest is not None:
            raise ValueError("clarification request cannot carry AuthorizationDigest")
        return self


InteractionDecision = Literal["confirmed", "rejected"]


__all__ = ["InteractionDecision", "InteractionOption", "InteractionRequest"]
