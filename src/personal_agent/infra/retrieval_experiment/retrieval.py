"""原件准备及固定 BEIR 检索；逐查询覆盖来自真实后端执行。"""

from __future__ import annotations

import csv
import importlib.metadata
import importlib.util
import math
import os
import re
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import Field, StrictStr, TypeAdapter

from .contracts import (
    BaselineJob,
)
from .file_io import (
    read_json,
    sha256_file,
    write_json,
)
from personal_agent.application.retrieval_experiment.contracts import (
    Coverage,
    DatasetManifest,
    ElasticsearchIdentity,
    ImplementationIdentity,
    ModelIdentity,
    QueryExecution,
    Rankings,
    Split,
    StrictModel,
    canonical_digest,
    dataset_binding,
    validate_rankings,
)


class CorpusDocument(StrictModel):
    title: StrictStr
    text: StrictStr


class SourceRow(CorpusDocument):
    id: Annotated[str, Field(alias="_id", strict=True, min_length=1)]


CORPUS_ADAPTER = TypeAdapter(dict[str, CorpusDocument])
QUERIES_ADAPTER = TypeAdapter(dict[str, StrictStr])
QRELS_ADAPTER = TypeAdapter(
    dict[str, dict[str, Annotated[int, Field(strict=True, ge=0)]]]
)


def _read_parquet(path: Path) -> dict[str, SourceRow]:
    import pyarrow.parquet as parquet

    rows: dict[str, SourceRow] = {}
    for raw in parquet.read_table(path).to_pylist():
        row = SourceRow.model_validate(raw)
        if row.id in rows:
            raise ValueError(f"原件存在重复 ID：{row.id}")
        rows[row.id] = row
    if not rows:
        raise ValueError(f"原件为空：{path}")
    return rows


