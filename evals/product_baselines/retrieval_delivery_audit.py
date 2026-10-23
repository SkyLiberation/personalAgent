"""只读复核正式下载包及原始排名；与生产 scorer 独立计算 SciFact 指标。"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite, log2
from pathlib import Path
import struct
from typing import Literal
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.application.retrieval_experiment.contracts import Coverage, ExperimentResult, Metrics
from personal_agent.application.retrieval_experiment.delivery import ReproductionManifest, manifest_bytes
from personal_agent.application.retrieval_experiment.models import PublishedExperimentResult
from personal_agent.kernel.contracts.resource import ResourceRef

from .retrieval_baseline import SOURCE


class DownloadedResource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource: ArtifactResourceItem
    download_url: str = Field(min_length=1)
    download_path: str
    sha256: str
    bytes: int


class IndependentMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result_ref: ResourceRef
    wrapper_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["train", "test"]
    method: Literal["bm25", "dense", "rrf", "candidate"]
    query_count: int
    completed_queries: int
    ndcg_at_10: float
    recall_at_100: float
    maximum_per_query_delta: float


class OriginalRankingAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_class: Literal["offline_evaluation"] = "offline_evaluation"
    model_calls: Literal[0] = 0
    semantic_grader_qualified: Literal[False] = False
    clean_reproduction_executed: Literal[False] = False
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    qrels_sha256: dict[Literal["train", "test"], str]
    results: tuple[IndependentMetrics, ...]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("下载 JSON 存在重复键")
        value[key] = item
    return value


def _json(content: bytes) -> object:
    return json.loads(content, object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("非有限 JSON")))


def read_downloaded_bundle(directory: Path) -> tuple[ReproductionManifest, dict[ResourceRef, bytes]]:
    """Read only authenticated downloads, without using server storage paths."""
    records = TypeAdapter(tuple[DownloadedResource, ...]).validate_json((directory / "index.json").read_bytes())
    by_name: dict[str, tuple[ArtifactResourceItem, bytes]] = {}
    resources: set[ResourceRef] = set()
    for record in records:
        path = directory / record.download_path
        if path.parent != directory or path.is_symlink():
            raise ValueError("下载文件路径不能离开本目录")
        content = path.read_bytes()
        if (len(content) != record.bytes or len(content) != record.resource.size_bytes
                or sha256(content).hexdigest() != record.sha256
                or record.sha256 != record.resource.content_digest):
            raise ValueError("正式下载文件身份不一致")
        if record.resource.resource_ref in resources:
            raise ValueError("同一交付资源引用重复")
        resources.add(record.resource.resource_ref)
        if record.resource.filename in {"manifest.json", "reproduction.zip"}:
            if record.resource.filename in by_name:
                raise ValueError("交付的清单或 ZIP 角色重复")
            by_name[record.resource.filename] = (record.resource, content)
    if "manifest.json" not in by_name or "reproduction.zip" not in by_name:
        raise ValueError("用户交付缺 manifest 或 ZIP；文件存在不能替代完整交付")
    manifest = ReproductionManifest.model_validate(_json(by_name["manifest.json"][1]))
    if manifest_bytes(manifest) != by_name["manifest.json"][1]:
        raise ValueError("下载清单不是当前绑定清单的确切原字节")
    expected = {"manifest.json", *(item.relative_path for item in manifest.artifacts)}
    contents: dict[ResourceRef, bytes] = {}
    with ZipFile(BytesIO(by_name["reproduction.zip"][1])) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("ZIP 必须恰好包含同一清单及全部绑定文件")
        if bundle.read("manifest.json") != by_name["manifest.json"][1]:
            raise ValueError("独立下载的清单与 ZIP 内清单不同")
        for exported in manifest.artifacts:
            item = exported.resource
            info = bundle.getinfo(exported.relative_path)
            if info.file_size != item.size_bytes or info.flag_bits & 1:
                raise ValueError("ZIP 文件大小或加密状态不符合交付")
            content = bundle.read(exported.relative_path)
            if sha256(content).hexdigest() != item.content_digest:
                raise ValueError("ZIP 原文件摘要与清单不同")
            contents[item.resource_ref] = content
    return manifest, contents


def _qrels(path: Path) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            qid, document = row["query-id"], row["corpus-id"]
            grade = int(row["score"])
            if grade not in (0, 1):
                raise ValueError("此独立 SciFact 评分只声明二元相关性，不外推其他 gain 定义")
            if document in result.setdefault(qid, {}):
                raise ValueError("qrels 查询/文档对重复")
            result[qid][document] = grade
    return result


def audit_original_rankings(downloads: Path, qrels_root: Path) -> tuple[IndependentMetrics, ...]:
    manifest, contents = read_downloaded_bundle(downloads)
    result_refs = [
        (ref, PublishedExperimentResult.model_validate(_json(contents[ref])))
        for ref in dict.fromkeys(
            (*manifest.facts.development_result_refs, *manifest.facts.final_result_refs)
        )
    ]
    if not result_refs:
        raise ValueError("清单没有可核对的实际实验结果")
    if not set(manifest.facts.final_result_refs).issubset({ref for ref, _ in result_refs}):
        raise ValueError("冻结后的最终结果没有完整下载")
    manifests = {item.split: item for item in (manifest.environment.development, manifest.environment.final)}
    labels = {}
    for split, data in manifests.items():
        path = qrels_root / f"{split}.tsv"
        if sha256(path.read_bytes()).hexdigest() != data.source_sha256["qrels"]:
            raise ValueError("独立评分标注身份与冻结数据不同")
        labels[split] = _qrels(path)
        if set(labels[split]) != set(data.query_ids):
            raise ValueError("独立标注不包含完整查询集合")
    reports = []
    for ref, wrapper in result_refs:
        result = ExperimentResult.model_validate(_json(contents[wrapper.raw_result_ref]))
        if result.implementation.packages.get("pytrec-eval-terrier") != "0.5.11":
            raise ValueError("独立评分仅支持已核对的 pytrec-eval-terrier 0.5.11 排序口径")
        data = manifests[result.dataset.split]
        if result.dataset.dataset_id != data.dataset_id or result.dataset.split_id != data.split_id:
            raise ValueError("结果绑定其他数据或 split")
        role_refs = {"rankings": wrapper.rankings_ref, "coverage": wrapper.coverage_ref,
                     "metrics": wrapper.metrics_ref, "per_query": wrapper.per_query_ref}
        for role, resource_ref in role_refs.items():
            if sha256(contents[resource_ref]).hexdigest() != getattr(result.artifacts, role).sha256:
                raise ValueError("原始结果的文件摘要与实际下载文件不同")
        rankings = _json(contents[wrapper.rankings_ref])
        coverage = Coverage.model_validate(_json(contents[wrapper.coverage_ref]))
        metrics = Metrics.model_validate(_json(contents[wrapper.metrics_ref]))
        per_query = _json(contents[wrapper.per_query_ref])
        if not isinstance(rankings, dict) or set(rankings) != set(data.query_ids):
            raise ValueError("排名没有完整覆盖查询，不得补零或缩小分母")
        executions = {entry.query_id: entry for entry in coverage.queries}
        if (len(executions) != len(coverage.queries) or set(executions) != set(data.query_ids)
                or coverage.dataset_id != data.dataset_id or coverage.split_id != data.split_id
                or coverage.retrieve_k != result.config.retrieve_k or coverage.split != data.split):
            raise ValueError("缺失完整且同身份的逐查询执行事实")
        if not isinstance(per_query, dict) or set(per_query) != set(data.query_ids):
            raise ValueError("逐查询指标缺失")
        documents = set(data.document_ids)
        ndcgs, recalls, deltas = [], [], []
        for qid in data.query_ids:
            row = rankings[qid]
            if not isinstance(row, dict) or len(row) > result.config.retrieve_k or not set(row).issubset(documents):
                raise ValueError("排名文档或深度非法")
            if any(isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score) for score in row.values()):
                raise ValueError("排名分数必须为有限数值")
            execution = executions[qid]
            if execution.status != "completed" or execution.hit_count != len(row) or execution.backend != result.config.method:
                raise ValueError("排名不能替代实际执行，执行事实与排名不一致")
            # trec_eval 9.0.8 stores scores as C float before sorting and breaks
            # ties by descending docid; Python binary64 can split those ties.
            ordered = sorted(row, key=lambda document: (
                struct.unpack("=f", struct.pack("=f", row[document]))[0], document,
            ), reverse=True)
            relevant = {document for document, grade in labels[data.split][qid].items() if grade > 0}
            ideal = sum(1 / log2(position + 2) for position in range(min(10, len(relevant))))
            gain = sum(1 / log2(position + 2) for position, document in enumerate(ordered[:10]) if document in relevant)
            ndcg = gain / ideal if ideal else 0.0
            recall = len(set(ordered[:100]) & relevant) / len(relevant) if relevant else 0.0
            ndcgs.append(ndcg)
            recalls.append(recall)
            observed = per_query[qid]
            deltas.extend((abs(ndcg - observed["ndcg_at_10"]), abs(recall - observed["recall_at_100"])))
        actual = (round(sum(ndcgs) / data.query_count, 5), round(sum(recalls) / data.query_count, 5))
        if actual != (metrics.ndcg_at_10, metrics.recall_at_100) or metrics != result.metrics or metrics.query_count != data.query_count:
            raise ValueError("独立原始排名复算与发布指标不一致")
        if max(deltas, default=0.0) > 1e-12:
            raise ValueError("逐查询指标与独立计算不同")
        reports.append(IndependentMetrics(
            result_ref=ref, wrapper_sha256=sha256(contents[ref]).hexdigest(),
            raw_result_sha256=sha256(contents[wrapper.raw_result_ref]).hexdigest(),
            split=data.split, method=result.config.method,
            query_count=data.query_count, completed_queries=len(executions), ndcg_at_10=actual[0],
            recall_at_100=actual[1], maximum_per_query_delta=max(deltas, default=0.0),
        ))
    return tuple(reports)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--qrels-root", type=Path, default=SOURCE / "BeIR-scifact-qrels")
    args = parser.parse_args()
    reports = audit_original_rankings(args.downloads.resolve(), args.qrels_root.resolve())
    manifest, _ = read_downloaded_bundle(args.downloads.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(OriginalRankingAudit(
            manifest_sha256=sha256(manifest_bytes(manifest)).hexdigest(),
            qrels_sha256={split: sha256((args.qrels_root / f"{split}.tsv").read_bytes()).hexdigest()
                          for split in ("train", "test")}, results=reports,
        ).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
