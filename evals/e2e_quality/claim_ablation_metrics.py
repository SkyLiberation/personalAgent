"""从冻结的 claim 消融裁判和用量生成独立离线指标归档。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from statistics import mean, median
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]
METRIC_VERSION = "claim-verifier-metrics:v1"
Arm = Literal["full", "no_claim"]
Outcome = Literal["detected", "missed", "allowed", "false_reject"]
ARMS: tuple[Arm, ...] = ("full", "no_claim")


class RecountPlan(BaseModel):
    """计划显式拥有样本到任务的归属，不从样本名称推断独立性。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    metric_definition_version: Literal["claim-verifier-metrics:v1"]
    run_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    main_cohorts: tuple[str, ...] = Field(min_length=1)
    sample_task_ids: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def explicit_selection(self) -> RecountPlan:
        if len(set(self.main_cohorts)) != len(self.main_cohorts):
            raise ValueError("主配对组不能重复")
        if any(not value.strip() for value in self.main_cohorts):
            raise ValueError("主配对组不能为空")
        if any(
            not sample.strip() or not task.strip()
            for sample, task in self.sample_task_ids.items()
        ):
            raise ValueError("样本和独立任务身份不能为空")
        return self


class Point(BaseModel):
    id: str
    expected_relation: Literal["unsupported", "supported"]


class LabeledRelation(BaseModel):
    point: Point


class LabeledInput(BaseModel):
    sample_id: str
    relations: tuple[LabeledRelation, ...]


class Decision(BaseModel):
    sample_id: str
    point_id: str
    full: Outcome
    no_claim: Outcome


class Adjudication(BaseModel):
    relations: tuple[Decision, ...]
    independent_human_review: bool


class Invocation(BaseModel):
    cohort: str
    id: str
    arm: Arm
    status: Literal["ok"]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    seconds: float = Field(gt=0, allow_inf_nan=False)
    retry_attempts: int = Field(ge=0)


class Evidence(BaseModel):
    """只消费封存汇总中已有的裁判和实际用量，不生成语义判断。"""

    logical_results: tuple[Invocation, ...]
    new_source_relations: tuple[LabeledInput, ...]
    semantic_adjudication: Adjudication


class Rate(TypedDict):
    numerator: int
    denominator: int
    value: float | None


class RelationMetrics(TypedDict):
    true_positive: int
    false_negative: int
    false_positive: int
    true_negative: int
    A1_selected_relation_recall: Rate
    A2_selected_legal_relation_false_positive_rate: Rate


def rate(numerator: int, denominator: int) -> Rate:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def scores(decisions: tuple[Decision, ...], arm: Arm) -> RelationMetrics:
    counts = Counter(getattr(decision, arm) for decision in decisions)
    return {
        "true_positive": counts["detected"],
        "false_negative": counts["missed"],
        "false_positive": counts["false_reject"],
        "true_negative": counts["allowed"],
        "A1_selected_relation_recall": rate(
            counts["detected"], counts["detected"] + counts["missed"]
        ),
        "A2_selected_legal_relation_false_positive_rate": rate(
            counts["false_reject"], counts["false_reject"] + counts["allowed"]
        ),
    }


def usage(calls: tuple[Invocation, ...], arm: Arm) -> dict[str, int | float]:
    selected = tuple(call for call in calls if call.arm == arm)
    return {
        "logical_calls": len(selected),
        "input_tokens": sum(call.input_tokens for call in selected),
        "output_tokens": sum(call.output_tokens for call in selected),
        "total_tokens": sum(call.total_tokens for call in selected),
        "structural_repairs": sum(call.retry_attempts for call in selected),
        "observed_wall_seconds_sum": sum(call.seconds for call in selected),
        "observed_call_wall_seconds_median": median(call.seconds for call in selected),
    }