def prepare_data(
    corpus_path: str | Path,
    queries_path: str | Path,
    qrels_path: str | Path,
    split: Split,
    output_dir: str | Path,
) -> Path:
    """只接受显式 split 的完整原始 qrels；不截取查询或预设数据量。"""
    if split not in ("train", "test"):
        raise ValueError("split 必须为 train 或 test")
    corpus_path, queries_path, qrels_path = map(
        Path, (corpus_path, queries_path, qrels_path)
    )
    corpus_rows = _read_parquet(corpus_path)
    query_rows = _read_parquet(queries_path)
    qrels: dict[str, dict[str, int]] = {}
    with qrels_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        if reader.fieldnames != ["query-id", "corpus-id", "score"]:
            raise ValueError("qrels 必须使用 query-id、corpus-id、score 三列 TSV")
        for row in reader:
            qid, docid, label = row["query-id"], row["corpus-id"], row["score"]
            if None in row or qid not in query_rows or docid not in corpus_rows:
                raise ValueError("qrels 行损坏或引用未知查询／文档")
            if not isinstance(label, str) or not re.fullmatch(r"0|[1-9][0-9]*", label):
                raise ValueError("相关性标签必须为非负整数")
            judgments = qrels.setdefault(qid, {})
            if docid in judgments:
                raise ValueError(f"qrels 存在重复查询／文档对：{qid}/{docid}")
            judgments[docid] = int(label)
    if not qrels or any(not any(labels.values()) for labels in qrels.values()):
        raise ValueError("每个评测查询必须至少有一个正相关性标注")
    corpus = {
        docid: row.model_dump(exclude={"id"})
        for docid, row in sorted(corpus_rows.items())
    }
    queries = {qid: query_rows[qid].text for qid in sorted(qrels)}
    qrels = {qid: dict(sorted(qrels[qid].items())) for qid in queries}
    source_sha256 = {
        "corpus": sha256_file(corpus_path),
        "queries": sha256_file(queries_path),
        "qrels": sha256_file(qrels_path),
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    for filename, content in (
        ("corpus.json", corpus),
        ("queries.json", queries),
        ("qrels.json", qrels),
    ):
        write_json(output / filename, content)
    artifact_sha256 = {
        filename: sha256_file(output / filename)
        for filename in ("corpus.json", "queries.json", "qrels.json")
    }
    dataset_id = canonical_digest(
        {key: source_sha256[key] for key in ("corpus", "queries")}
    )
    split_id = canonical_digest(
        {
            "dataset_id": dataset_id,
            "split": split,
            "qrels": source_sha256["qrels"],
            "query_ids": list(queries),
            "artifact_sha256": artifact_sha256,
        }
    )
    manifest = DatasetManifest(
        dataset_id=dataset_id,
        split_id=split_id,
        split=split,
        query_ids=tuple(queries),
        document_ids=tuple(corpus),
        corpus_count=len(corpus),
        query_count=len(queries),
        source_sha256=source_sha256,
        artifact_sha256=artifact_sha256,
    )
    write_json(output / "manifest.json", manifest)
    return output / "manifest.json"


def load_dataset(
    manifest_path: str | Path,
) -> tuple[
    DatasetManifest,
    dict[str, dict[str, str]],
    dict[str, str],
    dict[str, dict[str, int]],
]:
    path = Path(manifest_path)
    manifest = DatasetManifest.model_validate(read_json(path))
    expected_files = {"corpus.json", "queries.json", "qrels.json"}
    if set(manifest.artifact_sha256) != expected_files or set(
        manifest.source_sha256
    ) != {"corpus", "queries", "qrels"}:
        raise ValueError("数据 manifest 的原件／工件身份集合不完整")
    for name, expected in manifest.artifact_sha256.items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"数据工件摘要不一致：{name}")
    corpus_models = CORPUS_ADAPTER.validate_python(
        read_json(path.parent / "corpus.json")
    )
    corpus = {docid: document.model_dump() for docid, document in corpus_models.items()}
    queries = QUERIES_ADAPTER.validate_python(read_json(path.parent / "queries.json"))
    qrels = QRELS_ADAPTER.validate_python(read_json(path.parent / "qrels.json"))
    if (
        len(set(manifest.query_ids)) != manifest.query_count
        or len(set(manifest.document_ids)) != manifest.corpus_count
        or set(queries) != set(manifest.query_ids)
        or set(qrels) != set(queries)
        or set(corpus) != set(manifest.document_ids)
        or any(not identifier for identifier in (*corpus, *queries))
        or any(
            not any(labels.values()) or not set(labels) <= set(corpus)
            for labels in qrels.values()
        )
    ):
        raise ValueError("数据身份、完整查询集合或标注不一致")
    dataset_id = canonical_digest(
        {key: manifest.source_sha256[key] for key in ("corpus", "queries")}
    )
    split_id = canonical_digest(
        {
            "dataset_id": dataset_id,
            "split": manifest.split,
            "qrels": manifest.source_sha256["qrels"],
            "query_ids": list(manifest.query_ids),
            "artifact_sha256": manifest.artifact_sha256,
        }
    )
    if dataset_id != manifest.dataset_id or split_id != manifest.split_id:
        raise ValueError("数据 manifest 身份摘要不一致")
    return manifest, corpus, queries, qrels


