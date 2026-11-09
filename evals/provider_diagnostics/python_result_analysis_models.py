"""局部 Python 分析回放的来源、费用与独立审读归档契约。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.application.conversation.models import (
    ResearchExperimentDeliveryBinding,
)
from personal_agent.kernel.contracts.resource import ResourceRef

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
SOURCE_ID = "af209a821ee94bc4939d77fae7da8109"
RUN_REF = "irun_retrieval_e1_20261020"
SOURCE_REQUEST_SHA256 = (
    "f369d6bd9db320f9461156abea0027f52ca6cf29110837f86fd76089c6b7849c"
)
SOURCE_TRACE_SHA256 = "203ce8c7e39c8994a8ab566433cc393f7e11bd3c68f60a59eac8fa53851f364a"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileStamp(Record):
    path: Path
    sha256: Digest


class SourceFile(Record):
    resource_ref: ResourceRef
    filename: str
    subdirectory: Literal["uploads", "generated_artifacts"]
    storage_name: str
    sha256: Digest
    bytes: Count


class SourceBudget(Record):
    model_turns: Count
    tool_calls: Count
    agent_calls: Count
    tokens: Count
    wall_seconds_at_input: float = Field(gt=0)


class SourceSelection(Record):
    request: FileStamp
    trace: FileStamp
    profile: FileStamp
    deployment: FileStamp
    artifact_root: Path
    journal_root: Path
    artifact_files: tuple[SourceFile, ...]
    remaining: SourceBudget
    original_deadline_at: datetime
    execution_remaining_seconds: float = Field(gt=0)


class GroupLimits(Record):
    repetitions_per_arm: Literal[10] = 10
    physical_calls_per_sample: Literal[4] = 4
    physical_calls: Literal[80] = 80
    tokens: Literal[20000000] = 20_000_000
    wall_seconds: Literal[7200] = 7200
    max_output_tokens: Literal[32768] = 32768
    protocol_reserve_tokens: Literal[8192] = 8192


class CostEstimate(Record):
    source_measured_input_tokens: Count
    source_body_ascii_bytes: Count
    source_sized_80_call_tokens: Count
    first_call_reservation_tokens: Count
    note: str


class GroupPlan(Record):
    schema_version: Literal[1] = 1
    group_id: str
    evidence_class: Literal["Offline Eval"] = "Offline Eval"
    created_at: datetime
    source: SourceSelection
    limits: GroupLimits = GroupLimits()
    order: tuple[str, ...]
    cost_estimate: CostEstimate
    code_files: dict[str, Digest]
    authority: FileStamp
    first_sdk_required: bool = True
    upstream_plan_repair_claimed: Literal[False] = False


class Usage(Record):
    input_tokens: Count
    output_tokens: Count
    total_tokens: Count

    @model_validator(mode="after")
    def consistent(self) -> Usage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("Provider usage总量与输入／输出不一致，不能按已知费用继续")
        return self


class PhysicalCall(Record):
    send_id: str
    candidate_id: str
    sample_id: str
    at: datetime
    request_sha256: Digest
    reservation_tokens: Count
    request_input_bound: Count
    requested_output_tokens: Count
    http_status: int | None = None
    response_received: bool = False
    usage: Usage | None = None
    error_type: str | None = None


class RelationReview(Record):
    relation: Literal[
        "count_attribution",
        "set_relations",
        "example_ranking",
        "analysis_consistency",
        "tool_contribution",
    ]
    verdict: Literal["passed", "failed", "uncovered"]
    explanation: str = Field(min_length=1)
    evidence_locations: tuple[str, ...] = Field(min_length=1)


class IndependentReview(Record):
    sample_id: str
    result_sha256: Digest
    reviewer: str = Field(min_length=1)
    independent_reading_confirmed: Literal[True]
    user_report: Literal["passed", "failed", "uncovered"]
    relations: tuple[RelationReview, ...]
    notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def all_relations(self) -> IndependentReview:
        names = [item.relation for item in self.relations]
        if len(names) != 5 or len(set(names)) != 5:
            raise ValueError("独立审读必须分别记录全部五项关系，未覆盖不能省略")
        if self.user_report == "passed" and any(
            item.verdict == "failed"
            for item in self.relations
            if item.relation != "tool_contribution"
        ):
            raise ValueError("存在成稿关系失败时不能登记用户报告通过")
        return self


class SampleState(Record):
    sample_id: str
    status: Literal["pending", "running", "awaiting_review", "reviewed"] = "pending"
    started_at: datetime | None = None
    result: FileStamp | None = None
    review: FileStamp | None = None


class GroupState(Record):
    group_id: str
    started_at: datetime | None = None
    stopped_reason: str | None = None
    samples: tuple[SampleState, ...]
    physical_calls: tuple[PhysicalCall, ...] = ()

    @property
    def known_tokens(self) -> int:
        return sum(
            item.usage.total_tokens for item in self.physical_calls if item.usage
        )


class ClockMapping(Record):
    evidence_class: Literal["Offline Eval"] = "Offline Eval"
    source_deadline_at: datetime
    mapped_at: datetime
    source_remaining_seconds: float
    mapped_deadline_at: datetime
    source_trace_sha256: Digest


class ExportedArtifact(Record):
    resource_ref: ResourceRef
    filename: str
    content_type: str | None
    content_path: Path
    sha256: Digest
    role: Literal["draft_candidate", "python_original", "report"]
    report_binding: ResearchExperimentDeliveryBinding | None = None


class SampleResult(Record):
    sample_id: str
    reason: str
    started_at: datetime
    finished_at: datetime
    source_trace_sha256: Digest
    clock_mapping: FileStamp
    final_trace: FileStamp
    new_artifacts: tuple[ExportedArtifact, ...]
    accepted_request_files: tuple[Path, ...]
    first_sdk_audit: FileStamp | None
    physical_send_ids: tuple[str, ...]
    sdk_directory: Path
    semantic_verdict: Literal["awaiting_independent_review"] = (
        "awaiting_independent_review"
    )


class FirstSdkAudit(Record):
    sample_id: str
    source_request_sha256: Digest
    actual_request_sha256: Digest
    matching_user_and_typed_inputs: bool
    matching_model_configuration: bool
    matching_original_tools: bool
    matching_system_after_declared_projection: bool
    python_tool_count: Count
    wall_seconds: float | None
    allowed_wall_upper: float
    differences: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.differences
