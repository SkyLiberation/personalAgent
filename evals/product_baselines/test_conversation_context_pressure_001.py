"""CONVERSATION-CONTEXT-PRESSURE-001 paired live failure baseline."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
import re
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

import pytest

from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _get_json,
    _post_json,
)
from evals.product_baselines.evidence import (
    ProductEvidenceIdentity,
    ProductEvidenceRecorder,
    canonical_evidence_digest,
    product_evidence_role,
)
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal


pytestmark = pytest.mark.integration
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

_CASE_ID = "CONVERSATION-CONTEXT-PRESSURE-001"
_DATASET_REVISION = "conversation-context-pressure-20-pairs-v2"
_GRADER_VERSION = "conversation-context-pressure-paired-v2"
_JOURNEYS = (
    "acceptance_conditions",
    "fact_correction",
    "scope_withdrawal",
    "decision_summary",
)
_PAIRS = tuple(
    (journey, repetition)
    for repetition in range(1, 6)
    for journey in _JOURNEYS
)
_SAMPLES = tuple(
    (journey, repetition, path_kind)
    for path_kind in ("short", "long")
    for journey, repetition in _PAIRS
)
_MARKER_PATTERN = re.compile(r"CP[0-9A-F]{12}-[A-Z0-9]+")
_NO_EXTERNAL_WORK = "这里只需整理我在本对话中提供的事实，不要查询外部资料、执行动作或委托他人。"


@dataclass(frozen=True, slots=True)
class _Facts:
    pair_id: str
    early_one: str
    early_two: str
    old_value: str
    new_value: str
    withdrawn: str
    added: str
    middle: str
    late: str
    retained: str
    rejected: str
    pending: str

    @property
    def required(self) -> tuple[str, ...]:
        return (
            self.early_one,
            self.early_two,
            self.new_value,
            self.added,
            self.middle,
            self.late,
            self.retained,
            self.rejected,
            self.pending,
        )

    @property
    def forbidden(self) -> tuple[str, ...]:
        return self.old_value, self.withdrawn


@pytest.fixture(scope="module")
def context_pressure_seed() -> str:
    return os.environ.get("PERSONAL_AGENT_CONTEXT_PRESSURE_SEED", uuid4().hex)


@pytest.fixture(scope="module")
def short_path_outcomes() -> dict[str, bool]:
    return {}


def _facts(seed: str, journey: str, repetition: int) -> _Facts:
    digest = sha256(f"{seed}:{journey}:{repetition}".encode()).hexdigest()[:12].upper()
    prefix = f"CP{digest}"
    return _Facts(
        pair_id=f"{journey}-{repetition}",
        early_one=f"{prefix}-EARLY1",
        early_two=f"{prefix}-EARLY2",
        old_value=f"{prefix}-OLD",
        new_value=f"{prefix}-NEW",
        withdrawn=f"{prefix}-WITHDRAWN",
        added=f"{prefix}-ADDED",
        middle=f"{prefix}-MIDDLE",
        late=f"{prefix}-LATE",
        retained=f"{prefix}-RETAINED",
        rejected=f"{prefix}-REJECTED",
        pending=f"{prefix}-PENDING",
    )


def _short_turns(facts: _Facts) -> list[str]:
    return [text + _NO_EXTERNAL_WORK for text in [
        (
            f"我们开始评审决策备忘录。两个一直有效的硬性验收条件是 {facts.early_one} "
            f"和 {facts.early_two}；当前版本暂记为 {facts.old_value}。请简短确认记录，"
            "先不要提交最终备忘录。"
        ),
        (
            f"更正版本：{facts.old_value} 已作废，唯一有效值改为 {facts.new_value}。"
            f"同时撤回 {facts.withdrawn}，新增应交付事项 {facts.added}。请只确认更新。"
        ),
        (
            f"补充当前事实 {facts.middle} 和最终约束 {facts.late}。决策状态分别是："
            f"保留 {facts.retained}，拒绝 {facts.rejected}，待处理 {facts.pending}。"
            "请确认，暂不输出最终稿。"
        ),
        _final_request(facts),
    ]]


def _long_turns(facts: _Facts) -> list[str]:
    turns = [
        (
            f"我们开始多轮项目评审。两个一直有效的硬性验收条件是 {facts.early_one} "
            f"和 {facts.early_two}；当前版本暂记为 {facts.old_value}。请简短确认记录。"
        )
    ]
    turns.extend(
        f"第 {index} 项评审细节已经解决，不改变既有硬性条件；请简短确认并继续。"
        for index in range(2, 9)
    )
    turns.append(
        f"正式更正：{facts.old_value} 已作废，唯一有效版本改为 {facts.new_value}。"
        "后续备忘录不得采用旧值。请确认更新。"
    )
    turns.extend(
        f"第 {index} 项实施讨论已闭环，不新增或撤销验收条件；请简短确认。"
        for index in range(10, 15)
    )
    turns.append(
        f"范围调整：明确撤回 {facts.withdrawn}，新增应交付事项 {facts.added}。"
        "最终稿不得复活已撤回事项。请确认。"
    )
    turns.extend(
        f"第 {index} 项风险讨论已解决，不改变当前范围和版本；请简短确认。"
        for index in range(16, 21)
    )
    turns.append(
        f"中段事实确认为 {facts.middle}。决策状态是保留 {facts.retained}、"
        f"拒绝 {facts.rejected}、待处理 {facts.pending}。请确认。"
    )
    turns.append("补充：此前已经闭环的讨论不需要写入最终稿，请继续保留当前有效事实。")
    turns.append(
        f"最后补充的约束是 {facts.late}。请确认已经记录，下一轮我会要求最终稿。"
    )
    turns.append(_final_request(facts))
    assert len(turns) == 24
    return [text + _NO_EXTERNAL_WORK for text in turns]


def _final_request(facts: _Facts) -> str:
    del facts
    return (
        "现在提交可直接使用的中文决策备忘录：列出两个仍有效的早期硬性条件、"
        "唯一有效版本、新增交付事项、中段事实、最终约束，并把保留、拒绝、待处理"
        "三种终态分别写清。不得出现已作废版本或已撤回事项，也不要加入其他项目内容。"
    )


def _trace(server: LiveWebProcess, user_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return _get_json(
        f"{server.base_url}/api/conversation/runs/"
        f"{result['interaction_run_ref']}?" + urlencode({"user_id": user_id})
    )


def _config_cohort(server: LiveWebProcess) -> str:
    settings = server.settings
    return canonical_evidence_digest({
        "structured_model": settings.structured.model,
        "structured_provider_host": urlparse(
            settings.structured.base_url or ""
        ).hostname,
        "structured_output_transport": settings.structured.output_transport,
        "interaction_policy_revision": settings.interaction_loop.policy_revision,
        "formal_entrypoint": "POST /api/conversation/turn",
        "interaction_mode": "auto",
        "persistence": "production-postgres-composition",
        "dataset_revision": _DATASET_REVISION,
    })


@pytest.mark.parametrize(
    ("journey", "repetition", "path_kind"),
    _SAMPLES,
    ids=[f"{path}-{journey}-run-{rep}" for journey, rep, path in _SAMPLES],
)
def test_conversation_context_pressure_001(
    request: pytest.FixtureRequest,
    live_web_process: LiveWebProcess,
    product_evidence_recorder: ProductEvidenceRecorder,
    context_pressure_seed: str,
    short_path_outcomes: dict[str, bool],
    journey: str,
    repetition: int,
    path_kind: str,
) -> None:
    facts = _facts(context_pressure_seed, journey, repetition)
    turns = _short_turns(facts) if path_kind == "short" else _long_turns(facts)
    user_id = f"context-pressure-{facts.pair_id}-{path_kind}"
    conversation_id = f"context-pressure-{facts.pair_id}-{path_kind}-{uuid4().hex}"
    initial_state = {
        "isolated_conversation": True,
        "pair_id": facts.pair_id,
        "path_kind": path_kind,
        "planned_message_count_after_response": len(turns) * 2,
        "required_fact_digest": canonical_evidence_digest(facts.required),
        "forbidden_fact_digest": canonical_evidence_digest(facts.forbidden),
        "dataset_revision": _DATASET_REVISION,
    }
    product_evidence_recorder.enroll(
        nodeid=request.node.nodeid,
        identity=ProductEvidenceIdentity(
            case_id=_CASE_ID,
            role=product_evidence_role(_CASE_ID),
            evidence_class="product_e2e",
            formal_entrypoint="POST /api/conversation/turn",
            interaction_mode="auto",
            principal=AuthenticatedPrincipal(
                tenant_id="personal-agent",
                user_id=user_id,
            ),
            user_input_digest=canonical_evidence_digest(turns),
            initial_state_digest=canonical_evidence_digest(initial_state),
            config_cohort=_config_cohort(live_web_process),
            grader_version=_GRADER_VERSION,
        ),
    )

    messages: list[dict[str, str]] = []
    result: dict[str, Any] = {}
    trace: dict[str, Any] = {}
    entry_error: str | None = None
    completed_turns = 0
    for text in turns:
        messages.append({"role": "user", "content": text})
        try:
            result = _post_json(
                f"{live_web_process.base_url}/api/conversation/turn",
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "messages": messages,
                    "interaction_mode": "auto",
                },
            )
            trace = _trace(live_web_process, user_id, result)
        except Exception as exc:  # External provider/HTTP fact, not context failure.
            entry_error = f"{type(exc).__name__}: {exc}"
            break
        messages.append({
            "role": "assistant",
            "content": str(result.get("message", {}).get("content", "")),
        })
        completed_turns += 1

    answer = str(result.get("message", {}).get("content", ""))
    required_present = all(value in answer for value in facts.required)
    forbidden_absent = all(value not in answer for value in facts.forbidden)
    own_markers = set((*facts.required, *facts.forbidden))
    observed_markers = set(_MARKER_PATTERN.findall(answer))
    cross_sample_clean = observed_markers <= own_markers
    memo_form = len(answer) >= 80 and any(
        term in answer for term in ("备忘录", "决策", "验收")
    )
    implicit_knowledge_write = bool(trace.get("knowledge_save_operation"))
    provider_or_entry_failure = entry_error is not None
    delivered = (
        completed_turns == len(turns)
        and result.get("disposition") == "answer"
        and required_present
        and forbidden_absent
        and cross_sample_clean
        and memo_form
        and not implicit_knowledge_write
        and not provider_or_entry_failure
    )
    if path_kind == "short":
        short_path_outcomes[facts.pair_id] = delivered
    paired_short_delivered = short_path_outcomes.get(facts.pair_id)
    long_result_failure = path_kind == "long" and not delivered
    attributable_long_failure = bool(
        long_result_failure
        and paired_short_delivered
        and not provider_or_entry_failure
    )
    compositions = trace.get("context_composition") or []
    final_composition = compositions[-1] if compositions else {}
    usage = trace.get("usage") or {}
    report = {
        "case_id": _CASE_ID,
        "pair_id": facts.pair_id,
        "journey": journey,
        "repetition": repetition,
        "path_kind": path_kind,
        "natural_user_turns": turns,
        "initial_state": initial_state,
        "result": result,
        "interaction_trace": trace,
        "result_metrics": {
            "is_short": path_kind == "short",
            "is_long": path_kind == "long",
            "short_failure": path_kind == "short" and not delivered,
            "short_delivered": path_kind == "short" and delivered,
            "long_result_failure": long_result_failure,
            "attributable_long_failure": attributable_long_failure,
            "provider_or_entry_failure": provider_or_entry_failure,
            "delivered": delivered,
            "required_present": required_present,
            "forbidden_absent": forbidden_absent,
            "cross_sample_clean": cross_sample_clean,
            "cross_sample_pollution": not cross_sample_clean,
            "implicit_knowledge_write": implicit_knowledge_write,
            "memo_form": memo_form,
            "context_measurement_missing": not bool(compositions),
            "completed_turns": completed_turns,
            "message_count_after_response": len(messages),
            "conversation_messages_chars": int(
                final_composition.get("conversation_messages_chars") or 0
            ),
            "input_tokens": int(final_composition.get("input_tokens") or 0),
            "model_calls": int(usage.get("model_calls") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        },
    }
    product_evidence_recorder.capture_report(report)

    assert delivered, report["result_metrics"]