def implementation_identity(image_id: str) -> ImplementationIdentity:
    versions = {}
    for name in (
        "beir",
        "elasticsearch",
        "sentence-transformers",
        "torch",
        "pytrec-eval-terrier",
        "pydantic",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    package_root = Path(__file__).resolve().parents[2]
    sources = (
        "application/retrieval_experiment/contracts.py",
        "application/retrieval_experiment/rules.py",
        "infra/retrieval_experiment/contracts.py",
        "infra/retrieval_experiment/file_io.py",
        "infra/retrieval_experiment/retrieval.py",
        "infra/retrieval_experiment/scoring.py",
        "infra/retrieval_experiment/worker.py",
    )
    return ImplementationIdentity(
        image_id=image_id,
        packages=versions,
        tool_sha256={
            "src/personal_agent/" + name: sha256_file(package_root / name)
            for name in sources
        },
    )


def _verify_beir_source(module_name: str, expected: str) -> None:
    spec = importlib.util.find_spec(module_name)
    if (
        spec is None
        or spec.origin is None
        or sha256_file(Path(spec.origin)) != expected
    ):
        raise ValueError(f"BEIR 实现不匹配已审计源码：{module_name}")


class _ObservedElasticsearch:
    """只观察实际响应，不用排名字典推断执行完成。"""

    def __init__(self, client: Any, query_ids: tuple[str, ...], retrieve_k: int):
        self.client = client
        self.query_ids = query_ids
        self.retrieve_k = retrieve_k
        self.executions: list[QueryExecution] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def bulk(self, *args: Any, **kwargs: Any) -> Any:
        response = self.client.bulk(*args, **kwargs)
        if response.get("errors") is not False or not isinstance(
            response.get("items"), list
        ):
            raise ValueError("Elasticsearch bulk 执行错误或响应不完整")
        for item in response["items"]:
            if len(item) != 1:
                raise ValueError("Elasticsearch bulk item 不完整")
            outcome = next(iter(item.values()))
            if outcome.get("error") or not 200 <= outcome.get("status", 0) < 300:
                raise ValueError("Elasticsearch bulk item 执行失败")
        return response

    def msearch(self, *args: Any, **kwargs: Any) -> Any:
        body = kwargs.get("body")
        if not isinstance(body, list) or len(body) % 2:
            raise ValueError("BEIR msearch 请求不完整")
        batch_size = len(body) // 2
        if any(request.get("size") != self.retrieve_k + 1 for request in body[1::2]):
            raise ValueError("实际 Elasticsearch 检索深度与配置不同")
        response = self.client.msearch(*args, **kwargs)
        responses = response.get("responses")
        if not isinstance(responses, list) or len(responses) != batch_size:
            raise ValueError("Elasticsearch 未返回本批全部查询")
        offset = len(self.executions)
        if offset + batch_size > len(self.query_ids):
            raise ValueError("Elasticsearch 产生了额外查询执行")
        for qid, item in zip(
            self.query_ids[offset : offset + batch_size], responses, strict=True
        ):
            shards = item.get("_shards", {})
            if (
                item.get("error")
                or item.get("timed_out") is not False
                or shards.get("failed") != 0
                or not isinstance(shards.get("total"), int)
                or shards["total"] < 1
                or shards.get("successful") != shards["total"]
                or "hits" not in item
                or not isinstance(item["hits"].get("hits"), list)
            ):
                raise ValueError(f"Elasticsearch 查询未完整完成：{qid}")
            hits = item["hits"]["hits"]
            if len(hits) > self.retrieve_k + 1:
                raise ValueError("Elasticsearch 返回命中超额")
            identifiers = [hit.get("_id") for hit in hits]
            if len(set(identifiers)) != len(identifiers) or any(
                not isinstance(docid, str) for docid in identifiers
            ):
                raise ValueError("Elasticsearch 命中 ID 缺失或重复")
            for hit in hits:
                score = hit.get("_score")
                if (
                    isinstance(score, bool)
                    or not isinstance(score, (int, float))
                    or not math.isfinite(score)
                ):
                    raise ValueError("Elasticsearch 返回非有限分数")
            self.executions.append(
                QueryExecution(
                    query_id=qid,
                    hit_count=min(
                        self.retrieve_k, sum(docid != qid for docid in identifiers)
                    ),
                    backend="bm25",
                )
            )
        return response


def _elasticsearch_version(client: Any) -> dict[str, str]:
    version = client.info()["version"]
    identity = {
        "version_number": version["number"],
        "build_hash": version["build_hash"],
        "lucene_version": version["lucene_version"],
    }
    if any(not isinstance(value, str) or not value for value in identity.values()):
        raise ValueError("Elasticsearch 版本响应不完整")
    return identity


def _merged_settings(
    defaults: dict[str, object], configured: dict[str, object]
) -> dict[str, object]:
    merged = dict(defaults)
    for key, value in configured.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merged_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _elasticsearch_identity(
    client: Any, index_name: str, version: dict[str, str]
) -> ElasticsearchIdentity:
    response = client.indices.get_settings(
        index=index_name, include_defaults=True, flat_settings=False
    )[index_name]
    configured = response["settings"]["index"]
    defaults = response.get("defaults", {}).get("index", {})
    effective = _merged_settings(defaults, configured)
    # 排除索引名、UUID、创建时间等每次建索引都会变化的服务元数据。
    settings = {
        "analysis": effective.get("analysis", {}),
        "similarity": effective.get("similarity", {}),
        "number_of_shards": effective["number_of_shards"],
        "number_of_replicas": effective["number_of_replicas"],
    }
    mapping = client.indices.get_mapping(index=index_name)[index_name]["mappings"]
    return ElasticsearchIdentity(
        **version,
        effective_index_settings_digest=canonical_digest(settings),
        mapping_digest=canonical_digest(mapping),
    )


def _bm25(
    job: BaselineJob,
    manifest: DatasetManifest,
    corpus: dict[str, dict[str, str]],
    queries: dict[str, str],
) -> tuple[Rankings, tuple[QueryExecution, ...], ElasticsearchIdentity]:
    _verify_beir_source(
        "beir.retrieval.search.lexical.bm25_search",
        "f0c056b8145f6104b7f23be34fdeb3f2926fc9ae5b58eb8b6709b3f0b43cc8d0",
    )
    _verify_beir_source(
        "beir.retrieval.search.lexical.elastic_search",
        "a75382710c9ace81e7878557ce47ec2753e5e300907d8f79d14199674dec9e21",
    )
    from beir.retrieval.search.lexical import BM25Search

    endpoint = urlparse(job.es_endpoint or "")
    if (
        endpoint.scheme != "http"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
    ):
        raise ValueError("BM25 需要显式、无凭据的独立 Elasticsearch HTTP endpoint")
    if not job.index_name or not re.fullmatch(
        r"retrieval-experiment-[a-z0-9-]{1,100}", job.index_name
    ):
        raise ValueError("BM25 索引必须属于 retrieval-experiment- 独立命名空间")
    if job.model_path is not None or job.model_revision is not None:
        raise ValueError("BM25 作业不能携带模型参数")

    class CheckedBM25(BM25Search):
        # The pinned BEIR BaseSearch makes these dense-only operations abstract;
        # its BM25 implementation only implements online search.
        def encode(self, *args: object, **kwargs: object) -> None:
            raise ValueError("BM25 不支持独立向量编码")

        def search_from_files(self, *args: object, **kwargs: object) -> None:
            raise ValueError("BM25 不支持从向量文件检索")

        def index(self, documents: dict[str, dict[str, str]]) -> None:
            super().index(documents)
            self.es.es.indices.refresh(index=job.index_name)
            response = self.es.es.count(index=job.index_name)
            if (
                response.get("count") != manifest.corpus_count
                or response.get("_shards", {}).get("failed") != 0
            ):
                raise ValueError("Elasticsearch 索引文档总量或分片状态不一致")

    searcher = CheckedBM25(
        index_name=job.index_name,
        hostname=job.es_endpoint,
        initialize=False,
        number_of_shards=1,
        batch_size=job.batch_size,
        timeout=100,
        retry_on_timeout=False,
        sleep_for=0,
    )
    version = _elasticsearch_version(searcher.es.es)
    if job.expected_elasticsearch is not None and any(
        value != getattr(job.expected_elasticsearch, key)
        for key, value in version.items()
    ):
        raise ValueError("Elasticsearch 版本与冻结执行环境不一致")
    if searcher.es.es.indices.exists(index=job.index_name):
        raise ValueError("拒绝覆盖已存在的实验索引")
    observed = _ObservedElasticsearch(
        searcher.es.es, tuple(queries), job.config.retrieve_k
    )
    searcher.es.es = observed
    searcher.es.create_index()
    if not observed.indices.exists(index=job.index_name):
        raise ValueError("Elasticsearch 建索引失败")
    backend = _elasticsearch_identity(observed, job.index_name, version)
    if job.expected_elasticsearch is not None and backend != job.expected_elasticsearch:
        raise ValueError("Elasticsearch 实际索引设置或 mapping 与冻结执行环境不一致")
    searcher.initialize = True
    raw = searcher.search(corpus, queries, top_k=job.config.retrieve_k)
    if tuple(item.query_id for item in observed.executions) != tuple(queries):
        raise ValueError("BM25 未完整执行全部查询")
    # BEIR 对零命中不会创建结果键；只凭实际成功响应补回这些已完成查询。
    for execution in observed.executions:
        if execution.hit_count == 0:
            raw.setdefault(execution.query_id, {})
    rankings = validate_rankings(raw, manifest, job.config.retrieve_k, truncate=True)
    return rankings, tuple(observed.executions), backend


def _dense(
    job: BaselineJob,
    manifest: DatasetManifest,
    corpus: dict[str, dict[str, str]],
    queries: dict[str, str],
) -> tuple[Rankings, tuple[QueryExecution, ...], ModelIdentity]:
    if (
        not job.model_path
        or not job.model_revision
        or job.es_endpoint is not None
        or job.index_name is not None
        or job.expected_elasticsearch is not None
    ):
        raise ValueError(
            "dense 需要明确本地模型和 revision，不能携带 Elasticsearch 参数"
        )
    model_path = Path(job.model_path)
    if not model_path.is_dir():
        raise ValueError("模型必须是预置的本地目录")
    files = sorted(model_path.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("模型目录不能含符号链接")
    hashes = {
        path.relative_to(model_path).as_posix(): sha256_file(path)
        for path in files
        if path.is_file()
    }
    if not hashes or not any(
        name.endswith(".safetensors") or name.endswith("pytorch_model.bin")
        for name in hashes
    ):
        raise ValueError("本地模型权重未准备")
    identity = ModelIdentity(
        revision=job.model_revision, sha256=canonical_digest(hashes)
    )
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    _verify_beir_source(
        "beir.retrieval.models.sentence_bert",
        "e89a8d3be68a42a5dfedf5fbce48505dfdcf3cea812440369fa23cf0d57d97bd",
    )
    _verify_beir_source(
        "beir.retrieval.search.dense.exact_search",
        "4b7ee8e9c673dc14423ca25d3555716734319fcf2223ed9ca7899ed1144c08a2",
    )
    from beir.retrieval.models import SentenceBERT
    from beir.retrieval.search.dense import DenseRetrievalExactSearch

    model = SentenceBERT(
        str(model_path), device="cpu", local_files_only=True, trust_remote_code=False
    )
    searcher = DenseRetrievalExactSearch(
        model, batch_size=job.batch_size, show_progress_bar=False
    )
    # 固定 BEIR 在 cos_scores[1] 读取列数，单查询输入不能伪装成已支持。
    if len(queries) < 2:
        raise ValueError("固定 BEIR dense 实现至少需要两个查询")
    raw = searcher.search(
        corpus,
        queries,
        top_k=job.config.retrieve_k,
        score_function="cos_sim",
        return_sorted=True,
    )
    rankings = validate_rankings(raw, manifest, job.config.retrieve_k)
    executions = tuple(
        QueryExecution(query_id=qid, hit_count=len(rankings[qid]), backend="dense")
        for qid in queries
    )
    return rankings, executions, identity


def retrieve_baseline(
    job: BaselineJob,
    manifest: DatasetManifest,
    corpus: dict[str, dict[str, str]],
    queries: dict[str, str],
) -> tuple[Rankings, Coverage, ModelIdentity | None, ElasticsearchIdentity | None]:
    if job.config.method == "bm25":
        rankings, executions, backend = _bm25(job, manifest, corpus, queries)
        model = None
    else:
        rankings, executions, model = _dense(job, manifest, corpus, queries)
        backend = None
    coverage = Coverage(
        **dataset_binding(manifest).model_dump(),
        retrieve_k=job.config.retrieve_k,
        queries=executions,
    )
    return rankings, coverage, model, backend
