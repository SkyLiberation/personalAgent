"""真实失败历史的非思考摘要与主决策接续；不执行模型提议的动作。"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
from typing import Literal

import httpx
from dotenv import load_dotenv

from evals.provider_diagnostics.python_result_analysis_models import (
    Digest, GroupPlan, Record, Usage,
)
from evals.provider_diagnostics.python_result_analysis_runtime import (
    branch_environment, branch_settings, build_branch_context,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tmp/context-compression-research-20261021/e1-preparation-3"
OLD_REQUEST = ROOT / ".tmp/ctx-compact-20261021-1/sdk/9582296476fe44d9b4039e20e81e50ec.candidate.request.json"
SOURCE_PLAN = ROOT / ".tmp/python-analysis-20261021/group-1/plan.json"
RUN_REF = "irun_retrieval_e1_20261020"


class Plan(Record):
    kind: Literal["actual_stage_offline_non_thinking_compaction"] = "actual_stage_offline_non_thinking_compaction"
    deadline: datetime
    source_files: dict[Path, Digest]
    code_files: dict[Path, Digest]
    original_deadline: datetime
    initial_tokens: int
    max_incremental_tokens: Literal[1000000] = 1_000_000
    max_physical_calls: Literal[4] = 4


class Prepared(BaseException):
    """实际 SDK 已构造到 HTTP 边界，明确零发送退出。"""


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def records(directory: Path) -> tuple[list[dict], int]:
    responses = [json.loads(p.read_bytes())["response"]
                 for p in directory.glob("*.candidate.response.json")
                 if json.loads(p.read_bytes()).get("completed")]
    usages = [Usage(input_tokens=r["usage"]["prompt_tokens"],
                    output_tokens=r["usage"]["completion_tokens"],
                    total_tokens=r["usage"]["total_tokens"]) for r in responses]
    return responses, sum(item.total_tokens for item in usages)


def consumes_summary(messages: list[dict], summary: str) -> bool:
    for message in messages:
        if message.get("role") != "system":
            continue
        try:
            context = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(context, dict) and context.get("working_summary") == summary:
            return True
    return False


def configure(output: Path):
    load_dotenv(ROOT / ".env", override=True)
    credential = os.environ.get("DEEPSEEK_API")
    if not credential:
        raise ValueError("现有 DeepSeek 受信凭据不可用")
    os.environ.update(PYTHON_DOTENV_DISABLED="true", OPENAI_API_KEY=credential,
        STRUCTURED_API_KEY=credential, OPENAI_BASE_URL="https://api.deepseek.com",
        STRUCTURED_BASE_URL="https://api.deepseek.com")
    original_plan = GroupPlan.model_validate_json(SOURCE_PLAN.read_bytes())
    settings = branch_settings(original_plan, output)
    return settings


def decide(service, trace):
    capabilities = service._model_visible_capabilities_for_turn(
        service._effective_capabilities(run_ref=RUN_REF), trace.inputs, run_ref=RUN_REF)
    return service._decide_once(run_ref=RUN_REF, messages=trace.messages,
        capabilities=capabilities, inputs=trace.inputs, usage=trace.usage,
        review_criteria=trace.review_criteria, turn_index=trace.usage.model_turns + 1,
        working_plan=trace.working_plan, interaction_mode="auto")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--run", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    output = arguments.output_dir.resolve()
    if not output.is_relative_to((ROOT / ".tmp").resolve()):
        raise ValueError("归档必须在本仓库 .tmp 内")
    output.mkdir(parents=True, exist_ok=True)
    source_trace = SOURCE / f"server-data/interaction_runs/{RUN_REF}/0070.json"

    from personal_agent.application.conversation import ConversationService, FileInteractionJournal
    from personal_agent.application.conversation.models import InteractionTrace
    from personal_agent.application.artifacts import ArtifactService
    from personal_agent.application.conversation.context_materialization import materialize_interaction_inputs
    from personal_agent.application.conversation.citations import materialize_citation_context
    from evals.product_baselines.retrieval_acceptance_server import install_acceptance_observer

    original = InteractionTrace.model_validate_json(source_trace.read_bytes())
    if arguments.prepare:
        source_group = GroupPlan.model_validate_json(SOURCE_PLAN.read_bytes())
        deployment = source_group.source.deployment
        if digest(deployment.path) != deployment.sha256:
            raise ValueError("实际部署配置已偏离来源封存")
        paths = [source_trace, OLD_REQUEST, SOURCE_PLAN, SOURCE / "configuration.json",
                 deployment.path,
                 *sorted((SOURCE / "server-data/uploads").rglob("*")),
                 *sorted((SOURCE / "server-data/generated_artifacts").rglob("*"))]
        code = [*sorted((ROOT / "src").rglob("*.py")), Path(__file__),
                ROOT / "evals/provider_diagnostics/python_result_analysis_runtime.py",
                ROOT / "evals/provider_diagnostics/python_result_analysis_models.py",
                ROOT / "evals/product_baselines/retrieval_acceptance_server.py",
                ROOT / "docs/optimization/to_verify/conversation-loop-boundaries.md"]
        if (output / "plan.json").exists():
            if (output / "run-started.json").exists():
                raise ValueError("已付费身份不得覆盖")
            prior = Plan.model_validate_json((output / "plan.json").read_bytes())
            if any(digest(p) != value for p, value in prior.source_files.items()):
                raise ValueError("准备修正不得改变原始输入")
            suffix = len(list(output.glob("preparation-*.plan.json"))) + 1
            shutil.copyfile(output / "plan.json", output / f"preparation-{suffix}.plan.json")
            if (output / "preflight.json").exists():
                shutil.copyfile(output / "preflight.json", output / f"preparation-{suffix}.preflight.json")
            plan = prior.model_copy(update={"code_files": {p: digest(p) for p in code},
                "source_files": {**prior.source_files, deployment.path: deployment.sha256}})
        else:
            plan = Plan(deadline=datetime.now(UTC) + timedelta(minutes=20),
                source_files={p: digest(p) for p in paths if p.is_file()},
                code_files={p: digest(p) for p in code},
                original_deadline=original.run_deadline_at,
                initial_tokens=original.usage.total_tokens)
        (output / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        write(output / "preflight.json", {"passed": False, "status": "pending",
            "plan_sha256": digest(output / "plan.json")})
        clone = output / "data"
        if not clone.exists():
            shutil.copytree(SOURCE / "server-data", clone,
                ignore=lambda directory, names: ["interaction_runs"] if Path(directory) == SOURCE / "server-data" else [])
        folder = clone / "interaction_runs" / RUN_REF
        folder.mkdir(parents=True, exist_ok=True)
        # 本次独立 Offline 的时间映射，原来源文件和已消耗额度均不改。
        mapped = original.model_copy(update={"run_deadline_at": plan.deadline})
        (folder / "0070.json").write_text(mapped.model_dump_json(indent=2), encoding="utf-8")
        shutil.make_archive(str(output / "source-snapshot"), "zip", ROOT / "src")
    else:
        plan = Plan.model_validate_json((output / "plan.json").read_bytes())
        preflight = json.loads((output / "preflight.json").read_bytes())
        if not preflight["passed"] or preflight.get("plan_sha256") != digest(output / "plan.json"):
            raise ValueError("尚未取得零 HTTP 对照")
        with (output / "run-started.json").open("x", encoding="utf-8") as stream:
            json.dump({"at": datetime.now(UTC).isoformat()}, stream)
    if any(digest(p) != value for p, value in {**plan.source_files, **plan.code_files}.items()):
        raise ValueError("来源或实现身份发生漂移")
    if datetime.now(UTC) >= plan.deadline:
        raise ValueError("本次局部截止已到")
    settings = configure(output)
    number = len(list(output.glob("preflight-*-sdk"))) + 1
    sdk = output / (f"preflight-{number}-sdk" if arguments.prepare else "sdk")
    install_acceptance_observer(sdk)
    previous_send = httpx.Client.send
    admissions: list[dict] = []
    prepared_bodies: dict[str, dict] = {}

    def guarded_send(client, request, *args, **options):
        if request.url.host != "api.deepseek.com" or not request.url.path.endswith("/chat/completions"):
            raise ValueError("禁止评测范围外 HTTP")
        body = json.loads(request.content)
        summary = body.get("thinking") == {"type": "disabled"}
        stage = "summary" if summary else "consumer"
        if body.get("model") != "deepseek-flash" or body.get("max_tokens") != (8192 if summary else 32768):
            raise ValueError("实际模型或输出额度与设计不符")
        if summary:
            expected = json.loads(OLD_REQUEST.read_bytes())
            expected.update(expected.pop("extra_body", {}) or {})
            expected["thinking"] = {"type": "disabled"}
            repeated = any(item["stage"] == "summary" for item in admissions)
            source_preserved = body == expected if not repeated else (
                body["messages"][-2:] == expected["messages"][-2:]
                and {k: v for k, v in body.items() if k != "messages"}
                == {k: v for k, v in expected.items() if k != "messages"})
            if not source_preserved:
                raise ValueError("摘要输入除 thinking 外偏离原失败请求")
        elif body.get("thinking") != {"type": "enabled"}:
            raise ValueError("主任务 thinking 配置被改变")
        if arguments.prepare:
            prepared_bodies[stage] = body
            write(output / f"preflight-{stage}.request.json", body)
            raise Prepared()
        if not summary:
            uncompressed = json.loads((output / "preflight-consumer.request.json").read_bytes())
            summary_text = (output / "summary.txt").read_text(encoding="utf-8")
            if (len(json.dumps(body["messages"], ensure_ascii=False))
                    >= len(json.dumps(uncompressed["messages"], ensure_ascii=False))
                    or not consumes_summary(body["messages"], summary_text)):
                raise ValueError("后继请求未实际缩减或未消费确切摘要，零发送停止")
        responses, spent = records(sdk)
        if len(responses) != len(admissions):
            raise ValueError("之前物理调用存在未知或未结算消费")
        reserve = len(json.dumps(body, ensure_ascii=True, sort_keys=True).encode("ascii")) + body["max_tokens"] + 8192
        if (datetime.now(UTC) >= plan.deadline or len(admissions) >= plan.max_physical_calls
                or sum(x["stage"] == stage for x in admissions) >= 2
                or spent + reserve > plan.max_incremental_tokens):
            raise ValueError("付费前时间／次数／tokens 预约拒绝")
        admissions.append({"stage": stage, "reservation_tokens": reserve,
            "request_sha256": sha256(request.content).hexdigest(), "at": datetime.now(UTC).isoformat()})
        write(output / "admissions.json", admissions)
        return previous_send(client, request, *args, **options)

    httpx.Client.send = guarded_send
    try:
        with branch_environment(output):
            context = build_branch_context(settings, baseline=False)
            service = context.service.runtime._conversation_service
            before = service._journal.get(RUN_REF)
            if arguments.prepare:
                for call in (lambda: decide(service, before), lambda: service._history.compact(RUN_REF)):
                    try:
                        call()
                    except Prepared:
                        pass
                    else:
                        raise ValueError("零 HTTP 预检未命中发送入口")
                if set(prepared_bodies) != {"consumer", "summary"} or list(sdk.glob("*.http.request.json")):
                    raise ValueError("预检请求不完整或意外发送")
                write(output / "preflight.json", {"passed": True, "physical_calls": 0,
                    "plan_sha256": digest(output / "plan.json"),
                    "summary_only_thinking_changed": True, "consumer_thinking_enabled": True,
                    "source_inputs": len(before.inputs)})
                print("PREPARED: full original summary body matched; consumer configuration preserved; zero HTTP")
                return
            checkpoint = service._history.compact(RUN_REF)
            after_summary = service._journal.get(RUN_REF)
            (output / "summary.txt").write_text(checkpoint.working_summary, encoding="utf-8")
            visible = materialize_citation_context(materialize_interaction_inputs(after_summary.inputs))
            projected, history = service._history.project(after_summary, visible)
            restored = ConversationService(model_client=service._model_client,
                artifact_port=ArtifactService(settings), journal=FileInteractionJournal(output / "data/interaction_runs"),
                budget_policy=service._budget_policy, experiment_model_capacity_valid=True)
            restored_trace = restored._journal.get(RUN_REF)
            if restored._history.validate(restored_trace) != checkpoint or restored._history.project(restored_trace, visible) != (projected, history):
                raise ValueError("新 Journal／Artifact 实例未恢复相同检查点和投影")
            decision, response, _, feedback = decide(service, after_summary)
            service._history.record_response(RUN_REF, response)
            after = service._journal.get(RUN_REF)
            if feedback is not None or decision is None:
                raise ValueError("后继真实主决策未形成合法提议")
            responses, spent = records(sdk)
            bodies = [json.loads(p.read_bytes()) for p in sdk.glob("*.http.request.json")]
            consumers = [b for b in bodies if b.get("thinking") == {"type": "enabled"}]
            if not consumers or not any(consumes_summary(b["messages"], checkpoint.working_summary) for b in consumers):
                raise ValueError("实际后继请求没有消费确切摘要")
            if (after.inputs != before.inputs or after.experiment_records != before.experiment_records
                    or after.accepted_tool_requests != before.accepted_tool_requests
                    or after.run_deadline_at != plan.deadline or after.usage.total_tokens - before.usage.total_tokens != spent
                    or len(responses) != len(admissions) or spent > plan.max_incremental_tokens
                    or any(digest(p) != value for p, value in plan.source_files.items())):
                raise ValueError("原件／执行事实／费用／原额度边界失守")
            write(output / "report.json", {"mechanical_passed": True, "evidence_class": plan.kind,
                "physical_calls": len(admissions), "incremental_tokens": spent,
                "original_tokens": before.usage.total_tokens, "final_tokens": after.usage.total_tokens,
                "raw_input_items": len(visible), "projected_items": len(projected),
                "summary_chars": len(checkpoint.working_summary), "restored": True,
                "uncompressed_message_chars": len(json.dumps(json.loads((output / "preflight-consumer.request.json").read_bytes())["messages"], ensure_ascii=False)),
                "compressed_message_chars": len(json.dumps(consumers[0]["messages"], ensure_ascii=False)),
                "exact_summary_in_actual_consumer": True, "business_actions_executed": 0,
                "decision": decision.model_dump(mode="json"),
                "manual_summary_review": "pending", "natural_pressure": False,
                "limitations": ["一次真实阶段 Offline，不是自然触发或 E3", "未执行主决策提议，不验证整例交付", "不计语义判断准确率修复或多次压缩"]})
            print(json.dumps({"mechanical_passed": True, "physical_calls": len(admissions), "tokens": spent}, ensure_ascii=False))
    except Prepared:
        raise
    except BaseException as error:
        write(output / ("preflight-failure.json" if arguments.prepare else "failure.json"),
            {"type": type(error).__name__, "physical_calls": len(admissions)})
        raise
    finally:
        httpx.Client.send = previous_send


if __name__ == "__main__":
    main()
