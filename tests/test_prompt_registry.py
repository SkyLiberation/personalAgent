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
        "task_analyzer.system",
        "task_analyzer.user",
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


def test_task_analyzer_user_prompt_renders_current_input() -> None:
    rendered = render_prompt("task_analyzer.user", text="删除关于 DNS 的知识")

    assert "分析下面的当前请求：\n删除关于 DNS 的知识" == rendered


def test_task_analyzer_distinguishes_ingest_payload_from_resource_locator() -> None:
    prompt = get_prompt("task_analyzer.system")

    assert prompt.version == "v18"
    assert "只有 search、read 或 list 等只读操作" in prompt.template
    assert "文件路径也属于资源定位符" in prompt.template
    assert "ResourceHint.locator 必须为 null" in prompt.template
    assert "constraint.description=事实 X" in prompt.template
    assert "ResourceHint.origin=user_explicit" in prompt.template
    assert "goals.0.resource_hints.0.user_required_provider" in prompt.template


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
