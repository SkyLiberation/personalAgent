"""Non-authoritative history view, bound to immutable journal and Artifact facts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.artifacts.models import ContentDigest
from personal_agent.kernel.contracts.resource import ResourceRef


class HistoryItemKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    action_id: str
    decision_turn: int | None = None


class HistorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    working_summary: str = Field(min_length=1, max_length=20_000)


class HistoryCompactionCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["history_compaction"] = "history_compaction"
    run_ref: str
    source_revision: int = Field(ge=1)
    source_end: int = Field(ge=1)
    source_digest: ContentDigest
    covered_items: tuple[HistoryItemKey, ...] = Field(min_length=1)
    snapshot_ref: ResourceRef
    snapshot_digest: ContentDigest
    working_summary: str = Field(min_length=1, max_length=20_000)
    prompt_version: str
    model: str
    response_id: str | None
    response_digest: ContentDigest
    previous_checkpoint_digest: ContentDigest | None = None
