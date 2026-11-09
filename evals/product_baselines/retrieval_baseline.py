"""Initial world and conservative failure grading for retrieval E1/P1 admission.

This T0 grader can establish missing delivery. It cannot qualify a target or
accept an unexpected complete result without the independent grader in Spec §6.
"""
from __future__ import annotations

from personal_agent.infra.model_providers import build_provider_policy

from dataclasses import dataclass
import argparse
import csv
from hashlib import sha256
import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.retrieval_experiment.models import ExperimentLimits
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tmp/retrieval-experiment-scenario-20261018/sources"
MODEL = ROOT / ".tmp/retrieval-experiment-tool-20261020/model"
DEADLINE_SECONDS = 900
OWNER = AuthenticatedPrincipal(tenant_id="personal-agent", user_id="retrieval-experiment-20261020")


@dataclass(frozen=True)
class RetrievalScenario:
    case_id: str
    key: Literal["e1", "p1"]
    request: str


SCENARIOS = (
    RetrievalScenario("RETRIEVAL-EXPERIMENT-001", "e1", "请用提供的 SciFact 材料和获准环境，比较 BM25 与向量检索，分析实际错例，判断是否需要组合；有必要时再做验证。用 train 分析和选择配置，冻结后在 test 上比较基线与选中方案。给我完整的比较报告，说明实际结果、选择依据和限制。按给定预算自行推进，缺关键条件再问我；先不要修改当前知识库。"),
    RetrievalScenario("RETRIEVAL-EXPERIMENT-PROGRAM-001", "p1", "请用提供的数据和两种检索基线，自己实现并实测一个组合检索方案。根据开发结果选定方案，冻结后在保留集评测；根据实际运行的程序和结果说明你的选择与限制，不要改当前知识库。"),
)


class FileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    filename: str
    sha256: str
    bytes: int
    resource_ref: ResourceRef


class RetrievalWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal: AuthenticatedPrincipal = OWNER
    files: tuple[FileIdentity, ...]
    environment_ref: ResourceRef
    environment_text: str
    environment_sha256: str
    model_files: dict[str, str]
    split_audit: dict[str, int | str]
    user_input: str
    conversation_id: str
    interaction_run_ref: str
    test_qrels_exposed: Literal[False] = False


class BaselineOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivered: Literal[False] = False
    result: Literal["failed", "inconclusive"]
    reason: str
    generated_artifact_count: int
    missing_deliverables: tuple[str, ...]
    artifact_inventory: tuple[dict[str, str], ...]
    model_calls_completed: int
    material_consumed: bool
    earliest_boundary: str
    target_grader_qualified: Literal[False] = False


