"""检索实验冻结与最终执行的唯一无 IO 规则。"""

from __future__ import annotations

from .contracts import (
    Coverage,
    DatasetManifest,
    ExperimentResult,
    FrozenExperiment,
    InputRecipe,
)


def recipe(result: ExperimentResult) -> InputRecipe:
    return InputRecipe(
        config=result.config, implementation=result.implementation, model=result.model
    )


def freeze_experiment(
    result: ExperimentResult,
    result_digest: str,
    coverage: Coverage,
    parents: tuple[ExperimentResult, ...],
    parent_digests: tuple[str, ...],
    *,
    program_digest: str | None = None,
    config_digest: str | None = None,
) -> FrozenExperiment:
    if result.dataset.split != "train":
        raise ValueError("只能从开发结果冻结方案")
    query_ids = tuple(item.query_id for item in coverage.queries)
    if (
        not query_ids
        or len(query_ids) != len(set(query_ids))
        or len(query_ids) != result.metrics.query_count
        or coverage.dataset_id != result.dataset.dataset_id
        or coverage.split_id != result.dataset.split_id
        or coverage.split != "train"
    ):
        raise ValueError("冻结结果缺少完整且一致的开发查询执行事实")
    if parent_digests != result.input_results or len(parents) != len(parent_digests):
        raise ValueError("冻结提供的输入排名与实际运行不一致")
    for parent in parents:
        if parent.dataset != result.dataset or parent.config.method not in {
            "bm25",
            "dense",
        }:
            raise ValueError("首版仅冻结同数据开发集的受信基线输入")
    if result.candidate and (
        program_digest != result.candidate.source_sha256
        or config_digest != result.candidate.config_sha256
    ):
        raise ValueError("候选源码或配置与已执行版本不一致")
    return FrozenExperiment(
        dataset_id=result.dataset.dataset_id,
        development_split_id=result.dataset.split_id,
        development_result_sha256=result_digest,
        development_query_ids=query_ids,
        recipe=recipe(result),
        inputs=tuple(recipe(parent) for parent in parents),
        program_sha256=program_digest if result.candidate else None,
        program_config_sha256=config_digest if result.candidate else None,
        candidate_image_id=result.candidate.image_id if result.candidate else None,
        candidate_timeout_seconds=(
            result.candidate.timeout_seconds if result.candidate else None
        ),
    )


def validate_final_dataset(frozen: FrozenExperiment, manifest: DatasetManifest) -> None:
    if manifest.split != "test" or manifest.dataset_id != frozen.dataset_id:
        raise ValueError("test 数据与冻结的数据快照不一致")
    if set(manifest.query_ids) & set(frozen.development_query_ids):
        raise ValueError("test 查询与开发查询重叠")


def validate_final_result(frozen: FrozenExperiment, actual: ExperimentResult) -> None:
    if recipe(actual) != frozen.recipe:
        raise ValueError("实际 test 实现或模型与冻结版本不一致")
    if frozen.program_sha256 is not None and (
        actual.candidate is None
        or actual.candidate.image_id != frozen.candidate_image_id
        or actual.candidate.source_sha256 != frozen.program_sha256
        or actual.candidate.config_sha256 != frozen.program_config_sha256
        or actual.candidate.timeout_seconds != frozen.candidate_timeout_seconds
    ):
        raise ValueError("实际 test 候选身份与冻结方案不一致")
