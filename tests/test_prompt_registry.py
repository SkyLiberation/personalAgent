from personal_agent.kernel.prompts import get_prompt, render_prompt


def test_core_prompts_are_registered_with_versions() -> None:
    prompt_names = [
        "answer_generation.system",
        "evidence_rerank.system",
        "evidence_rerank.user",
        "graphiti.custom_extraction",
        "react.system",
        "structured.system",
        "delete_candidate_resolve.user",
        "solidify_draft.user",
    ]

    for name in prompt_names:
        prompt = get_prompt(name)
        assert prompt.name == name
        assert prompt.version.startswith("v")
        assert prompt.output_contract
        assert prompt.template.strip()


def test_expanded_registry_prompts_render_with_sample_variables() -> None:
    assert "Question: Q" == render_prompt(
        "evidence_rerank.user",
        rerank_prompt="Question: Q",
    )
    assert "personal knowledge graph" in render_prompt("graphiti.custom_extraction")
