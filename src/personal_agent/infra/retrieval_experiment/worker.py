"""容器内受信入口：python -m personal_agent.infra.retrieval_experiment.worker JOB_JSON。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .contracts import (
    JOB_ADAPTER,
    BaselineJob,
    RRFJob,
    ScoreJob,
)
from .file_io import (
    read_json,
    sha256_file,
)
from personal_agent.application.retrieval_experiment.contracts import (
    validate_rankings,
)
from .retrieval import implementation_identity, load_dataset, retrieve_baseline
from .scoring import (
    load_result,
    reciprocal_rank_fusion,
    transformed_coverage,
    write_result,
)


def run_job(job: BaselineJob | RRFJob | ScoreJob) -> Path:
    manifest, corpus, queries, qrels = load_dataset(job.manifest_path)
    implementation = implementation_identity(job.image_id)
    if isinstance(job, BaselineJob):
        rankings, coverage, model, backend = retrieve_baseline(
            job, manifest, corpus, queries
        )
        implementation = implementation.model_copy(update={"elasticsearch": backend})
        return write_result(
            job.output_dir,
            manifest,
            qrels,
            rankings,
            coverage,
            job.config,
            implementation,
            model=model,
        )
    if isinstance(job, RRFJob):
        loaded = [load_result(path, manifest) for path in job.input_results]
        if any(
            result.config.retrieve_k < job.config.retrieve_k for result, _, _ in loaded
        ):
            raise ValueError("RRF 输入排名深度低于输出配置")
        rankings = reciprocal_rank_fusion(
            tuple(ranking for _, ranking, _ in loaded), manifest, job.config.retrieve_k
        )
        coverage = transformed_coverage(manifest, rankings, job.config)
        models = {result.model for result, _, _ in loaded if result.model is not None}
        if len(models) > 1:
            raise ValueError("首版 RRF 不支持多个不同向量模型")
        return write_result(
            job.output_dir,
            manifest,
            qrels,
            rankings,
            coverage,
            job.config,
            implementation,
            model=next(iter(models), None),
            input_results=tuple(sha256_file(Path(path)) for path in job.input_results),
        )
    if job.input_result is not None:
        if (
            any(
                value is not None
                for value in (
                    job.candidate_rankings_path,
                    job.config,
                    job.candidate_identity,
                )
            )
            or job.input_results
        ):
            raise ValueError("复算已有结果不能混入候选参数")
        result, rankings, coverage = load_result(job.input_result, manifest)
        implementation = implementation.model_copy(
            update={"elasticsearch": result.implementation.elasticsearch}
        )
        return write_result(
            job.output_dir,
            manifest,
            qrels,
            rankings,
            coverage,
            result.config,
            implementation,
            model=result.model,
            candidate=result.candidate,
            input_results=result.input_results,
        )
    if (
        not job.candidate_rankings_path
        or job.config is None
        or job.candidate_identity is None
    ):
        raise ValueError("候选评分必须提供终态后恢复的排名、配置及确切执行身份")
    if len(job.input_results) < 2:
        raise ValueError("候选需要至少两份已完成的同 split 输入排名")
    loaded = [load_result(path, manifest) for path in job.input_results]
    if any(result.config.retrieve_k < job.config.retrieve_k for result, _, _ in loaded):
        raise ValueError("候选输入排名深度低于输出配置")
    candidate_path = Path(job.candidate_rankings_path)
    if sha256_file(candidate_path) != job.candidate_identity.stdout_sha256:
        raise ValueError("候选排名文件与 runner 封存 stdout 摘要不一致")
    rankings = validate_rankings(
        read_json(candidate_path), manifest, job.config.retrieve_k
    )
    coverage = transformed_coverage(manifest, rankings, job.config)
    models = {result.model for result, _, _ in loaded if result.model is not None}
    if len(models) > 1:
        raise ValueError("首版候选不支持多个不同向量模型")
    return write_result(
        job.output_dir,
        manifest,
        qrels,
        rankings,
        coverage,
        job.config,
        implementation,
        model=next(iter(models), None),
        candidate=job.candidate_identity,
        input_results=tuple(sha256_file(Path(path)) for path in job.input_results),
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "用法：python -m personal_agent.infra.retrieval_experiment.worker JOB_JSON"
        )
    job = JOB_ADAPTER.validate_python(read_json(Path(sys.argv[1])))
    result_path = run_job(job)
    print(
        json.dumps(
            {"status": "completed", "result_path": str(result_path)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