def build_report(evidence: Evidence, plan: RecountPlan) -> dict[str, object]:
    """检查完整真实配对，再按固定口径聚合既有裁判。"""

    calls = tuple(
        call for call in evidence.logical_results if call.cohort in plan.main_cohorts
    )
    pairs: dict[tuple[str, str], dict[Arm, Invocation]] = {}
    for call in calls:
        pair = pairs.setdefault((call.cohort, call.id), {})
        if (
            call.arm in pair
            or call.total_tokens != call.input_tokens + call.output_tokens
        ):
            raise ValueError("配对臂重复或原生用量不一致")
        pair[call.arm] = call
    if {call.cohort for call in calls} != set(plan.main_cohorts):
        raise ValueError("主配对组与冻结计划不一致")
    if any(set(pair) != set(ARMS) for pair in pairs.values()):
        raise ValueError("配对缺失；不能将缺失观测填成零")
    samples = {sample for _, sample in pairs}
    if samples != plan.sample_task_ids.keys() or len(samples) != len(pairs):
        raise ValueError("主配对样本与任务映射不一致，或跨组重复使用样本身份")

    labels: dict[str, tuple[str, str]] = {}
    if len({sample.sample_id for sample in evidence.new_source_relations}) != len(
        evidence.new_source_relations
    ):
        raise ValueError("同一输入的关系标签不能重复登记")
    for sample in evidence.new_source_relations:
        for relation in sample.relations:
            if relation.point.id in labels or sample.sample_id not in samples:
                raise ValueError("标签身份重复或不属于本轮主配对")
            labels[relation.point.id] = (
                sample.sample_id,
                relation.point.expected_relation,
            )
    decisions = evidence.semantic_adjudication.relations
    if (
        len(decisions) != len(labels)
        or {d.point_id for d in decisions} != labels.keys()
    ):
        raise ValueError("标签与裁判没有一一覆盖")
    families: set[tuple[str, str, str]] = set()
    for decision in decisions:
        sample, expected = labels[decision.point_id]
        if sample != decision.sample_id or not decision.point_id.startswith(
            sample + "-"
        ):
            raise ValueError("关系没有绑定对应输入")
        families.add(
            (
                plan.sample_task_ids[sample],
                decision.point_id[len(sample) + 1 :],
                expected,
            )
        )
        valid = (
            {"detected", "missed"}
            if expected == "unsupported"
            else {"allowed", "false_reject"}
        )
        if any(getattr(decision, arm) not in valid for arm in ARMS):
            raise ValueError("裁判结果与冻结关系标签不相容")

    tasks = sorted({plan.sample_task_ids[decision.sample_id] for decision in decisions})
    by_task = {
        task: {
            arm: scores(
                tuple(
                    d for d in decisions if plan.sample_task_ids[d.sample_id] == task
                ),
                arm,
            )
            for arm in ARMS
        }
        for task in tasks
    }
    macro: dict[Arm, dict[str, object]] = {}
    for arm in ARMS:
        macro[arm] = {}
        for metric in (
            "A1_selected_relation_recall",
            "A2_selected_legal_relation_false_positive_rate",
        ):
            measured = {
                task: by_task[task][arm][metric]["value"]
                for task in tasks
                if by_task[task][arm][metric]["value"] is not None
            }
            macro[arm][metric] = {
                "value": mean(measured.values()) if measured else None,
                "contributing_tasks": list(measured),
                "denominator_tasks": len(measured),
            }
    negative = tuple(d for d in decisions if labels[d.point_id][1] == "unsupported")
    paired = Counter((d.full == "detected", d.no_claim == "detected") for d in negative)
    full_input = sum(call.input_tokens for call in calls if call.arm == "full")
    no_input = sum(call.input_tokens for call in calls if call.arm == "no_claim")
    difference = full_input - no_input
    return {
        "metric_definition_version": METRIC_VERSION,
        "run_id": plan.run_id,
        "evidence_class": "offline_eval_metrics_recount",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "new_model_calls": 0,
        "source": {"path": plan.source_path, "sha256": plan.source_sha256},
        "scope": {
            "cost_complete_input_pairs": len(pairs),
            "cost_independent_source_tasks": len(set(plan.sample_task_ids.values())),
            "quality_labeled_inputs": len(evidence.new_source_relations),
            "quality_independent_source_tasks": len(tasks),
            "quality_relation_instances": len(decisions),
            "quality_unique_task_relation_families": len(families),
            "negative_instances": len(negative),
            "negative_relation_families": sum(
                item[2] == "unsupported" for item in families
            ),
            "legal_relation_families": sum(item[2] == "supported" for item in families),
            "complete_answer_annotation": False,
            "independent_human_review": evidence.semantic_adjudication.independent_human_review,
            "cropped_diagnostics_in_main_denominators": False,
        },
        "selected_relation_scores": {arm: scores(decisions, arm) for arm in ARMS},
        "by_task": by_task,
        "task_equal_weight_means": macro,
        "paired_answer_error_detection": {
            "full_only": paired[(True, False)],
            "no_claim_only": paired[(False, True)],
            "both_detected": paired[(True, True)],
            "both_missed": paired[(False, False)],
            "net_gain_percentage_points": 100
            * (paired[(True, False)] - paired[(False, True)])
            / len(negative)
            if negative
            else None,
        },
        "A6_verifier_usage": {arm: usage(calls, arm) for arm in ARMS},
        "A6_input_token_change": {
            "full_minus_no_claim": difference,
            "full_over_no_claim_percent": 100 * difference / no_input
            if no_input
            else None,
            "removal_saves_percent_of_full": 100 * difference / full_input
            if full_input
            else None,
        },
        "cost_by_cohort": {
            cohort: {
                arm: usage(tuple(call for call in calls if call.cohort == cohort), arm)
                for arm in ARMS
            }
            for cohort in sorted(plan.main_cohorts)
        },
        "unavailable": {
            "complete_answer_recall_and_feedback_precision": "输入仅裁判预设关系，未完整标注答案与所有反馈",
            "A3_actionable_feedback_rate": "尚未输入全部反馈的可执行性裁判",
            "A4_closed_loop_repair_rate": "尚未输入两组实际反馈消费及完整新版裁判",
            "A5_user_outcome_pass_rate": "尚未输入两组 Product E2E 的用户结果契约及裁判",
            "A6_repairs_per_million_tokens": "缺少成功修复数及连续修订成本",
            "R1_general_resource_error_recall": "尚未输入研究稿完整错误裁判，个案另在证据正文说明",
            "R2_mirror_only_feedback_and_cost_share": "尚未输入完整反馈分类与独立消费成本",
            "R3_evidence_gap_completion_rate": "没有上游取证决策的消融对照",
            "stable_latency_or_confidence_interval": "本入口不生成稳定时延或统计推断",
            "monetary_cost": "没有价格与缓存计费依据",
        },
    }


