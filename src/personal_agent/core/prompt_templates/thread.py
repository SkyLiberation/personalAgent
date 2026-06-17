from __future__ import annotations

from ..prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "thread_digest.user": PromptSpec(
        name="thread_digest.user",
        version="v1",
        output_contract="free_text",
        template=(
            "你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。"
            "按主题分点列出讨论的关键事项、达成的结论和待办事项。"
            "保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。\n\n"
            "群聊消息：\n{messages_text}"
        ),
    ),
    "thread_context_compression.user": PromptSpec(
        name="thread_context_compression.user",
        version="v1",
        output_contract="ThreadSummary",
        template=(
            "你在为一个多轮对话压缩较早的历史，供后续轮次理解上下文使用。"
            "这不是面向用户的纪要，目标是维护结构化 ThreadSummary。\n"
            "要求：\n"
            "- 只压缩、不展开，不要补充对话中没有的信息；\n"
            "- 用户明确确认的内容才能进入 user_goals、user_constraints、confirmed_decisions 或 pending_tasks；\n"
            "- 助手历史回复、建议、推测只能进入 assistant_assumptions，不能当事实；\n"
            "- 对话中出现但没有证据支撑或用户确认的事实判断放入 unverified_claims；\n"
            "- 开放问题、冲突点、待澄清事项放入 open_questions；\n"
            "- evidence_refs 只能放对话里明确出现的 note_id、citation、tool ref 或文件/URL 引用。\n"
            "只返回合法 JSON，不要 Markdown，不要解释。JSON schema:\n"
            "{{\n"
            "  \"user_goals\": [\"...\"],\n"
            "  \"user_constraints\": [\"...\"],\n"
            "  \"confirmed_decisions\": [\"...\"],\n"
            "  \"pending_tasks\": [\"...\"],\n"
            "  \"open_questions\": [\"...\"],\n"
            "  \"assistant_assumptions\": [\"...\"],\n"
            "  \"unverified_claims\": [\"...\"],\n"
            "  \"evidence_refs\": [\"...\"],\n"
            "  \"context_notes\": [\"...\"]\n"
            "}}\n\n"
            "待更新的摘要和新增较早对话：\n{messages_text}"
        ),
    ),
}
