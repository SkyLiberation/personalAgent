from pathlib import Path

from evals.e2e_quality.evidence_catalog import (
    RESEARCH_TOOL_PROTOCOL_OUTCOME,
    RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME,
)
from evals.product_baselines.test_conversation_research_delivery_001 import (
    _SAMPLES,
    _concept_coverage,
)
from evals.product_baselines.test_conversation_research_review_001 import REVIEW_SCENARIO


_RESEARCH_CONCEPTS = (
    ("工具", "选择"),
    ("权限", "边界"),
    ("结果", "契约"),
)


def test_concept_coverage_accepts_connected_chinese_paraphrases() -> None:
    answer = """## 工具定义与选择机制
这里说明选择依据。
## 权限与安全边界
这里说明授权规则。
## 结果契约
这里说明返回结构。"""

    assert _concept_coverage(answer, _RESEARCH_CONCEPTS) == (True, True, True)


def test_concept_coverage_rejects_atoms_split_across_unrelated_segments() -> None:
    answer = "工具定义见第一节。选择建议见第二节。权限由宿主负责。边界另行讨论。"

    assert _concept_coverage(answer, _RESEARCH_CONCEPTS) == (False, False, False)


def test_concept_coverage_remains_case_insensitive_for_protocol_terms() -> None:
    concepts = (("checkpoint",), ("replay",), ("副作用",))

    assert _concept_coverage(
        "Checkpoint 记录状态；REPLAY 恢复执行；副作用需要幂等。",
        concepts,
    ) == (True, True, True)


def test_review_pilot_preserves_original_cohort_and_canonical_result_contract() -> None:
    assert len(_SAMPLES) == 20
    assert all(scenario.dataset_revision != REVIEW_SCENARIO.dataset_revision for scenario, _ in _SAMPLES)
    assert REVIEW_SCENARIO.outcome_contract is RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME
    assert RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME.observable_result == RESEARCH_TOOL_PROTOCOL_OUTCOME.observable_result
    assert RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME.counterfactuals == RESEARCH_TOOL_PROTOCOL_OUTCOME.counterfactuals
    root = Path(__file__).resolve().parents[1]
    assert (root / RESEARCH_TOOL_PROTOCOL_OUTCOME.source_ref).is_file()
    assert (root / RESEARCH_TOOL_PROTOCOL_REVIEW_OUTCOME.source_ref).is_file()
