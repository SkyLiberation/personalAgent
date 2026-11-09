"""固定worker的外层文件作业协议。"""

from __future__ import annotations
from typing import Annotated, Literal
from pydantic import Field, TypeAdapter
from personal_agent.application.retrieval_experiment.contracts import (
    StrictModel,
    Identifier,
    BM25Config,
    DenseConfig,
    RRFConfig,
    CandidateConfig,
    CandidateIdentity,
    ElasticsearchIdentity,
)


class BaselineJob(StrictModel):
    mode: Literal["baseline"]
    manifest_path: Identifier
    output_dir: Identifier
    config: Annotated[BM25Config | DenseConfig, Field(discriminator="method")]
    image_id: Identifier
    batch_size: Annotated[int, Field(strict=True, ge=1, le=256)] = 128
    es_endpoint: Identifier | None = None
    index_name: Identifier | None = None
    model_path: Identifier | None = None
    model_revision: Identifier | None = None
    expected_elasticsearch: ElasticsearchIdentity | None = None


class RRFJob(StrictModel):
    mode: Literal["rrf"]
    manifest_path: Identifier
    output_dir: Identifier
    config: RRFConfig
    input_results: Annotated[tuple[Identifier, ...], Field(min_length=2)]
    image_id: Identifier


class ScoreJob(StrictModel):
    mode: Literal["score"]
    manifest_path: Identifier
    output_dir: Identifier
    image_id: Identifier
    input_result: Identifier | None = None
    candidate_rankings_path: Identifier | None = None
    config: CandidateConfig | None = None
    candidate_identity: CandidateIdentity | None = None
    input_results: tuple[Identifier, ...] = ()


Job = Annotated[BaselineJob | RRFJob | ScoreJob, Field(discriminator="mode")]
JOB_ADAPTER = TypeAdapter(Job)
