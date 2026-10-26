"""Deployment-owned answer composition, shared by configuration and run binding."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AnswerResultConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    writer: Literal["direct", "claims"] = "claims"
    verification: Literal["required", "none"] = "required"