def prepare_world(settings: Settings, scenario: RetrievalScenario, *, limits: ExperimentLimits) -> RetrievalWorld:
    """Seed only authorized initial facts through the existing Artifact owner."""
    artifacts = ArtifactService(settings, logging.getLogger(__name__), provider_policy=build_provider_policy(base_url=settings.openai.base_url, provider=settings.openai.provider))
    split_queries = {}
    split_audit = {}
    for split, expected in (("train", 809), ("test", 300)):
        path = SOURCE / f"BeIR-scifact-qrels/{split}.tsv"
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        query_ids = {row["query-id"] for row in rows}
        if len(query_ids) != expected:
            raise ValueError(f"{split}真实标注查询覆盖与Spec不符")
        split_queries[split] = query_ids
        split_audit[f"{split}_queries"] = len(query_ids)
        split_audit[f"{split}_qrels_sha256"] = sha256(path.read_bytes()).hexdigest()
    if split_queries["train"] & split_queries["test"]:
        raise ValueError("开发与保留查询不应有交集")
    split_audit["query_overlap"] = 0
    files = []
    for relative, mime in (
        ("BeIR-scifact/corpus.parquet", "application/vnd.apache.parquet"),
        ("BeIR-scifact/queries.parquet", "application/vnd.apache.parquet"),
        ("BeIR-scifact-qrels/train.tsv", "text/tab-separated-values"),
    ):
        path = SOURCE / relative
        data = path.read_bytes()
        ref = artifacts.save_upload(filename=path.name, content_type=mime, file_bytes=data,
                                    uploads_dir=settings.data_dir / "uploads", principal=OWNER, owner=OWNER)
        record, actual = artifacts.read_upload(ref, principal=OWNER, owner=OWNER)
        if actual != data or record.size_bytes != len(data):
            raise ValueError("初始原件读取与来源不一致")
        files.append(FileIdentity(filename=relative, sha256=sha256(data).hexdigest(),
                                  bytes=len(data), resource_ref=ref))
    required_model_files = ("model.safetensors", "tokenizer.json", "config.json", "modules.json", "1_Pooling/config.json")
    model_files = {name: sha256((MODEL / name).read_bytes()).hexdigest() for name in required_model_files}
    budget = settings.interaction_loop
    environment = (
        "本次委托的许可材料与环境\n"
        "材料来源为官方BeIR/SciFact镜像；同一5183篇文档库；train完整809条已标注查询用于开发，test完整300条用于冻结后独立评测。"
        "英文原件保持原文，中文报告。指标为nDCG@10与Recall@100，不要求超过BM25，不将结果外推中文私人知识库。\n"
        "已提供corpus/queries Parquet与开发qrels TSV合法附件；test标注仅供受信评分端，生成模型无读取权限。\n"
        "获准执行环境已有固定BEIR ef83d29307061c65d04b035b4f4e7c18bd8374af、Elasticsearch7.17.28和"
        "sentence-transformers/all-MiniLM-L6-v2 revision1110a243fdf4706b3f48f1d95db1a4f5529b4d41，离线使用。"
        "允许在本次隔离实验资源运行基线、必要组合及候选；固定参考RRF常数60，不限定你自己的组合程序。"
        "依赖已准备，不需下载、不允许动态安装或宿主Shell。\n"
        "原件只读，仅写本任务实验产物和专用实验索引，不修改当前知识库，不访问其他用户资源。"
        "可按实际结果选择方案与停止，不提供预生成排名、候选源码、胜出配置或错例。\n"
        f"预算：每例{budget.max_model_turns}模型轮、{budget.max_tool_calls}工具、"
        f"{budget.max_agent_calls}委派上限、{budget.max_total_tokens}累计tokens、"
        f"{limits.run_timeout_seconds:g}秒总截止；委派不要求使用。"
        f"实验累计执行额度{limits.max_execution_seconds:g}秒。"
        f"固定实验单作业上限{limits.worker_timeout_seconds:g}秒，仍受任务剩余时间和累计执行额度约束，"
        f"候选默认{limits.candidate_timeout_seconds:g}秒。候选隔离限制{limits.candidate_memory_mb}MiB、"
        f"{limits.candidate_cpus:g}CPU、{limits.candidate_pids}进程、{limits.candidate_scratch_mb}MiB临时空间、"
        f"{limits.stdout_bytes // (1024 * 1024)}MiB输出。\n"
        "当前知识库不得修改。缺关键条件可说明；没有实际执行或文件时不得宣称完整完成。\n"
        "授权原件引用：\n" + json.dumps([item.model_dump(mode="json") for item in files], ensure_ascii=False)
    )
    if len(environment) > 11000:
        raise ValueError("环境清单不得被inspect_upload截断")
    ref = artifacts.save_upload(filename="environment.txt", content_type="text/plain", file_bytes=environment.encode("utf-8"),
                                uploads_dir=settings.data_dir / "uploads", principal=OWNER, owner=OWNER)
    inspected = artifacts.inspect_upload(resource_ref=ref, principal=OWNER, owner=OWNER)
    if environment not in inspected["text"]:
        raise ValueError("环境清单未能原文读取")
    user_input = scenario.request + "\n\n材料和许可环境说明见附件，按需读取：" + ref.model_dump_json()
    if len(user_input) > 20000:
        raise ValueError("输入超出正式消息长度")
    return RetrievalWorld(files=tuple(files), environment_ref=ref, environment_text=environment,
                          environment_sha256=sha256(environment.encode("utf-8")).hexdigest(), model_files=model_files,
                          split_audit=split_audit,
                          user_input=user_input, conversation_id=f"retrieval-{scenario.key}-20261020",
                          interaction_run_ref=f"irun_retrieval_{scenario.key}_20261020")


