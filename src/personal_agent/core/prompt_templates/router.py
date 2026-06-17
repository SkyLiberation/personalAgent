from __future__ import annotations

from ..prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "direct_answer.system": PromptSpec(
        name="direct_answer.system",
        version="v1",
        output_contract="free_text",
        template="你是一个友好、简洁的个人知识库助手。直接回答用户，不需要检索知识库。保持简短。",
    ),
    "router.classify.system": PromptSpec(
        name="router.classify.system",
        version="v2",
        output_contract="RouterDecision",
        template=(
            "你是一个严谨的入口路由分类器，只返回符合 schema 的 JSON。"
            "请把用户输入分类到以下意图之一：capture_text, capture_link, capture_file, ask, "
            "summarize_thread, delete_knowledge, solidify_conversation, direct_answer, unknown。"
            "capture_text: 用户想记录文字内容。capture_link: 用户发来链接想收录。"
            "ask: 任何知识型、定义型、解释型问题（如“什么是X”“X的原理/作用/区别”“为什么……”），"
            "以及需要检索个人知识库、公共网络或最新外部事实才能可靠回答的问题。"
            "用户的知识库可能已沉淀相关笔记，因此这类问题必须走 ask 检索，不得因为看起来是常识就直接回答。"
            "summarize_thread: 需要总结群聊/会话。delete_knowledge: 删除过时或错误的知识笔记。"
            "solidify_conversation: 把对话结论沉淀为知识。"
            "例如已有对话在讨论 DNS，用户再说“将DNS相关知识存储至知识库”，是在要求整理已有会话知识，"
            "必须归为 solidify_conversation，不能把这条操作指令本身按 capture_text 存储。"
            "只有用户输入本身提供了需要原样记录的实质正文时，才归为 capture_text。"
            "direct_answer: 仅限闲聊、问候、感谢、对你自身身份/能力的询问等无信息需求的对话。"
            "注意：知识型或定义型问题（哪怕看起来是常识）不属于此类，应归为 ask。"
            "请重点判断信息是否具有时效性：当前天气、实时价格、最新新闻、航班状态等依赖最新外部事实的问题应归为 ask，"
            "不得仅因问题简单而归为 direct_answer。"
            "当输入不足以安全确定或执行意图时设置 requires_clarification=true，并提供 missing_information 和 clarification_prompt；"
            "例如仅说“帮我”或“删除”需要澄清，而“删除关于 DNS 的知识”已提供检索范围，"
            "应归为 delete_knowledge 且 requires_clarification=false，后续会检索候选并要求用户确认。"
            "“你是谁”“你好”是完整的 direct_answer，不需要澄清。"
            "route 是最终意图；user_visible_message 是简短分类理由。"
            "requires_tools/requires_retrieval/requires_step_projection/candidate_tools 可以按你的判断填写，系统会再合并默认控制字段。"
            "risk_level: 删除类操作应为 high，一般操作为 low。"
            "requires_confirmation: 删除操作应为 true。"
            "历史 chat messages 只用于理解指代和已有讨论主题；"
            "请分类最后一条当前用户输入，不要把历史助手回复当作事实证据。"
        ),
    ),
    "router.classify.user": PromptSpec(
        name="router.classify.user",
        version="v1",
        output_contract="RouterDecision",
        template="当前用户输入：{text}",
    ),
    "replanner.system": PromptSpec(
        name="replanner.system",
        version="v2",
        output_contract="ReExecutionSteps",
        template="你是一个严谨的任务重新规划器，只返回符合 schema 的 JSON。",
    ),
    "replanner.user": PromptSpec(
        name="replanner.user",
        version="v3",
        output_contract="ReExecutionSteps",
        template=(
            "当前计划中的某个步骤执行失败了，请根据失败信息和中间结果，生成替换剩余未完成步骤的新计划。"
            "已经完成的步骤不要重新执行。\n\n"
            "原始意图: {intent}\n\n"
            "原始计划步骤:\n{steps_summary}\n\n"
            "失败步骤: {failed_step_id} ({failed_action_type})\n"
            "失败原因: {error}\n\n"
            "同类任务过去失败的教训（供参考，避免重蹈覆辙；如与当前情况无关可忽略）:\n{reflections}\n\n"
            "已完成的中间结果:\n{obs_summary}\n\n"
            "请返回一个 JSON 对象，包含 steps 数组。每个步骤包含：step_id, action_type, description, "
            "tool_name, tool_input, depends_on, expected_output, success_criteria, risk_level, "
            "requires_confirmation, on_failure。"
            "不要包含已经完成的步骤。如果无法重新规划，返回 {{\"steps\": []}}。"
        ),
    ),
    "react.system": PromptSpec(
        name="react.system",
        version="v2",
        output_contract="tool_call",
        template=(
            "你是一个在受控环境中执行任务步骤的推理助手。"
            "每一轮必须通过工具调用表达下一步动作：需要外部信息时调用允许列表中的真实工具；"
            "已经可以完成时调用 finish_react。"
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
            "当当前保存请求使用“该知识”“这个内容”“上述回答”等指代且未另行指定主题时，"
            "只提炼保存请求之前最近一轮助手回答所表达的知识，不要选择更早的其他主题。"
            "如果候选会话中没有足以支撑本次请求的知识，请将正文留空。\n\n"
            "请输出符合 schema 的 JSON，其中 content 仅包含被选择知识的正文。\n\n"
            "当前保存请求：{entry_text}\n\n候选会话：\n{dialogue}"
        ),
    ),
}
