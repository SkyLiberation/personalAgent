"""候选环境之外校验执行事实，并以完整 split 分母独立评分。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .file_io import (
    read_json,
    sha256_file,
    write_json,
)
from personal_agent.application.retrieval_experiment.contracts import (
    ArtifactFile,
    CandidateIdentity,
    Coverage,
    DatasetManifest,
    ExperimentConfig,
    ExperimentResult,
    ImplementationIdentity,
    Metrics,
    ModelIdentity,
    QueryExecution,
    QueryMetrics,
    Rankings,
    ResultArtifacts,
    dataset_binding,
    validate_rankings,
)


def validate_coverage(
    coverage: Coverage,
    manifest: DatasetManifest,
    rankings: Rankings,
    config: ExperimentConfig,
) -> None:
    if (
        coverage.dataset_id != manifest.dataset_id
        or coverage.split_id != manifest.split_id
        or coverage.split != manifest.split
        or coverage.retrieve_k != config.retrieve_k
    ):
        raise ValueError("执行覆盖与数据、split 或配置身份不一致")
    executions = {execution.query_id: execution for execution in coverage.queries}
    if len(executions) != len(coverage.queries) or set(executions) != set(
        manifest.query_ids
    ):
        raise ValueError("缺少逐查询执行事实或存在重复、未知查询")
    if any(
        execution.hit_count != len(rankings[qid]) or execution.backend != config.method
        for qid, execution in executions.items()
    ):
        raise ValueError("查询执行事实与排名或方法不一致")


def load_result(
    result_path: str | Path, manifest: DatasetManifest
) -> tuple[ExperimentResult, Rankings, Coverage]:
    path = Path(result_path)
    result = ExperimentResult.model_validate(read_json(path))
    if result.dataset != dataset_binding(manifest):
        raise ValueError("输入结果属于其他数据快照或 split")
    for role, artifact in result.artifacts:
        if (
            artifact.path != f"{role}.json"
            or sha256_file(path.parent / artifact.path) != artifact.sha256
        ):
            raise ValueError(f"输入结果工件身份不一致：{role}")
    rankings = validate_rankings(
        read_json(path.parent / result.artifacts.rankings.path),
        manifest,
        result.config.retrieve_k,
    )
    coverage = Coverage.model_validate(
        read_json(path.parent / result.artifacts.coverage.path)
    )
    validate_coverage(coverage, manifest, rankings, result.config)
    metrics = Metrics.model_validate(
        read_json(path.parent / result.artifacts.metrics.path)
    )
    if result.metrics != metrics or metrics.query_count != manifest.query_count:
        raise ValueError("输入结果的指标或查询分母不一致")
    if result.config.method == "dense" and result.model is None:
        raise ValueError("dense 结果缺少模型身份")
    if result.config.method == "candidate" and result.candidate is None:
        raise ValueError("candidate 结果缺少候选执行身份")
    return result, rankings, coverage


def score_rankings(
    manifest: DatasetManifest,
    qrels: dict[str, dict[str, int]],
    rankings: Rankings,
    coverage: Coverage,
    config: ExperimentConfig,
) -> tuple[Metrics, dict[str, QueryMetrics]]:
    import pytrec_eval

    rankings = validate_rankings(rankings, manifest, config.retrieve_k)
    validate_coverage(coverage, manifest, rankings, config)
    if set(qrels) != set(manifest.query_ids):
        raise ValueError("评分标注查询集合与 split 不一致")
    evaluator = pytrec_eval.RelevanceEvaluator(qrels, {"ndcg_cut.10", "recall.100"})
    # pytrec_eval 不返回空排名的 query；这些确已完成的查询必须显式计零。
    nonempty = {qid: scores for qid, scores in rankings.items() if scores}
    evaluated = evaluator.evaluate(nonempty) if nonempty else {}
    if set(evaluated) != set(nonempty):
        raise ValueError("独立评分器没有返回全部非空查询")
    per_query = {}
    for qid in manifest.query_ids:
        if rankings[qid]:
            observed = evaluated[qid]
            per_query[qid] = QueryMetrics(
                ndcg_at_10=observed["ndcg_cut_10"], recall_at_100=observed["recall_100"]
            )
        else:
            per_query[qid] = QueryMetrics(ndcg_at_10=0.0, recall_at_100=0.0)
    metrics = Metrics(
        ndcg_at_10=round(
            sum(item.ndcg_at_10 for item in per_query.values()) / manifest.query_count,
            5,
        ),
        recall_at_100=round(
            sum(item.recall_at_100 for item in per_query.values())
            / manifest.query_count,
            5,
        ),
        query_count=manifest.query_count,
    )
    return metrics, per_query


def transformed_coverage(
    manifest: DatasetManifest, rankings: Rankings, config: ExperimentConfig
) -> Coverage:
    """仅在受信变换成功，或 runner 终态输出完成校验后由受信端调用。"""
    return Coverage(
        **dataset_binding(manifest).model_dump(),
        retrieve_k=config.retrieve_k,
        queries=tuple(
            QueryExecution(
                query_id=qid, hit_count=len(rankings[qid]), backend=config.method
            )
            for qid in manifest.query_ids
        ),
    )


def reciprocal_rank_fusion(
    inputs: tuple[Rankings, ...], manifest: DatasetManifest, retrieve_k: int
) -> Rankings:
    fused: Rankings = {}
    for qid in manifest.query_ids:
        scores: dict[str, float] = {}
        for rankings in inputs:
            ordered = sorted(
                rankings[qid].items(), key=lambda pair: (pair[1], pair[0]), reverse=True
            )
            for rank, (docid, _) in enumerate(ordered, start=1):
                scores[docid] = scores.get(docid, 0.0) + 1.0 / (60 + rank)
        fused[qid] = dict(
            sorted(scores.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)[
                :retrieve_k
            ]
        )
    return validate_rankings(fused, manifest, retrieve_k)


def _write_query_metrics(path: Path, metrics: Mapping[str, QueryMetrics]) -> None:
    """Keep each query on one searchable line within the same standard JSON object."""
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write("{\n")
        separator = ""
        for query_id, value in metrics.items():
            output.write(separator)
            # JSON escaping also prevents line separators inside an identifier.
            json.dump(query_id, output, ensure_ascii=True, allow_nan=False)
            output.write(":")
            json.dump(
                value.model_dump(mode="json"),
                output,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            separator = ",\n"
        output.write("\n}\n")


def write_result(
    output_dir: str | Path,
    manifest: DatasetManifest,
    qrels: dict[str, dict[str, int]],
    rankings: Rankings,
    coverage: Coverage,
    config: ExperimentConfig,
    implementation: ImplementationIdentity,
    *,
    model: ModelIdentity | None = None,
    candidate: CandidateIdentity | None = None,
    input_results: tuple[str, ...] = (),
) -> Path:
    rankings = validate_rankings(rankings, manifest, config.retrieve_k)
    metrics, per_query = score_rankings(manifest, qrels, rankings, coverage, config)
    output = Path(output_dir)
    # 控制端在挂载目录先保存作业身份；它不是排名或评分产物。
    if output.exists() and (
        not output.is_dir() or any(path.name != "job.json" for path in output.iterdir())
    ):
        raise ValueError("输出目录非空，拒绝覆盖已有实验")
    output.mkdir(parents=True, exist_ok=True)
    contents: Mapping[str, object] = {
        "rankings": rankings,
        "coverage": coverage,
        "metrics": metrics,
    }
    artifacts = {}
    for role, content in contents.items():
        filename = f"{role}.json"
        write_json(output / filename, content)
        artifacts[role] = ArtifactFile(
            path=filename, sha256=sha256_file(output / filename)
        )
    _write_query_metrics(output / "per_query.json", per_query)
    artifacts["per_query"] = ArtifactFile(
        path="per_query.json", sha256=sha256_file(output / "per_query.json")
    )
    result = ExperimentResult(
        config=config,
        dataset=dataset_binding(manifest),
        implementation=implementation,
        model=model,
        candidate=candidate,
        input_results=input_results,
        artifacts=ResultArtifacts.model_validate(artifacts),
        metrics=metrics,
    )
    write_json(output / "result.json", result)
    return output / "result.json"
