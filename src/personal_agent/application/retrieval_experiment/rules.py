"""检索实验冻结与最终执行的唯一无 IO 规则。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

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
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> FrozenExperiment:
    if result.dataset.split != "train":
        raise ValueError(prompts.render('experiment_rules.development_only'))
    query_ids = tuple(item.query_id for item in coverage.queries)
    if (
        not query_ids
        or len(query_ids) != len(set(query_ids))
        or len(query_ids) != result.metrics.query_count
        or coverage.dataset_id != result.dataset.dataset_id
        or coverage.split_id != result.dataset.split_id
        or coverage.split != "train"
    ):
        raise ValueError(prompts.render('experiment_rules.coverage'))
    if parent_digests != result.input_results or len(parents) != len(parent_digests):
        raise ValueError(prompts.render('experiment_rules.input_rankings'))
    for parent in parents:
        if parent.dataset != result.dataset or parent.config.method not in {
            "bm25",
            "dense",
        }:
            raise ValueError(prompts.render('experiment_rules.baseline_inputs'))
    if result.candidate and (
        program_digest != result.candidate.source_sha256
        or config_digest != result.candidate.config_sha256
    ):
        raise ValueError(prompts.render('experiment_rules.source_identity'))
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


def validate_final_dataset(frozen: FrozenExperiment, manifest: DatasetManifest, *, prompts: PromptCatalog = DEFAULT_PROMPTS) -> None:
    if manifest.split != "test" or manifest.dataset_id != frozen.dataset_id:
        raise ValueError(prompts.render('experiment_rules.final_dataset'))
    if set(manifest.query_ids) & set(frozen.development_query_ids):
        raise ValueError(prompts.render('experiment_rules.query_overlap'))


def validate_final_result(frozen: FrozenExperiment, actual: ExperimentResult, *, prompts: PromptCatalog = DEFAULT_PROMPTS) -> None:
    if recipe(actual) != frozen.recipe:
        raise ValueError(prompts.render('experiment_rules.final_recipe'))
    if frozen.program_sha256 is not None and (
        actual.candidate is None
        or actual.candidate.image_id != frozen.candidate_image_id
        or actual.candidate.source_sha256 != frozen.program_sha256
        or actual.candidate.config_sha256 != frozen.program_config_sha256
        or actual.candidate.timeout_seconds != frozen.candidate_timeout_seconds
    ):
        raise ValueError(prompts.render('experiment_rules.final_candidate'))
