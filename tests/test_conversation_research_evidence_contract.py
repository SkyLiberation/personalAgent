from evals.product_baselines.test_conversation_research_delivery_001 import (
    _concept_coverage,
)


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
