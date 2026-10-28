"""检索实验业务请求、许可、冻结执行与正式产物引用。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

import hashlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, ValidationInfo, model_validator

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from .contracts import (
    DatasetManifest,
    Depth,
    Digest,
    ExperimentConfig,
    ExperimentResult,
    FrozenExperiment,
    Identifier,
    Metrics,
    ModelIdentity,
    StrictModel,
    canonical_digest,
)

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
PositiveSeconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
Status = Literal["succeeded", "failed", "timed_out", "output_limit", "unknown"]
ErrorCode = Literal[
    "execution_failed", "deadline", "output_limit", "backend_unknown", "invalid_output"
]


class BaselineDevelopment(StrictModel):
    method: Literal["bm25", "dense"]
    retrieve_k: Depth


class RRFDevelopment(StrictModel):
    method: Literal["rrf"]
    retrieve_k: Depth
    input_result_refs: tuple[ResourceRef, ...] = Field(min_length=2)


class CandidateDevelopment(StrictModel):
    method: Literal["candidate"]
    retrieve_k: Depth
    input_result_refs: tuple[ResourceRef, ...] = Field(min_length=2)
    program_ref: ResourceRef
    config_ref: ResourceRef | None = None


DevelopmentRequest = Annotated[
    BaselineDevelopment | RRFDevelopment | CandidateDevelopment,
    Field(discriminator="method"),
]


class RunDevelopment(StrictModel):
    operation: Literal["run_development"]
    request: DevelopmentRequest


class FreezeExperiment(StrictModel):
    operation: Literal["freeze"]
    selected_result_ref: ResourceRef


class EvaluateFinal(StrictModel):
    operation: Literal["evaluate_final"]
    frozen_ref: ResourceRef


ExperimentAction = Annotated[
    RunDevelopment | FreezeExperiment | EvaluateFinal, Field(discriminator="operation")
]


class ExperimentToolArgs(StrictModel):
    action: ExperimentAction


class MaterialBinding(StrictModel):
    role: Literal["corpus", "queries", "development_qrels", "test_qrels"]
    resource_ref: ResourceRef
    content_digest: Digest


class ExperimentLimits(StrictModel):
    run_timeout_seconds: PositiveSeconds
    max_execution_seconds: PositiveSeconds
    worker_timeout_seconds: Annotated[
        float, Field(gt=0, le=1200, allow_inf_nan=False)
    ] = 1200
    candidate_timeout_seconds: Annotated[
        float, Field(gt=0, le=1200, allow_inf_nan=False)
    ] = 60
    worker_memory_mb: PositiveInteger = 4096
    worker_cpus: PositiveSeconds = 4
    worker_pids: PositiveInteger = 128
    candidate_memory_mb: PositiveInteger = 512
    candidate_cpus: PositiveSeconds = 1
    candidate_pids: PositiveInteger = 64
    candidate_scratch_mb: PositiveInteger = 32
    stdout_bytes: PositiveInteger = 16 * 1024 * 1024
    stderr_bytes: PositiveInteger = 64 * 1024


class RetrievalDeployment(StrictModel):
    authorized_principal: AuthenticatedPrincipal
    scorer_principal: AuthenticatedPrincipal
    materials: tuple[MaterialBinding, ...]
    development: DatasetManifest
    final: DatasetManifest
    worker_image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    candidate_image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    model: ModelIdentity
    limits: ExperimentLimits

    @property
    def deployment_digest(self) -> str:
        return canonical_digest(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def validate_binding(self) -> RetrievalDeployment:
        roles = [item.role for item in self.materials]
        if sorted(roles) != ["corpus", "development_qrels", "queries", "test_qrels"]:
            raise ValueError("部署必须恰好绑定四种原件角色")
        if self.scorer_principal == self.authorized_principal:
            raise ValueError("scorer 与研究主体必须隔离")
        for item in self.materials:
            owner = (
                self.scorer_principal
                if item.role == "test_qrels"
                else self.authorized_principal
            )
            if (
                item.resource_ref.owner != owner
                or item.resource_ref.resource_type != "artifact"
            ):
                raise ValueError("部署原件身份与固定用途主体不一致")
        if (
            self.development.split != "train"
            or self.final.split != "test"
            or self.development.dataset_id != self.final.dataset_id
            or set(self.development.query_ids) & set(self.final.query_ids)
        ):
            raise ValueError("部署开发与最终数据绑定不合法")
        for manifest in (self.development, self.final):
            if (
                len(manifest.query_ids) != manifest.query_count
                or len(set(manifest.query_ids)) != manifest.query_count
                or len(manifest.document_ids) != manifest.corpus_count
            ):
                raise ValueError("部署manifest覆盖不完整")
            for item in self.materials:
                key = {
                    "corpus": "corpus",
                    "queries": "queries",
                    "development_qrels": "qrels",
                    "test_qrels": "qrels",
                }[item.role]
                if (
                    item.role
                    in {
                        "corpus",
                        "queries",
                        "development_qrels"
                        if manifest.split == "train"
                        else "test_qrels",
                    }
                    and manifest.source_sha256[key] != item.content_digest
                ):
                    raise ValueError("部署原件hash与manifest不同")
        return self


class BoundInputIdentity(StrictModel):
    resource_ref: ResourceRef
    content_digest: Digest


class PublishedExperimentResult(StrictModel):
    raw_result_ref: ResourceRef
    rankings_ref: ResourceRef
    coverage_ref: ResourceRef
    metrics_ref: ResourceRef
    per_query_ref: ResourceRef
    corpus: BoundInputIdentity
    queries: BoundInputIdentity
    input_result_refs: tuple[ResourceRef, ...] = ()
    program_ref: ResourceRef | None = None
    config_ref: ResourceRef | None = None


class PublishedFrozenExperiment(StrictModel):
    frozen: FrozenExperiment
    selected_result_ref: ResourceRef
    input_result_refs: tuple[ResourceRef, ...]
    program_ref: ResourceRef | None = None
    config_ref: ResourceRef | None = None


class BoundArtifact(BoundInputIdentity):
    content: bytes

    @model_validator(mode="after")
    def verify_digest(self, info: ValidationInfo) -> BoundArtifact:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if hashlib.sha256(self.content).hexdigest() != self.content_digest:
            raise ValueError(prompts.render('experiment_validation.input_digest'))
        return self


class DevelopmentWorkload(StrictModel):
    operation: Literal["run_development"]
    config: ExperimentConfig
    input_results: tuple[PublishedExperimentResult, ...] = ()
    input_result_refs: tuple[ResourceRef, ...] = ()
    program_ref: ResourceRef | None = None
    config_ref: ResourceRef | None = None


class FinalWorkload(StrictModel):
    operation: Literal["evaluate_final"]
    frozen_ref: ResourceRef
    frozen: PublishedFrozenExperiment


Workload = Annotated[
    DevelopmentWorkload | FinalWorkload, Field(discriminator="operation")
]


class ExperimentCommand(StrictModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    request_digest: Digest
    deployment_digest: Digest
    workload: Workload
    bound_inputs: tuple[BoundInputIdentity, ...]
    accepted_at: AwareDatetime
    deadline_at: AwareDatetime
    reserved_seconds: PositiveSeconds
    command_digest: Digest

    @model_validator(mode="after")
    def validate_command(self, info: ValidationInfo) -> ExperimentCommand:
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        if self.deadline_at <= self.accepted_at:
            raise ValueError(prompts.render('experiment_validation.deadline'))
        if self.command_digest != canonical_digest(
            self.model_dump(mode="json", exclude={"command_digest"})
        ):
            raise ValueError(prompts.render('experiment_validation.command_digest'))
        if any(
            item.resource_ref.owner != self.execution_scope.principal
            for item in self.bound_inputs
        ):
            raise ValueError(prompts.render('experiment_validation.input_owner'))
        return self


class BackendJobFact(StrictModel):
    job_key: Digest
    role: Literal["baseline", "rrf", "candidate", "score"]
    container_name: Identifier
    container_id: Identifier | None = None
    image_id: Identifier | None = None
    status: Literal[
        "created",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "output_limit",
        "unknown",
    ]
    elapsed_seconds: Seconds | None = None


class ExperimentExecutionFact(StrictModel):
    status: Literal[
        "dispatching", "succeeded", "failed", "timed_out", "output_limit", "unknown"
    ]
    jobs: tuple[BackendJobFact, ...] = ()
    elapsed_seconds: Seconds | None = None
    error_code: ErrorCode | None = None


class ExperimentActionReceipt(StrictModel):
    operation: Literal["run_development", "freeze", "evaluate_final"]
    status: Status
    result_refs: tuple[ResourceRef, ...] = ()
    frozen_ref: ResourceRef | None = None
    diagnostic_refs: tuple[ResourceRef, ...] = ()
    error_code: ErrorCode | None = None


class ExperimentRecord(StrictModel):
    action_id: Identifier
    request_digest: Digest
    command: ExperimentCommand | None = None
    execution: ExperimentExecutionFact | None = None
    receipt: ExperimentActionReceipt | None = None


class ExperimentJournalView(StrictModel):
    execution_scope: ExecutionScope
    action_id: Identifier
    action: ExperimentAction
    request_digest: Digest
    deployment_digest: Digest
    allowed_artifact_refs: tuple[ResourceRef, ...]
    run_deadline_at: AwareDatetime
    remaining_execution_seconds: Seconds
    records: tuple[ExperimentRecord, ...] = ()


class ExperimentMetricSummary(StrictModel):
    result_ref: ResourceRef
    publication: PublishedExperimentResult
    method: Literal["bm25", "dense", "rrf", "candidate"]
    split: Literal["train", "test"]
    query_count: PositiveInteger
    retrieve_k: Depth
    metrics: Metrics


class ExperimentToolResult(StrictModel):
    receipt: ExperimentActionReceipt
    summaries: tuple[ExperimentMetricSummary, ...] = ()
    elapsed_seconds: Seconds = 0
    unsettled_seconds: Seconds = 0
    limitations: tuple[str, ...] = ()
    corpus: BoundInputIdentity | None = None
    queries: BoundInputIdentity | None = None


class ResultBundle(StrictModel):
    result: ExperimentResult
    result_bytes: bytes
    rankings: bytes
    coverage: bytes
    metrics: bytes
    per_query: bytes
    corpus_bytes: bytes
    queries_bytes: bytes


class BackendDiagnostic(StrictModel):
    filename: str
    content_type: str
    content: bytes
    limitations: tuple[str, ...] = ()


class BackendOutcome(StrictModel):
    execution: ExperimentExecutionFact
    results: tuple[ResultBundle, ...] = ()
    diagnostics: tuple[BackendDiagnostic, ...] = ()
