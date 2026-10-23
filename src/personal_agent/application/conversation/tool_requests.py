"""Exact typed requests accepted before this conversation's durable tools run."""

from pydantic import BaseModel, ConfigDict
from personal_agent.application.artifacts.models import ArtifactWriteRequest


class WriteArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ArtifactWriteRequest