def archive_report(plan_path: Path, output_root: Path) -> Path:
    plan_bytes = plan_path.read_bytes()
    plan = RecountPlan.model_validate_json(plan_bytes)
    source_bytes = (ROOT / plan.source_path).read_bytes()
    if sha256(source_bytes).hexdigest() != plan.source_sha256:
        raise ValueError("源汇总 SHA-256 不符；不能覆盖旧比较身份")
    report = build_report(Evidence.model_validate_json(source_bytes), plan)
    report_bytes = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    artifacts = {
        "plan.json": plan_bytes,
        "source.json": source_bytes,
        "report.json": report_bytes,
        "reporter.py": Path(__file__).read_bytes(),
    }
    manifest = {
        "metric_definition_version": METRIC_VERSION,
        "run_id": plan.run_id,
        "evidence_class": "offline_eval_metrics_recount",
        "new_model_calls": 0,
        "python_version": sys.version,
        "pydantic_version": version("pydantic"),
        "artifacts": [
            {"path": name, "bytes": len(content), "sha256": sha256(content).hexdigest()}
            for name, content in artifacts.items()
        ],
    }
    artifacts["manifest.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    artifacts["checksums.sha256"] = "".join(
        f"{sha256(content).hexdigest()}  {name}\n"
        for name, content in artifacts.items()
    ).encode("utf-8")
    output_root.mkdir(parents=True, exist_ok=False)
    for name, content in artifacts.items():
        with (output_root / name).open("xb") as target:
            target.write(content)
    return output_root / "report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="冻结指标版本、源校验和及任务映射的计划",
    )
    parser.add_argument(
        "--output-root", type=Path, required=True, help="尚不存在的独立归档目录"
    )
    args = parser.parse_args()
    try:
        report = archive_report(args.plan, args.output_root)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"claim 指标归档失败：{exc}\n")
    print(f"claim 指标归档完成：{report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
