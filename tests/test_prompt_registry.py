from personal_agent.kernel.prompts import get_prompt, render_prompt


def test_core_prompts_are_registered_with_versions() -> None:
    prompt_names = [
        "answer_generation.system",
        "answer.dialogue_context_policy",
        "ask.unified_answer.user",
        "ask.correction.user",
        "query_planner.system",
        "query_planner.user",
        "evidence_rerank.system",
        "evidence_rerank.user",
        "thread_digest.user",
        "thread_context_compression.user",
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
    dialogue_policy = render_prompt("answer.dialogue_context_policy")

    assert "ContextPack：selected=1" in render_prompt(
        "ask.unified_answer.user",
        dialogue_context_policy=dialogue_policy,
        question="Q",
        context_block="ctx",
        selected_count=1,
        dropped_count=0,
        used_chars=10,
        char_budget=100,
        evidence_block="evidence",
        citation_hint="citation",
        match_hint="match",
    )
    assert "校验发现的问题" in render_prompt(
        "ask.correction.user",
        question="Q",
        answer="A",
        issues_text="issues",
        warnings_text="warnings",
        claims_text="claims",
        evidence_text="evidence",
    )
    assert "Conversation context" in render_prompt(
        "query_planner.user",
        current_datetime="2026-06-11T00:00:00+08:00",
        question="Q",
        conversation_context_block="\n\nConversation context:\nctx",
    )
    assert "Question: Q" == render_prompt(
        "evidence_rerank.user",
        rerank_prompt="Question: Q",
    )
    assert "群聊消息" in render_prompt("thread_digest.user", messages_text="hello")
    assert '"user_goals"' in render_prompt(
        "thread_context_compression.user",
        messages_text="hello",
    )
    assert "personal knowledge graph" in render_prompt("graphiti.custom_extraction")
