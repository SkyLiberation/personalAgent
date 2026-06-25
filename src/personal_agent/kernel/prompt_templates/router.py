from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "direct_answer.system": PromptSpec(
        name="direct_answer.system",
        version="v1",
        output_contract="free_text",
        template="你是一个友好、简洁的个人知识库助手。直接回答用户，不需要检索知识库。保持简短。",
    ),
    "router.classify.system": PromptSpec(
        name="router.classify.system",
        version="v7",
        output_contract="RouterOutput",
        template=(
            "任务：识别当前用户请求中的语义目标，并按 schema 返回结果。\n"
            "意图：capture_text=记录当前输入中的实质正文；capture_link=收录链接；"
            "capture_file=收录文件；ask=知识、解释、实时事实或检索问题；"
            "summarize_thread=总结会话；delete_knowledge=删除知识；"
            "solidify_conversation=提炼历史对话中的结论并入库；"
            "review_digest=立即生成当前用户的知识简报；"
            "consolidate_knowledge=按主题整理并合并已有知识；"
            "inspect_knowledge_gaps=分析知识孤岛、薄弱连接或潜在冲突；"
            "research_once=对外部最新信息执行一次性多来源研究；"
            "create_research_subscription=创建每天/每周定时运行的外部信息收集简报；"
            "manage_research=查看、暂停、恢复、修改、立即运行 Research 订阅，或查看简报、反馈、入库；"
            "maintain_knowledge=查看、修正、替换、标记过期或标记冲突的已有知识；"
            "inspect_operations=诊断后台 worker、队列、失败任务或重试 dead 任务；"
            "inspect_workflow=查看或解释某个 workflow run 的步骤、状态、历史与失败原因；"
            "direct_answer=问候、感谢、身份或能力闲聊；unknown=无法判断。\n"
            "拆分规则：\n"
            "1. 一个请求可以产生一个或多个 goals；按用户表达的处理顺序排列。\n"
            "2. 每个 goal.input 只保留该目标实际处理的内容，不混入其他目标的指令。\n"
            "3. 只判断用户要完成什么，不决定如何执行。\n"
            "4. 历史消息只用于理解指代；不要把历史助手回复当事实证据。\n"
            "5. 疑问句（“什么是…”“…是什么”“为什么…”“如何…”“怎么…”等）一律是 ask，"
            "绝不路由到 capture_text 或 solidify_conversation。\n"
            "6. solidify_conversation 只在用户明确要求把【历史对话】中的结论保存/固化/记下来时使用，"
            "且必须已存在可提炼的历史对话；没有历史对话时不得选 solidify_conversation。\n"
            "澄清规则：只有缺失信息会导致目标无法确定或无法执行时才返回 outcome=clarify。"
            "此时 clarification 必须包含缺失信息和一个直接的追问；否则返回 outcome=ready 且 clarification=null。\n"
            "边界示例：用户提供待保存正文时用 capture_text；用户说“把刚才结论记下来”时用 solidify_conversation；"
            "知识问题即使看似常识也用 ask（如“什么是DNS”“什么是服务降级”都是 ask，不是 capture 也不是 solidify）；"
            "“删除关于 DNS 的知识”信息足够，不需要入口澄清；"
            "“生成今天的知识简报”用 review_digest；"
            "“把关于缓存的笔记整理成一篇综述”用 consolidate_knowledge，input 只保留“缓存”；"
            "“检查我的知识库还有哪些缺口”用 inspect_knowledge_gaps；"
            "“调研最近一个月 Agent 工具调用的发展”用 research_once；"
            "“每天9点收集AI新闻简报”用 create_research_subscription；"
            "“把 AI 简报改成每天8点/暂停这个订阅/马上跑一次”用 manage_research；"
            "“这条知识过期了/用新版替换这条笔记/这两条知识冲突”用 maintain_knowledge；"
            "“为什么昨天简报没发/worker 是否堆积/重试失败任务”用 inspect_operations；"
            "“这个 run 哪一步失败了/查看 run_id 的执行历史”用 inspect_workflow。\n"
            "复合示例：“记住：DNS 把域名解析为 IP，然后回答 DNS 为什么需要缓存”应产生两个 goals："
            "先 capture_text，再 ask。"
        ),
    ),
    "router.classify.user": PromptSpec(
        name="router.classify.user",
        version="v1",
        output_contract="RouterOutput",
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
