from personal_agent.kernel.prompts import get_prompt, render_prompt


def test_core_prompts_are_registered_with_versions() -> None:
    prompt_names = [
        "answer_generation.system",
        "answer.dialogue_context_policy",
        "ask.web_answer.user",
        "ask.unified_answer.user",
        "ask.graph_answer.user",
        "ask.local_answer.user",
        "ask.correction.user",
        "direct_answer.system",
        "router.classify.system",
        "router.classify.user",
        "replanner.system",
        "replanner.user",
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


def test_router_user_prompt_renders_current_input() -> None:
    rendered = render_prompt("router.classify.user", text="删除关于 DNS 的知识")

    assert "当前用户输入：删除关于 DNS 的知识" == rendered


def test_replanner_prompt_escapes_json_literal() -> None:
    rendered = render_prompt(
        "replanner.user",
        intent="ask",
        steps_summary="- s1: retrieve 检索 [failed]",
        failed_step_id="s1",
        failed_action_type="retrieve",
        error="timeout",
        obs_summary="无",
        reflections="无",
    )

    assert '{"steps": []}' in rendered
    assert "失败步骤: s1 (retrieve)" in rendered


def test_expanded_registry_prompts_render_with_sample_variables() -> None:
    dialogue_policy = render_prompt("answer.dialogue_context_policy")

    assert "网络搜索结果" in render_prompt(
        "ask.web_answer.user",
        dialogue_context_policy=dialogue_policy,
        question="Q",
        context_block="ctx",
        web_block="web",
    )
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
    assert "图谱事实网络" in render_prompt(
        "ask.graph_answer.user",
        dialogue_context_policy=dialogue_policy,
        question="Q",
        context_block="ctx",
        focus_entities="Redis",
        graph_fact_block="facts",
        anchored_block="anchors",
        notes_block="notes",
    )
    assert "相关内容证据" in render_prompt(
        "ask.local_answer.user",
        dialogue_context_policy=dialogue_policy,
        question="Q",
        context_block="ctx",
        notes_block="notes",
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
