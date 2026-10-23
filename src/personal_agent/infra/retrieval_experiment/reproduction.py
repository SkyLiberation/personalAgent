"""只读交付包和干净复现：宿主 IO 留在外层，执行复用原实验引擎。"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import Field

from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.application.retrieval_experiment.contracts import (
    Digest,
    ExperimentResult,
    Metrics,
    StrictModel,
    canonical_digest,
    validate_rankings,
)
from personal_agent.application.retrieval_experiment.delivery import (
    ReproduceCandidateDevelopment,
    ReproduceSelectedFinal,
    ReproductionEnvironment,
    ReproductionManifest,
    manifest_bytes,
)
from personal_agent.application.retrieval_experiment.models import (
    BoundArtifact,
    BoundInputIdentity,
    DevelopmentWorkload,
    ExperimentCommand,
    FinalWorkload,
    ResultBundle,
    RetrievalDeployment,
)
from personal_agent.application.retrieval_experiment.ports import ExperimentArtifactPort
from personal_agent.application.retrieval_experiment.results import (
    PublishedExperimentReader,
)
from personal_agent.application.retrieval_experiment.rules import recipe
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope

from .backend import DockerExperimentBackend
from .controller import _docker_client
from .deployment import LocalExperimentEnvironment
from .file_io import read_json, sha256_file, write_json


class ExportedArtifactReader:
    """已下载文件的只读 Artifact 投影；身份、大小及摘要在任何作业前核对。"""

    def __init__(self, manifest_path: Path) -> None:
        if manifest_path.is_symlink():
            raise ValueError("复现清单不能为符号链接")
        self.root = manifest_path.resolve().parent
        self.manifest = ReproductionManifest.model_validate(read_json(manifest_path))
        self._items: dict[ResourceRef, tuple[ArtifactResourceItem, bytes]] = {}
        for exported in self.manifest.artifacts:
            path = self.root.joinpath(*exported.relative_path.split("/"))
            current = path
            while current != self.root:
                if current.is_symlink():
                    raise ValueError("导出文件路径不能包含符号链接")
                current = current.parent
            if not path.resolve().is_relative_to(self.root):
                raise ValueError("导出文件越过包目录")
            content = path.read_bytes()
            item = exported.resource
            if (
                len(content) != item.size_bytes
                or hashlib.sha256(content).hexdigest() != item.content_digest
            ):
                raise ValueError(f"导出文件大小或摘要不符：{exported.relative_path}")
            self._items[item.resource_ref] = item, content

    def resource_item(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem:
        if principal != owner or resource_ref.owner != principal:
            raise PermissionError("不能读取其他主体的导出资源")
        if resource_ref not in self._items:
            raise FileNotFoundError("清单没有所需公开资源")
        return self._items[resource_ref][0]

    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[ArtifactResourceItem, bytes]:
        item = self.resource_item(resource_ref, principal=principal, owner=owner)
        return item, self._items[resource_ref][1]

class ReproductionComparison(StrictModel):
    expected_result_ref: ResourceRef
    query_count: int = Field(gt=0)
    ranked_document_count: int = Field(ge=0)
    maximum_score_delta: float = Field(ge=0, le=0.000001, allow_inf_nan=False)


class ReproductionReport(StrictModel):
    schema_version: Literal[1] = 1
    manifest_digest: Digest
    comparisons: tuple[ReproductionComparison, ...]


def _compare(
    expected_ref: ResourceRef,
    expected: ExperimentResult,
    original_rankings: bytes,
    actual: ResultBundle,
    deployment: RetrievalDeployment,
) -> ReproductionComparison:
    if recipe(expected) != recipe(actual.result):
        raise ValueError("复现实现、模型或配置与交付结果不同")
    if expected.candidate and (
        actual.result.candidate is None
        or expected.candidate.source_sha256 != actual.result.candidate.source_sha256
        or expected.candidate.config_sha256 != actual.result.candidate.config_sha256
        or expected.candidate.image_id != actual.result.candidate.image_id
        or expected.candidate.timeout_seconds != actual.result.candidate.timeout_seconds
    ):
        raise ValueError("复现候选源码、配置或执行约束不同")
    manifest = (
        deployment.development
        if expected.dataset.split == "train"
        else deployment.final
    )
    if expected.dataset != actual.result.dataset:
        raise ValueError("复现数据身份与原结果不同")
    left = validate_rankings(
        json.loads(original_rankings), manifest, expected.config.retrieve_k
    )
    right = validate_rankings(
        json.loads(actual.rankings), manifest, expected.config.retrieve_k
    )
    maximum, count = 0.0, 0
    for query_id in manifest.query_ids:
        if tuple(left[query_id]) != tuple(right[query_id]):
            raise ValueError("复现查询的文档 ID 或排名顺序不同")
        for document_id, score in left[query_id].items():
            maximum = max(maximum, abs(score - right[query_id][document_id]))
            count += 1
    if maximum > 0.000001:
        raise ValueError("复现原始分数差异超过 1e-6")
    left_metrics, right_metrics = expected.metrics, actual.result.metrics
    if (
        left_metrics.query_count != right_metrics.query_count
        or any(
            f"{getattr(left_metrics, name):.5f}"
            != f"{getattr(right_metrics, name):.5f}"
            for name in ("ndcg_at_10", "recall_at_100")
        )
        or Metrics.model_validate_json(actual.metrics) != right_metrics
    ):
        raise ValueError("复现指标未保持五位小数一致")
    return ReproductionComparison(
        expected_result_ref=expected_ref,
        query_count=manifest.query_count,
        ranked_document_count=count,
        maximum_score_delta=maximum,
    )


def reproduce(
    manifest_path: Path,
    output: Path,
    *,
    deployment: RetrievalDeployment,
    environment: LocalExperimentEnvironment,
    artifacts: ExperimentArtifactPort,
) -> Path:
    """固定任务从清单恢复；本机许可与地址仅来自既有受信部署。"""
    catalog = ExportedArtifactReader(manifest_path)
    manifest = catalog.manifest
    if manifest.environment != ReproductionEnvironment.from_deployment(deployment):
        raise ValueError("本地许可数据、模型或镜像身份与交付清单不同")
    if manifest.submission_ref.owner != deployment.authorized_principal:
        raise PermissionError("本地受信部署没有该交付主体的许可")
    if output.exists() or output.is_symlink():
        raise ValueError("复现输出必须是尚不存在的新目录")
    if output.resolve().is_relative_to(catalog.root):
        raise ValueError("复现输出不能写入交付包目录")
    model_digest = canonical_digest(
        {
            path.relative_to(environment.model_path).as_posix(): sha256_file(path)
            for path in sorted(environment.model_path.rglob("*"))
            if path.is_file()
        }
    )
    if model_digest != deployment.model.sha256:
        raise ValueError("本地模型原字节与许可身份不同")
    with closing(_docker_client(environment.endpoint)) as client:
        if any(
            client.images.get(image).id != image
            for image in (
                deployment.worker_image_id,
                deployment.candidate_image_id,
            )
        ):
            raise ValueError("交付所需确切镜像不可用")
    # 四种材料在任何作业之前一次读取校验；私有标签仅在评分后端使用。
    materials = []
    for binding in deployment.materials:
        principal = (
            deployment.scorer_principal
            if binding.role == "test_qrels"
            else deployment.authorized_principal
        )
        try:
            _, content = artifacts.read_upload(
                binding.resource_ref, principal=principal, owner=principal
            )
        except (PermissionError, FileNotFoundError) as error:
            if binding.role == "test_qrels":
                raise PermissionError(
                    "当前许可环境没有私有最终评分标签，不能完成评分复现"
                ) from error
            raise
        materials.append(
            BoundArtifact(
                resource_ref=binding.resource_ref,
                content_digest=binding.content_digest,
                content=content,
            )
        )
    scope = ExecutionScope(
        principal=deployment.authorized_principal,
        execution_id="reproduce_"
        + hashlib.sha256(manifest_bytes(manifest)).hexdigest()[:24],
        thread_id="reproduction",
    )
    reader = PublishedExperimentReader(artifacts=catalog, deployment=deployment)
    prepared_tasks = []
    for task in manifest.tasks:
        execution_inputs: list[BoundArtifact] = []
        if isinstance(task, ReproduceCandidateDevelopment):
            publication, result, _ = reader.read_result(
                task.result_ref, execution_scope=scope
            )
            if (
                result.dataset.split != "train"
                or result.candidate is None
                or publication.program_ref is None
            ):
                raise ValueError("候选开发复现任务不对应实际候选开发结果")
            if (
                result.candidate.timeout_seconds
                != deployment.limits.candidate_timeout_seconds
            ):
                raise ValueError("本地候选时限与原实际执行不同")
            parent_results = tuple(
                reader.read_result(ref, execution_scope=scope)
                for ref in publication.input_result_refs
            )
            for _, _, files in parent_results:
                execution_inputs.extend(files)
            workload = DevelopmentWorkload(
                operation="run_development",
                config=result.config,
                input_results=tuple(parent[0] for parent in parent_results),
                input_result_refs=publication.input_result_refs,
                program_ref=publication.program_ref,
                config_ref=publication.config_ref,
            )
            source_refs = (publication.program_ref, publication.config_ref)
            expected_refs = (task.result_ref,)
        elif isinstance(task, ReproduceSelectedFinal):
            workload = FinalWorkload(
                operation="evaluate_final",
                frozen_ref=task.frozen_ref,
                frozen=reader.read_frozen(task.frozen_ref, execution_scope=scope),
            )
            source_refs = (workload.frozen.program_ref, workload.frozen.config_ref)
            expected_refs = task.result_refs
        else:
            raise ValueError("未知复现任务")
        expected = tuple(
            reader.read_result(ref, execution_scope=scope) for ref in expected_refs
        )
        for _, _, files in expected:
            execution_inputs.extend(files)
        execution_inputs.extend(
            reader.read_artifact(ref, execution_scope=scope)
            for ref in source_refs if ref is not None
        )
        prepared_tasks.append((
            task, workload, expected_refs, expected, tuple(execution_inputs)
        ))
    output.resolve().mkdir(parents=True, exist_ok=False)
    backend = DockerExperimentBackend(
        deployment=deployment,
        environment=environment.model_copy(
            update={"workspace_root": output.resolve() / "executions"}
        ),
    )
    started = datetime.now(timezone.utc)
    deadline = started + timedelta(seconds=deployment.limits.max_execution_seconds)
    comparisons = []
    public_materials = tuple(
        item for item in materials if item.resource_ref.owner == scope.principal
    )
    for index, (task, workload, expected_refs, expected, task_inputs) in enumerate(prepared_tasks):
        now = datetime.now(timezone.utc)
        remaining = min(
            (deadline - now).total_seconds(), deployment.limits.worker_timeout_seconds
        )
        if remaining <= 0:
            raise TimeoutError("复现总执行额度已耗尽")
        # 清单可包含分析程序与诊断原件；原实验只接收任务显式依赖，
        # 不因文件进入交付包就将其传给评分后端或自动执行。
        available = tuple({
            item.resource_ref: item for item in (*task_inputs, *public_materials)
        }.values())
        identities = tuple(
            BoundInputIdentity(
                resource_ref=item.resource_ref, content_digest=item.content_digest
            )
            for item in available
        )
        payload = dict(
            execution_scope=scope,
            action_id=f"reproduce-{index}",
            request_digest=canonical_digest(task.model_dump(mode="json")),
            deployment_digest=deployment.deployment_digest,
            workload=workload,
            bound_inputs=identities,
            accepted_at=now,
            deadline_at=now + timedelta(seconds=remaining),
            reserved_seconds=remaining,
        )
        from pydantic import TypeAdapter

        command = ExperimentCommand(
            **payload,
            command_digest=canonical_digest(
                TypeAdapter(dict).dump_python(payload, mode="json")
            ),
        )
        inputs = (
            available
            + tuple(
                item for item in materials if item.resource_ref.owner != scope.principal
            )
            if isinstance(workload, FinalWorkload)
            else available
        )
        outcome = backend.execute(command, inputs)
        if outcome.execution.status != "succeeded":
            raise RuntimeError(
                f"复现未成功：{outcome.execution.status}，{outcome.execution.error_code}"
            )
        if len(outcome.results) != len(expected):
            raise ValueError("复现结果集合与原最终执行集合不同")
        for ref, (_, original, files), actual in zip(
            expected_refs, expected, outcome.results
        ):
            comparisons.append(
                _compare(ref, original, files[2].content, actual, deployment)
            )
        backend.cleanup(command)
    report = ReproductionReport(
        manifest_digest=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        comparisons=tuple(comparisons),
    )
    report_path = output.resolve() / "reproduction.json"
    write_json(report_path, report)
    return report_path


def reproduce_from_settings(manifest_path: Path, output: Path) -> Path:
    # Heavy upload conversion dependencies remain lazy; ordinary engineering CLI
    # and --help do not load the product Runtime or Artifact service.
    from personal_agent.application.artifacts.service import ArtifactService
    from personal_agent.kernel.config import Settings
    from .deployment import load_retrieval_deployment

    settings = Settings.from_env()
    if settings.retrieval_experiment_config_path is None:
        raise ValueError("未配置 PERSONAL_AGENT_RETRIEVAL_EXPERIMENT_CONFIG")
    deployment, environment = load_retrieval_deployment(
        settings.retrieval_experiment_config_path
    )
    return reproduce(
        manifest_path,
        output,
        deployment=deployment,
        environment=environment,
        artifacts=ArtifactService(settings),
    )
