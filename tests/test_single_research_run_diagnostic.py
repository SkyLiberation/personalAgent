from evals.provider_diagnostics.single_research_run_001 import (
    lifecycle_contract_facts,
    lifecycle_contract_passed,
    score_research_report,
)


def test_single_research_run_grader_requires_two_independent_official_sources():
    report = """
    # 机制比较
    Gemini 使用 Plan、Search、Read、Iterate 和 Output 循环。
    OpenAI 也使用多步骤检索并生成报告。
    https://ai.google.dev/gemini-api/docs/deep-research
    https://developers.openai.com/api/docs/models/o3-deep-research

    # 信任边界
    Application 是生命周期和权限的责任主体，并执行 Verification 与 Completion。

    # 迁移建议
    迁移时保留 Project 生命周期，删除重复 Planner；失败则退出候选。
    """ + ("可核验内容。" * 100)

    score = score_research_report(report)

    assert score["passed"] is True
    assert score["source_groups"] == ["gemini", "openai_deep_research"]


def test_agent_run_contract_maps_timeout_but_still_exposes_usage_gap():
    facts = lifecycle_contract_facts(None)

    assert facts["timed_out_status_typed"] is True
    assert facts["provider_timeout_maps_to_typed_status"] is True
    assert facts["projection_usage_typed"] is False
    assert lifecycle_contract_passed(facts) is False
