"""受信控制端、检索和评分之间唯一的文件契约。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

import hashlib
import json
import math
from typing import Annotated, Literal, Mapping, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

BEIR_COMMIT = "ef83d29307061c65d04b035b4f4e7c18bd8374af"
Identifier = Annotated[str, StringConstraints(strict=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", strict=True)]
Depth = Annotated[int, Field(strict=True, ge=100, le=1000)]
Split = Literal["train", "test"]
Rankings: TypeAlias = dict[str, dict[str, float]]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BM25Config(StrictModel):
    method: Literal["bm25"]
    retrieve_k: Depth


class DenseConfig(StrictModel):
    method: Literal["dense"]
    retrieve_k: Depth
    score_function: Literal["cos_sim"] = "cos_sim"


class RRFConfig(StrictModel):
    method: Literal["rrf"]
    retrieve_k: Depth
    rrf_constant: Literal[60] = 60


class CandidateConfig(StrictModel):
    method: Literal["candidate"]
    retrieve_k: Depth


ExperimentConfig = Annotated[
    BM25Config | DenseConfig | RRFConfig | CandidateConfig,
    Field(discriminator="method"),
]
CONFIG_ADAPTER = TypeAdapter(ExperimentConfig)


class DatasetManifest(StrictModel):
    schema_version: Literal[1] = 1
    dataset_id: Digest
    split_id: Digest
    split: Split
    query_ids: tuple[Identifier, ...]
    document_ids: tuple[Identifier, ...]
    corpus_count: Annotated[int, Field(strict=True, gt=0)]
    query_count: Annotated[int, Field(strict=True, gt=0)]
    source_sha256: dict[Literal["corpus", "queries", "qrels"], Digest]
    artifact_sha256: dict[Literal["corpus.json", "queries.json", "qrels.json"], Digest]


class DatasetBinding(StrictModel):
    dataset_id: Digest
    split_id: Digest
    split: Split


class QueryExecution(StrictModel):
    query_id: Identifier
    status: Literal["completed"] = "completed"
    hit_count: Annotated[int, Field(strict=True, ge=0)]
    backend: Literal["bm25", "dense", "rrf", "candidate"]


class Coverage(DatasetBinding):
    retrieve_k: Depth
    queries: tuple[QueryExecution, ...]


class Metrics(StrictModel):
    ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    recall_at_100: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    query_count: Annotated[int, Field(strict=True, gt=0)]


class QueryMetrics(StrictModel):
    ndcg_at_10: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    recall_at_100: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ElasticsearchIdentity(StrictModel):
    version_number: Identifier
    build_hash: Identifier
    lucene_version: Identifier
    effective_index_settings_digest: Digest
    mapping_digest: Digest


class ImplementationIdentity(StrictModel):
    beir_commit: Literal[BEIR_COMMIT] = BEIR_COMMIT
    tool_sha256: dict[Identifier, Digest]
    packages: dict[Identifier, Identifier]
    image_id: Identifier
    elasticsearch: ElasticsearchIdentity | None = None


class ModelIdentity(StrictModel):
    model_id: Literal["sentence-transformers/all-MiniLM-L6-v2"] = (
        "sentence-transformers/all-MiniLM-L6-v2"
    )
    revision: Identifier
    sha256: Digest


class CandidateIdentity(StrictModel):
    source_sha256: Digest
    config_sha256: Digest
    image_id: Identifier
    job_id: Identifier
    stdout_sha256: Digest
    timeout_seconds: Annotated[float, Field(gt=0, le=1200, allow_inf_nan=False)]


class ArtifactFile(StrictModel):
    path: Literal["rankings.json", "coverage.json", "metrics.json", "per_query.json"]
    sha256: Digest


class ResultArtifacts(StrictModel):
    rankings: ArtifactFile
    coverage: ArtifactFile
    metrics: ArtifactFile
    per_query: ArtifactFile


class ExperimentResult(StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["completed"] = "completed"
    config: ExperimentConfig
    dataset: DatasetBinding
    implementation: ImplementationIdentity
    model: ModelIdentity | None = None
    candidate: CandidateIdentity | None = None
    input_results: tuple[Digest, ...] = ()
    artifacts: ResultArtifacts
    metrics: Metrics


def canonical_digest(value: object) -> str:
    content = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def dataset_binding(manifest: DatasetManifest) -> DatasetBinding:
    return DatasetBinding(
        dataset_id=manifest.dataset_id, split_id=manifest.split_id, split=manifest.split
    )


def validate_rankings(
    raw: object, manifest: DatasetManifest, retrieve_k: int, *, truncate: bool = False,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> Rankings:
    """统一排序；仅检索器可裁剪 backend 的额外一个 self-match 候选。"""
    if not isinstance(raw, Mapping) or set(raw) != set(manifest.query_ids):
        raise ValueError(prompts.render('experiment_rankings.coverage'))
    known_documents = set(manifest.document_ids)
    rankings: Rankings = {}
    for qid in manifest.query_ids:
        scores = raw[qid]
        if not isinstance(scores, Mapping):
            raise ValueError(prompts.render('experiment_rankings.scores', query_id=qid))
        if len(scores) > retrieve_k + (1 if truncate else 0):
            raise ValueError(prompts.render('experiment_rankings.depth', query_id=qid))
        checked: dict[str, float] = {}
        for docid, score in scores.items():
            if not isinstance(docid, str) or docid not in known_documents:
                raise ValueError(prompts.render('experiment_rankings.document', query_id=qid, document_id=docid))
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise ValueError(prompts.render('experiment_rankings.finite_score', query_id=qid, document_id=docid))
            if docid != qid:
                checked[docid] = float(score)
        ordered = sorted(
            checked.items(), key=lambda pair: (pair[1], pair[0]), reverse=True
        )
        rankings[qid] = dict(ordered[:retrieve_k])
    return rankings


class InputRecipe(StrictModel):
    config: ExperimentConfig
    implementation: ImplementationIdentity
    model: ModelIdentity | None


class FrozenExperiment(StrictModel):
    schema_version: Literal[1] = 1
    dataset_id: Digest
    development_split_id: Digest
    development_result_sha256: Digest
    development_query_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    recipe: InputRecipe
    inputs: tuple[InputRecipe, ...]
    program_sha256: Digest | None = None
    program_config_sha256: Digest | None = None
    candidate_image_id: Identifier | None = None
    candidate_timeout_seconds: Annotated[float, Field(gt=0, le=1200)] | None = None
