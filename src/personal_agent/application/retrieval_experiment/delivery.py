"""核对实际实验完成事实；保留历史清单的离线读取类型，不生成用户文件包。"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope

from .contracts import (
    Coverage,
    DatasetManifest,
    Digest,
    ExperimentResult,
    Metrics,
    ModelIdentity,
    QueryMetrics,
    StrictModel,
    canonical_digest,
    dataset_binding,
    validate_rankings,
)
from .models import (
    BoundArtifact,
    DevelopmentWorkload,
    ExperimentRecord,
    FinalWorkload,
    PublishedExperimentResult,
    RetrievalDeployment,
)
from .rules import (
    freeze_experiment,
    recipe,
    validate_final_dataset,
    validate_final_result,
)
from .service import RetrievalExperimentService


class DeliveryGap(StrictModel):
    code: Literal[
        "execution_unsettled",
        "development_missing",
        "freeze_missing",
        "final_missing",
        "final_ambiguous",
        "fact_missing",
        "coverage_incomplete",
        "artifact_missing",
        "identity_mismatch",
    ]
    message: Annotated[str, Field(min_length=1, max_length=500)]
    missing_refs: tuple[ResourceRef, ...] = Field(default=(), max_length=16)


class DeliveryIncomplete(ValueError):
    """可交给原模型修复的业务缺口；权限和损坏异常不降为该类。"""

    def __init__(self, *gaps: DeliveryGap) -> None:
        if not gaps or len(gaps) > 16:
            raise ValueError("交付缺口必须为 1 至 16 项")
        self.gaps = tuple(gaps)
        super().__init__("；".join(gap.message for gap in gaps))


def _incomplete(code: str, message: str, *refs: ResourceRef) -> DeliveryIncomplete:
    return DeliveryIncomplete(
        DeliveryGap(code=code, message=message, missing_refs=refs)
    )


class ExperimentDeliveryFacts(StrictModel):
    frozen_ref: ResourceRef
    development_result_refs: tuple[ResourceRef, ...] = Field(min_length=1)
    final_result_refs: tuple[ResourceRef, ...] = Field(min_length=1)
    candidate_development_refs: tuple[ResourceRef, ...] = ()


def validate_export_path(value: str) -> str:
    if not re.fullmatch(
        r"files/[0-9a-f]{64}/[0-9a-f]{64}\.(?:json|jsonl|py|txt|csv|tsv|bin)", value
    ):
        raise ValueError("导出文件必须使用 files/ 下由导出端生成的摘要路径")
    return value


def _export_path(resource: ArtifactResourceItem) -> str:
    media_type = (resource.content_type or "").split(";", 1)[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        suffix = "json"
    else:
        suffix = {
            "text/x-python": "py",
            "application/x-python-code": "py",
            "application/x-ndjson": "jsonl",
            "text/csv": "csv",
            "text/tab-separated-values": "tsv",
        }.get(media_type, "txt" if media_type.startswith("text/") else "bin")
    identity = canonical_digest(resource.resource_ref.model_dump(mode="json"))
    return f"files/{identity}/{resource.content_digest}.{suffix}"


class ExportedArtifact(StrictModel):
    relative_path: str
    resource: ArtifactResourceItem

    _path = field_validator("relative_path")(validate_export_path)

    @model_validator(mode="after")
    def validate_identity_path(self) -> ExportedArtifact:
        if self.relative_path != _export_path(self.resource):
            raise ValueError("导出路径与资源身份、摘要或内容类型不同")
        return self


class ReproduceCandidateDevelopment(StrictModel):
    kind: Literal["candidate_development"] = "candidate_development"
    result_ref: ResourceRef


class ReproduceSelectedFinal(StrictModel):
    kind: Literal["selected_final"] = "selected_final"
    frozen_ref: ResourceRef
    result_refs: tuple[ResourceRef, ...] = Field(min_length=1)


ReproductionTask = Annotated[
    ReproduceCandidateDevelopment | ReproduceSelectedFinal, Field(discriminator="kind")
]


class ReproductionEnvironment(StrictModel):
    """仅内容身份；没有本地地址、许可主体或私有 ResourceRef。"""

    development: DatasetManifest
    final: DatasetManifest
    model: ModelIdentity
    worker_image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    candidate_image_id: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]

    @classmethod
    def from_deployment(
        cls, deployment: RetrievalDeployment
    ) -> ReproductionEnvironment:
        return cls(
            development=deployment.development,
            final=deployment.final,
            model=deployment.model,
            worker_image_id=deployment.worker_image_id,
            candidate_image_id=deployment.candidate_image_id,
        )


class ReproductionTolerance(StrictModel):
    score_absolute: Literal[0.000001] = 0.000001
    metric_decimal_places: Literal[5] = 5


class ReproductionManifest(StrictModel):
    schema_version: Literal[3] = 3
    submission_ref: ResourceRef
    body_digest: Digest
    facts: ExperimentDeliveryFacts
    artifacts: tuple[ExportedArtifact, ...] = Field(min_length=1)
    tasks: tuple[ReproductionTask, ...] = Field(min_length=1)
    environment: ReproductionEnvironment
    tolerance: ReproductionTolerance = Field(default_factory=ReproductionTolerance)

    @model_validator(mode="after")
    def validate_catalog(self) -> ReproductionManifest:
        if self.submission_ref.resource_type != "conversation_final":
            raise ValueError("复现清单必须绑定实际最终提交")
        paths = [item.relative_path.casefold() for item in self.artifacts]
        refs = [item.resource.resource_ref for item in self.artifacts]
        if len(paths) != len(set(paths)) or len(refs) != len(set(refs)):
            raise ValueError("清单导出路径及资源引用不能重复")
        if any(ref.owner != self.submission_ref.owner for ref in refs):
            raise PermissionError("公开交付不能包含其他主体的资源")
        required = {
            self.facts.frozen_ref,
            *self.facts.development_result_refs,
            *self.facts.final_result_refs,
            *self.facts.candidate_development_refs,
        }
        if not required.issubset(refs):
            raise ValueError("清单缺少绑定事实的原文件")
        candidates = tuple(
            task.result_ref
            for task in self.tasks
            if isinstance(task, ReproduceCandidateDevelopment)
        )
        finals = tuple(
            task for task in self.tasks if isinstance(task, ReproduceSelectedFinal)
        )
        if (
            candidates != self.facts.candidate_development_refs
            or len(finals) != 1
            or finals[0].frozen_ref != self.facts.frozen_ref
            or finals[0].result_refs != self.facts.final_result_refs
        ):
            raise ValueError("复现任务必须恰好覆盖实际候选开发及选中最终事实")
        return self


def manifest_bytes(manifest: ReproductionManifest) -> bytes:
    return (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _same_run(left: ExecutionScope, right: ExecutionScope) -> bool:
    return (
        left.principal == right.principal
        and left.execution_id == right.execution_id
        and left.thread_id == right.thread_id
    )


class RetrievalExperimentCompletionService:
    def __init__(self, *, experiments: RetrievalExperimentService) -> None:
        self.experiments = experiments
        self.artifacts = experiments.artifacts
        self.deployment = experiments.deployment

    def validate(self, *, execution_scope: ExecutionScope, records: tuple[ExperimentRecord, ...]) -> None:
        scope = execution_scope
        if (
            scope.principal != self.deployment.authorized_principal
        ):
            raise PermissionError("交付不属于当前获准实验主体")
        successful: dict[ResourceRef, tuple[int, ExperimentRecord]] = {}
        finals: list[tuple[int, ExperimentRecord]] = []
        for index, record in enumerate(records):
            if record.command:
                if (
                    not _same_run(record.command.execution_scope, scope)
                    or record.command.deployment_digest
                    != self.deployment.deployment_digest
                ):
                    raise PermissionError("实验事实与当前 run 或部署不一致")
                if (
                    record.command.action_id != record.action_id
                    or record.command.request_digest != record.request_digest
                    or (
                        record.receipt
                        and record.receipt.operation
                        != record.command.workload.operation
                    )
                ):
                    raise ValueError("实验记录与原接受身份不一致")
                if record.execution and record.execution.status in {
                    "dispatching",
                    "unknown",
                }:
                    raise _incomplete(
                        "execution_unsettled", "实验仍有尚未确认的执行，不能完整交付"
                    )
            if not record.receipt or record.receipt.status != "succeeded":
                continue
            if record.receipt.operation != "freeze" and (
                record.command is None
                or record.execution is None
                or record.execution.status != "succeeded"
            ):
                raise _incomplete("fact_missing", "成功回执缺少对应的实际成功执行")
            for ref in record.receipt.result_refs:
                if ref in successful and successful[ref][1] != record:
                    raise ValueError("同一实验结果出现互相冲突的记录")
                successful[ref] = index, record
            if record.command and isinstance(record.command.workload, FinalWorkload):
                finals.append((index, record))
        if not finals:
            raise _incomplete("final_missing", "尚无成功执行的完整最终评测")
        final_keys = {
            (record.command.workload.frozen_ref, record.receipt.result_refs)
            for _, record in finals
        }
        if len(final_keys) != 1:
            raise _incomplete(
                "final_ambiguous", "存在互不相同的最终方案，不能由交付端代选"
            )
        final_index, final_record = finals[0]
        workload = final_record.command.workload
        frozen_ref = workload.frozen_ref
        freeze_indices = tuple(
            index
            for index, record in enumerate(records)
            if index < final_index
            and record.receipt
            and record.receipt.status == "succeeded"
            and record.receipt.operation == "freeze"
            and record.receipt.frozen_ref == frozen_ref
        )
        if not freeze_indices:
            raise _incomplete(
                "freeze_missing", "最终评测之前没有本 run 的合法冻结", frozen_ref
            )
        try:
            frozen = self.experiments.read_frozen(frozen_ref, execution_scope=scope)
        except FileNotFoundError as error:
            raise _incomplete(
                "artifact_missing", "原冻结文件不存在", frozen_ref
            ) from error
        if frozen != workload.frozen:
            raise ValueError("最终执行绑定与原冻结文件不一致")
        contents: dict[ResourceRef, BoundArtifact] = {}
        results: dict[
            ResourceRef,
            tuple[
                PublishedExperimentResult, ExperimentResult, tuple[BoundArtifact, ...]
            ],
        ] = {}
        reading: set[ResourceRef] = set()

        def add(ref: ResourceRef) -> BoundArtifact:
            if ref in contents:
                return contents[ref]
            try:
                snapshot = self.artifacts.read_snapshot(
                    ref, principal=scope.principal, owner=scope.principal
                )
            except FileNotFoundError as error:
                raise _incomplete(
                    "artifact_missing", "交付所需原文件不存在", ref
                ) from error
            record_scope = snapshot.record.execution_scope
            if record_scope is None or not _same_run(record_scope, scope):
                raise PermissionError("交付文件不属于当前 run")
            if snapshot.record.purpose not in {"machine", "draft"}:
                raise PermissionError("交付原件必须来自当前实验或正式草稿写入口")
            content = snapshot.content.encode("utf-8")
            bound = BoundArtifact(
                resource_ref=ref,
                content_digest=snapshot.content_digest,
                content=content,
            )
            contents[ref] = bound
            return bound

        def result(ref: ResourceRef):
            if ref in results:
                return results[ref]
            if ref in reading:
                raise ValueError("实验结果存在循环输入引用")
            reading.add(ref)
            if ref not in successful:
                raise _incomplete("fact_missing", "结果没有本 run 的实际成功记录", ref)
            try:
                publication, actual, files = self.experiments.read_result(
                    ref, execution_scope=scope
                )
            except FileNotFoundError as error:
                raise _incomplete(
                    "artifact_missing", "结果所需原文件不存在", ref
                ) from error
            manifest = (
                self.deployment.development
                if actual.dataset.split == "train"
                else self.deployment.final
            )
            if (
                actual.implementation.image_id != self.deployment.worker_image_id
                or (actual.model is not None and actual.model != self.deployment.model)
                or (actual.config.method == "dense" and actual.model is None)
            ):
                raise ValueError("实际实验实现或模型与当前许可身份不同")
            if (actual.config.method == "candidate") != (actual.candidate is not None):
                raise ValueError("候选方法与实际候选执行身份不一致")
            self._validate_result(actual, files, manifest)
            for item in files:
                checked = add(item.resource_ref)
                if checked != item:
                    raise ValueError("交付读取期间原文件发生变化")
            for parent in publication.input_result_refs:
                result(parent)
            if (
                tuple(
                    results[parent][2][1].content_digest
                    for parent in publication.input_result_refs
                )
                != actual.input_results
            ):
                raise ValueError("结果父输入与实际原字节摘要不同")
            for source in (publication.program_ref, publication.config_ref):
                if source:
                    add(source)
            if actual.candidate is None and (
                publication.program_ref is not None
                or publication.config_ref is not None
            ):
                raise ValueError("非候选结果不能绑定候选源码或配置")
            if actual.candidate:
                if publication.program_ref is None:
                    raise _incomplete("fact_missing", "实际候选缺少源码引用", ref)
                source = contents[publication.program_ref]
                config_digest = (
                    contents[publication.config_ref].content_digest
                    if publication.config_ref
                    else hashlib.sha256(b"").hexdigest()
                )
                if (
                    source.content_digest != actual.candidate.source_sha256
                    or config_digest != actual.candidate.config_sha256
                    or actual.candidate.image_id != self.deployment.candidate_image_id
                ):
                    raise ValueError("候选源码、配置或执行镜像与原结果不同")
            results[ref] = publication, actual, files
            reading.remove(ref)
            return results[ref]

        # 所有成功开发候选均保留；开发基线是完整比较的必要事实。
        development_baselines = set()
        for ref, (index, record) in successful.items():
            publication, actual, _ = result(ref)
            if (
                isinstance(record.command.workload, DevelopmentWorkload)
                and actual.dataset.split == "train"
            ):
                if index < final_index and actual.config.method in {"bm25", "dense"}:
                    development_baselines.add(actual.config.method)
        if development_baselines != {"bm25", "dense"}:
            raise _incomplete(
                "development_missing", "需要完整成功的 BM25 与 dense 开发实验"
            )
        selected_publication, selected_result, selected_files = result(
            frozen.selected_result_ref
        )
        selected_index = successful[frozen.selected_result_ref][0]
        if (
            selected_index >= min(freeze_indices)
            or selected_result.dataset.split != "train"
        ):
            raise _incomplete("identity_mismatch", "冻结选中项不是冻结之前的开发结果")
        if (
            selected_publication.input_result_refs != frozen.input_result_refs
            or selected_publication.program_ref != frozen.program_ref
            or selected_publication.config_ref != frozen.config_ref
        ):
            raise ValueError("冻结的输入或源码引用与原选中开发结果不同")
        rebuilt = freeze_experiment(
            selected_result,
            selected_files[1].content_digest,
            Coverage.model_validate_json(selected_files[3].content),
            tuple(results[ref][1] for ref in frozen.input_result_refs),
            tuple(
                results[ref][2][1].content_digest for ref in frozen.input_result_refs
            ),
            program_digest=contents[frozen.program_ref].content_digest
            if frozen.program_ref
            else None,
            config_digest=contents[frozen.config_ref].content_digest
            if frozen.config_ref
            else hashlib.sha256(b"").hexdigest(),
        )
        if rebuilt != frozen.frozen:
            raise ValueError("冻结文件与原开发结果、配置或源码不一致")
        validate_final_dataset(frozen.frozen, self.deployment.final)
        actual_finals = tuple(
            result(ref)[1] for ref in final_record.receipt.result_refs
        )
        if any(
            item.dataset != dataset_binding(self.deployment.final)
            for item in actual_finals
        ):
            raise _incomplete("identity_mismatch", "最终回执包含其他 split 的实验结果")
        if not any(item.config.method == "bm25" for item in actual_finals):
            raise _incomplete("final_missing", "最终评测缺少实际 BM25 基线")
        selected_finals = [
            item for item in actual_finals if recipe(item) == frozen.frozen.recipe
        ]
        if len(selected_finals) != 1:
            raise _incomplete("final_missing", "最终评测缺少唯一的冻结选中结果")
        validate_final_result(frozen.frozen, selected_finals[0])
        add(frozen_ref)

    @staticmethod
    def _validate_result(
        actual: ExperimentResult,
        files: tuple[BoundArtifact, ...],
        manifest: DatasetManifest,
    ) -> None:
        if (
            actual.dataset != dataset_binding(manifest)
            or actual.metrics.query_count != manifest.query_count
        ):
            raise _incomplete("coverage_incomplete", "实验不是当前完整数据集的结果")
        coverage = Coverage.model_validate_json(files[3].content)
        rankings = validate_rankings(
            json.loads(files[2].content), manifest, actual.config.retrieve_k
        )
        if (
            coverage.dataset_id != manifest.dataset_id
            or coverage.split_id != manifest.split_id
            or coverage.split != manifest.split
            or coverage.retrieve_k != actual.config.retrieve_k
            or tuple(item.query_id for item in coverage.queries) != manifest.query_ids
            or any(
                item.backend != actual.config.method
                or item.hit_count != len(rankings[item.query_id])
                for item in coverage.queries
            )
        ):
            raise _incomplete(
                "coverage_incomplete", "查询执行事实不完整或与实际排名不同"
            )
        if Metrics.model_validate_json(files[4].content) != actual.metrics:
            raise ValueError("原指标文件与 result 不一致")
        per_query = TypeAdapter(dict[str, QueryMetrics]).validate_json(files[5].content)
        if set(per_query) != set(manifest.query_ids):
            raise _incomplete("coverage_incomplete", "逐查询指标没有覆盖完整查询集")

