"""Non-authoritative history view, bound to immutable journal and Artifact facts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.artifacts.models import ContentDigest
from personal_agent.capabilities.contracts.verification import VerificationKind
from personal_agent.kernel.contracts.resource import ResourceRef


class HistoryItemKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: str
    action_id: str
    decision_turn: int | None = None


class HistorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    working_summary: str = Field(min_length=1, max_length=20_000)


class HistoryRunCoverage(BaseModel):
    """One exact, complete decision prefix on the visible conversation branch."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_ref: str = Field(min_length=1)
    through_turn: int = Field(ge=1)
    includes_final: bool
    source_digest: ContentDigest


class HistoryCompactionCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["history_compaction"] = "history_compaction"
    run_ref: str
    source_revision: int = Field(ge=1)
    source_digest: ContentDigest
    sources: tuple[HistoryRunCoverage, ...] = Field(min_length=1)
    snapshot_ref: ResourceRef
    snapshot_digest: ContentDigest
    prior_snapshot_refs: tuple[ResourceRef, ...] = ()
    working_summary: str = Field(min_length=1, max_length=20_000)
    prompt_version: str
    model: str
    response_id: str | None
    response_digest: ContentDigest
    previous_checkpoint_digest: ContentDigest | None = None


class VerificationTurnCompaction(BaseModel):
    """A checked summary of one exact event prefix, never a second task history."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_turn: int = Field(ge=1)
    covered_events: int = Field(ge=1)
    source_digest: ContentDigest
    snapshot_ref: ResourceRef
    working_summary: str = Field(min_length=1, max_length=20_000)
    model_invocation_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    summary_run_ref: str = Field(min_length=1)


class VerificationHistoryCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: VerificationKind
    turns: tuple[VerificationTurnCompaction, ...] = Field(min_length=1)