def grade_missing_delivery(*, trace: dict, data_dir: Path, model_calls_completed: int,
                           entry_error: str | None, program_required: bool = False) -> BaselineOutcome:
    """Inspect actual answer and execution progress; artifact inventory is diagnostic only."""
    inventory = []
    for sidecar in (data_dir / "generated_artifacts").glob("artg_*.json"):
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        ref = ResourceRef.model_validate(record["resource_ref"])
        if ref.owner != OWNER:
            continue
        settings = Settings(data_dir=data_dir)
        service = ArtifactService(settings, provider_policy=build_provider_policy(
            base_url=settings.openai.base_url, provider=settings.openai.provider,
        ))
        stored, content = service.read_upload(ref, principal=OWNER, owner=OWNER)
        kind = str(record.get("artifact_kind", ""))
        mime = stored.content_type or ""
        filename = stored.filename.lower()
        inventory.append({"resource_id": ref.resource_id, "kind": kind, "mime": mime,
                          "filename": filename, "sha256": sha256(content).hexdigest()})
    receipts = [item for item in trace.get("experiment_records", ())
                if item.get("receipt") and item["receipt"]["status"] == "succeeded"]
    progress = {item["receipt"]["operation"] for item in receipts}
    missing_items = []
    if not trace.get("final_message") or trace["final_message"].get("disposition") != "answer":
        missing_items.append("answer_final")
    for operation in ("run_development", "freeze", "evaluate_final"):
        if operation not in progress:
            missing_items.append(operation)
    if program_required and not any(
        item.get("command") and item["command"]["workload"].get("config", {}).get("method") == "candidate"
        and item.get("execution") and item["execution"]["status"] == "succeeded" for item in receipts
    ):
        missing_items.append("candidate_execution")
    missing = tuple(missing_items)
    observations = [item for item in trace.get("inputs", ()) if item.get("kind") == "tool_result"]
    material_consumed = any(item.get("capability_id") == "inspect_artifact" and item.get("status") == "succeeded"
                            for item in observations)
    if entry_error or model_calls_completed == 0:
        result, boundary, reason = "inconclusive", "environment_or_model", "正式入口失败或没有完整真实模型响应；不能作为缺能力准入。"
    elif missing:
        result, reason = "failed", "研究回答或必要实际执行缺失：" + "、".join(missing) + "；不以下载、打包或文件数量判定Agent能力。"
        boundary = "capability_or_material_consumption"
    else:
        result, boundary, reason = "inconclusive", "agent_result_requires_review", "已有回答及执行进展，须核对真实结果消费、决策依据和适用语义；不以步骤完成、文件存在或下载成功宣称Agent能力通过。"
    return BaselineOutcome(result=result, reason=reason, generated_artifact_count=len(inventory),
                           missing_deliverables=missing, artifact_inventory=tuple(inventory),
                           model_calls_completed=model_calls_completed, material_consumed=material_consumed,
                           earliest_boundary=boundary)


def main() -> None:
    """Prepare and validate actual initial files without launching app or model."""
    parser = argparse.ArgumentParser(description="E1/P1真实材料和正式请求预检；零模型、零数据库写入")
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=False)
    from personal_agent.adapters.web.routes.conversation import ConversationTurnRequest
    import pyarrow.parquet as pq

    corpus = pq.read_table(SOURCE / "BeIR-scifact/corpus.parquet")
    queries = pq.read_table(SOURCE / "BeIR-scifact/queries.parquet")
    if corpus.num_rows != 5183 or queries.num_rows != 1109:
        raise ValueError("初始数据规模偏离唯一Spec")
    summary = {"model_calls": 0, "http_calls": 0, "database_writes": 0, "scenarios": []}
    settings = Settings.from_env()
    for scenario in SCENARIOS:
        sample = args.output_root / scenario.key
        world = prepare_world(
            settings.model_copy(update={"data_dir": sample / "server-data"}), scenario,
            limits=ExperimentLimits(run_timeout_seconds=DEADLINE_SECONDS, max_execution_seconds=DEADLINE_SECONDS),
        )
        body = ConversationTurnRequest.model_validate({
            "user_id": OWNER.user_id, "conversation_id": world.conversation_id,
            "interaction_run_ref": world.interaction_run_ref, "interaction_mode": "auto",
            "messages": [{"role": "user", "content": world.user_input}],
        })
        (sample / "world.json").write_text(world.model_dump_json(indent=2), encoding="utf-8")
        (sample / "request.json").write_text(body.model_dump_json(indent=2), encoding="utf-8")
        names = {path.name for path in (sample / "server-data/uploads").iterdir()}
        if any("test.tsv" in name for name in names):
            raise ValueError("生成侧不应有test标注")
        summary["scenarios"].append({"case_id": scenario.case_id, "original_request_preserved": world.user_input.startswith(scenario.request),
                                     "request_chars": len(world.user_input), "environment_chars": len(world.environment_text),
                                     "file_count": len(world.files), "test_qrels_exposed": False,
                                     "world_digest": sha256(world.model_dump_json().encode()).hexdigest()})
    (args.output_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
