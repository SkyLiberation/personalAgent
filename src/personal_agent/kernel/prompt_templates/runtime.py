from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "react.system": PromptSpec(
        name="react.system",
        version="v3",
        output_contract="tool_call",
        template=(
            "你是一个在受控环境中执行任务步骤的推理助手。"
            "每一轮必须通过工具调用表达下一步动作：需要外部信息时调用允许列表中的真实工具；"
            "已经可以完成时调用 finish_react。"
            "一旦 Observation 已包含完成当前步骤所需的信息，必须调用 finish_react，"
            "不得重复相同的 provider 调用；工具预算耗尽时只能调用 finish_react。"
            "真实工具参数必须满足对应 tool schema，不要编造未提供的工具名或参数。"
        ),
    ),
    "structured.system": PromptSpec(
        name="structured.system",
        version="v1",
        output_contract="json_schema",
        template="你是一个严谨的结构化输出助手，只返回符合 schema 的 JSON。",
    ),
    "delete_candidate_resolve.user": PromptSpec(
        name="delete_candidate_resolve.user",
        version="v2",
        output_contract="DeleteCandidate",
        template=(
            "你负责从已有知识笔记候选中定位用户明确要求删除的目标。"
            "只在目标与候选明显对应时选择一条；不确定或有多个可能目标时返回 null。"
            "不要执行删除，也不要生成不存在的 ID。"
            "输出必须符合 schema，note_id 只能是候选 ID 或 null。\n\n"
            "用户删除请求：{delete_request}\n"
            "候选笔记：{prompt_candidates}"
        ),
    ),
    "solidify_draft.user": PromptSpec(
        name="solidify_draft.user",
        version="v2",
        output_contract="SolidifyDraft",
        template=(
            "你负责决定哪些会话事实属于用户本次指定的固化范围，并将它们整理为一条可独立入库的中文知识笔记。"
            "候选会话可能同时包含多个无关主题，必须根据当前保存请求进行语义选择；"
            "不要仅因为某段出现在上下文中就写入笔记，也不要写入操作指令本身。"
            "当当前保存请求使用‘该知识’‘这个内容’‘上述回答’等指代且未另行指定主题时，"
            "只提炼保存请求之前最近一轮助手回答所表达的知识，不要选择更早的其他主题。"
            "如果候选会话中没有足以支撑本次请求的知识，请将正文留空。\n\n"
            "请输出符合 schema 的 JSON，其中 content 仅包含被选择知识的正文。\n\n"
            "当前保存请求：{entry_text}\n\n候选会话：\n{dialogue}"
        ),
    ),
}
