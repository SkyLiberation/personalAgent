"""Owned model instructions and execution feedback, selected per Runtime instance."""
from personal_agent.kernel.prompt_registry import PromptSpec

PROMPTS = {
    'research_policy_decision': PromptSpec(
        name='research_policy_decision', version='2026-10-27.v1-md1', owner='research',
        template="""

## 任务
你是 research agent 的下一步策略决策器。你可以自己提出更有信息增益的 search_web query，也可以在证据已经足够或预算不值得继续消耗时 stop。只能输出 JSON，不能输出解释性正文。

## 输出协议
允许 action：search_web, stop。
JSON schema：{{"action":"search_web|stop","query":"...","purpose":"...","event_id":"...","expected_gain":"official_confirmation|independent_source|disambiguation|personal_relevance|recency|stop","cost_level":"low|medium|high","reason":"..."}}。

## 约束
约束：search_web 的 query 必须具体、不能重复已执行查询；event_id 必须来自事件列表或为空；不要为了补低价值信息消耗预算。

## 当前输入
主题：{topic}
要求：{instructions}
研究策略：{policy}
初始查询计划：{query_plan}
已执行查询：{query_history}
剩余查询预算：{remaining_queries}
剩余探索查询预算：{remaining_exploration}
剩余验证查询预算：{remaining_verification}
剩余工具预算：{remaining_tools}
事件：{events}
证据缺口：{gaps}
可参考动作：{action_hints}""",
    ),
    'research_next_action': PromptSpec(
        name='research_next_action', version='2026-10-27.v1-md1', owner='research',
        template="""

## 任务与约束
你是研究循环的下一步动作选择器。只能从候选 candidates 中选择一个，不能发明新 action 或 query。目标是在有限预算内优先提升事件可信度，尤其是补齐官方来源或独立来源。若候选都没有价值，选择 stop。

## 输出
只输出 JSON：{{"candidate_id":"candidate_0","reason":"..."}} 或 {{"candidate_id":"stop","reason":"..."}}。

## 当前输入
主题：{topic}
要求：{instructions}
研究策略：{policy}
已执行查询：{query_history}
剩余查询预算：{remaining_queries}
剩余验证查询预算：{remaining_verification}
事件：{events}
候选：{candidates}""",
    ),
    'research_satisfaction': PromptSpec(
        name='research_satisfaction', version='2026-10-27.v1-md1', owner='research',
        template="""

## 任务
评估当前 research 是否已经满足用户目标。只输出 JSON，不要输出 Markdown。

## 输出协议
JSON schema：{{"coverage_score":0.0,"confidence_score":0.0,"remaining_critical_gap_ids":["..."],"marginal_gain":0.0,"should_continue":true,"reason":"..."}}。

## 判定标准
coverage_score 衡量是否已找到足够数量且覆盖主题的候选事件；confidence_score 衡量来源支撑是否达到用户可信度目标；marginal_gain 衡量继续搜索预计新增价值；remaining_critical_gap_ids 只能引用给定 gaps 中仍阻碍目标满足的 gap id。在预算有限时，如果继续搜索只能低收益重复，应 should_continue=false。

## 当前输入
主题：{topic}
要求：{instructions}
目标条数：{max_items}
研究策略：{policy}
迭代次数：{iterations}/{max_queries}
探索查询：{exploration}/{max_exploration}
验证查询：{verification}/{max_verification}
工具调用：{tool_calls}/{max_tool_calls}
连续低收益轮次：{low_yield_rounds}
已执行查询：{query_history}
事件：{events}
证据缺口：{gaps}""",
    ),
    'research_request_understanding': PromptSpec(
        name='research_request_understanding', version='2026-10-27.v1-md1', owner='research',
        template="""

## 任务
将一次研究请求解析成规范化 research run，并生成初始搜索策略。只输出 JSON，不要输出 Markdown 或解释。

## 输出协议
JSON schema：{{"topic":"...","instructions":"...","max_items":1,"lookback_hours":24,"policy":{{"research_type":"technical_product_update|academic_research|company_financials|general_news","source_preference":["official","docs","github","paper","media"],"evidence_requirement":"official_or_multi_source|official_required|paper_or_primary_source|primary_financial_source_required|multi_source","ranking_objective":"confidence_first|personal_relevance_first|novelty_first|impact_first","verification_strictness":"low|medium|medium_high|high"}},"query_plan":[{{"query":"...","intent":"official|docs|repo|paper|technical|media|latest|financial_filing|transcript","priority":0.9}}]}}。

## 要求
要求：topic 只保留研究对象，不要包含“调研/最多几条/高可信”等控制语；instructions 保留可信度、来源偏好、个人相关性、语言、排除项等约束；policy 根据研究类型决定证据要求和排序目标；max_items 取 1 到 20；lookback_hours 取 1 到 720；query_plan 最多使用剩余查询预算，覆盖 primary source、repo/docs/paper/media 等不同证据角度。如果用户没有指定某项，使用默认值。

## 当前输入
原始 topic/request：{topic}
已有 instructions：{instructions}
默认 max_items：{max_items}
默认时间窗口小时数：{lookback_hours}
总查询预算：{max_queries}
初始探索查询预算：{max_exploration}
证据验证查询预算：{max_verification}
订阅 seed queries：{seed_queries}""",
    ),
    'knowledge.consolidation.source': PromptSpec(
        name='knowledge.consolidation.source', version='2026-10-27.v1-md1', owner='knowledge_consolidation',
        template="""

## 来源{index}
{title}
{content}""",
    ),
    'knowledge.consolidation.draft': PromptSpec(
        name='knowledge.consolidation.draft', version='2026-10-27.v1-md1', owner='knowledge_consolidation',
        template="""

## 任务
请把下面关于「{topic}」的多条笔记整理成一篇结构化知识综述。合并重复内容、保留关键事实、用小标题组织，并在开头概述主题。

## 来源材料
{sources}""",
    ),
    'artifacts.image.question_default': PromptSpec(
        name='artifacts.image.question_default', version='2026-10-27.v1', owner='artifacts',
        template='请概述图片内容',
    ),
    'artifacts.image.describe': PromptSpec(
        name='artifacts.image.describe', version='2026-10-27.v1', owner='artifacts',
        template='客观描述附件可见内容并回答用户问题；不要声称已保存。\n用户请求：{question}',
    ),
    'knowledge.gap_question': PromptSpec(
        name='knowledge.gap_question', version='2026-10-27.v1-md1', owner='knowledge_gap',
        template="""

## 任务与输出
把下面的个人知识库缺口改写成一句自然、友好、简洁的中文提问。只输出问题本身。

## 输入
缺口类型：{gap_type}
相关实体：{entities}
默认问法：{question}""",
    ),
    'knowledge.gap_no_entities': PromptSpec(
        name='knowledge.gap_no_entities', version='2026-10-27.v1', owner='knowledge_gap',
        template='无',
    ),
    'tools.context_missing': PromptSpec(
        name='tools.context_missing', version='2026-10-27.v1', owner='tools',
        template='工具缺少受信执行上下文。',
    ),
    'tools.execution_failed': PromptSpec(
        name='tools.execution_failed', version='2026-10-27.v1', owner='tool_gateway',
        template='工具执行失败。',
    ),
    'tools.web_read.domain_denied': PromptSpec(
        name='tools.web_read.domain_denied', version='2026-10-27.v1', owner='web_read',
        template='目标域名不在允许列表中，未读取正文。',
    ),
    'tools.web_read.no_body': PromptSpec(
        name='tools.web_read.no_body', version='2026-10-27.v1', owner='web_read',
        template='服务提供方未返回可读正文。',
    ),
    'tools.web_read.failed': PromptSpec(
        name='tools.web_read.failed', version='2026-10-27.v1', owner='web_read',
        template='网页读取失败：{detail}',
    ),
    'tools.web_read.transient': PromptSpec(
        name='tools.web_read.transient', version='2026-10-27.v1', owner='web_read',
        template='网页读取暂时失败：{detail}',
    ),
    'tools.web_read.undelivered': PromptSpec(
        name='tools.web_read.undelivered', version='2026-10-27.v1', owner='web_read',
        template='网页读取未交付正文：{detail}',
    ),
    'tools.python.acceptance_missing': PromptSpec(
        name='tools.python.acceptance_missing', version='2026-10-27.v1', owner='python_execution',
        template='Python执行请求缺少已接受记录。',
    ),
    'tools.python.read_receipt': PromptSpec(
        name='tools.python.read_receipt', version='2026-10-27.v1', owner='python_execution',
        template='请读回执和诊断原件',
    ),
    'tools.python.status': PromptSpec(
        name='tools.python.status', version='2026-10-27.v1', owner='python_execution',
        template='Python实际执行状态：{status}；{detail}',
    ),
    'tools.experiment.acceptance_missing': PromptSpec(
        name='tools.experiment.acceptance_missing', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验请求缺少已接受记录。',
    ),
    'tools.experiment.read_receipt': PromptSpec(
        name='tools.experiment.read_receipt', version='2026-10-27.v1', owner='retrieval_experiment',
        template='详见实际回执',
    ),
    'tools.experiment.status': PromptSpec(
        name='tools.experiment.status', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验状态：{status}；{detail}',
    ),
    'tools.artifact.acceptance_missing': PromptSpec(
        name='tools.artifact.acceptance_missing', version='2026-10-27.v1', owner='artifacts',
        template='保存请求没有与本次执行身份绑定的已接受记录。',
    ),
    'tools.verification.criteria_coverage': PromptSpec(
        name='tools.verification.criteria_coverage', version='2026-10-27.v1', owner='interaction_verifier',
        template='最终核验模型输出未按当前 criterion_id 恰好覆盖每个验收项，不能形成核验回执。',
    ),
    'tools.graph.unconfigured': PromptSpec(
        name='tools.graph.unconfigured', version='2026-10-27.v1', owner='graph_search',
        template='图谱未配置或未启用。',
    ),
    'tools.graph.unavailable': PromptSpec(
        name='tools.graph.unavailable', version='2026-10-27.v1', owner='graph_search',
        template='图谱检索不可用。',
    ),
    'tools.research.run_unavailable': PromptSpec(
        name='tools.research.run_unavailable', version='2026-10-27.v1', owner='research',
        template='未找到该用户的 Research run。',
    ),
    'artifacts.ref_unavailable': PromptSpec(
        name='artifacts.ref_unavailable', version='2026-10-27.v1', owner='artifacts',
        template='文件ID不在当前可读集合中，或对应多个不同的确切引用。',
    ),
    'artifacts.ref_owner_mismatch': PromptSpec(
        name='artifacts.ref_owner_mismatch', version='2026-10-27.v1', owner='artifacts',
        template='文件ID不属于当前主体的Artifact。',
    ),
    'python_execution.authorization': PromptSpec(
        name='python_execution.authorization', version='2026-10-27.v1', owner='python_execution',
        template='本主体未获Python执行部署授权',
    ),
    'python_execution.request_digest': PromptSpec(
        name='python_execution.request_digest', version='2026-10-27.v1', owner='python_execution',
        template='Python请求与已接受摘要不同',
    ),
    'python_execution.accepted_deployment': PromptSpec(
        name='python_execution.accepted_deployment', version='2026-10-27.v1', owner='python_execution',
        template='Python请求未被本run按当前部署接受',
    ),
    'python_execution.receipt_command': PromptSpec(
        name='python_execution.receipt_command', version='2026-10-27.v1', owner='python_execution',
        template='Python回执缺少冻结Command',
    ),
    'python_execution.execution_command': PromptSpec(
        name='python_execution.execution_command', version='2026-10-27.v1', owner='python_execution',
        template='Python执行记录缺少冻结Command',
    ),
    'python_execution.recovery_fact': PromptSpec(
        name='python_execution.recovery_fact', version='2026-10-27.v1', owner='python_execution',
        template='Python恢复结果与已保存进程事实不同',
    ),
    'python_execution.input_owner': PromptSpec(
        name='python_execution.input_owner', version='2026-10-27.v1', owner='python_execution',
        template='Python只能读取本主体的确切Artifact',
    ),
    'python_execution.input_boundary': PromptSpec(
        name='python_execution.input_boundary', version='2026-10-27.v1', owner='python_execution',
        template='Python输入身份或字节长度超过边界',
    ),
    'python_execution.input_changed': PromptSpec(
        name='python_execution.input_changed', version='2026-10-27.v1', owner='python_execution',
        template='Python读取期间Artifact身份发生变化',
    ),
    'python_execution.budget_exhausted': PromptSpec(
        name='python_execution.budget_exhausted', version='2026-10-27.v1', owner='python_execution',
        template='当前run执行额度或绝对截止已耗尽',
    ),
    'python_execution.input_budget_exhausted': PromptSpec(
        name='python_execution.input_budget_exhausted', version='2026-10-27.v1', owner='python_execution',
        template='准备Python输入时当前run截止或额度已耗尽',
    ),
    'python_execution.timer_resolution': PromptSpec(
        name='python_execution.timer_resolution', version='2026-10-27.v1', owner='python_execution',
        template='Python剩余额度低于执行时钟精度',
    ),
    'python_execution.command_request': PromptSpec(
        name='python_execution.command_request', version='2026-10-27.v1', owner='python_execution',
        template='冻结Python Command与已接受请求或部署不同',
    ),
    'python_execution.program_bytes': PromptSpec(
        name='python_execution.program_bytes', version='2026-10-27.v1', owner='python_execution',
        template='冻结Python程序与已接受原字节不同',
    ),
    'python_execution.original_command': PromptSpec(
        name='python_execution.original_command', version='2026-10-27.v1', owner='python_execution',
        template='Python原件与冻结Command不同',
    ),
    'python_execution.dispatching_result': PromptSpec(
        name='python_execution.dispatching_result', version='2026-10-27.v1', owner='python_execution',
        template='执行器不能以dispatching作为执行结果',
    ),
    'python_execution.capture_budget': PromptSpec(
        name='python_execution.capture_budget', version='2026-10-27.v1', owner='python_execution',
        template='执行器返回超过冻结捕获额度的字节',
    ),
    'python_execution.stdout_limit': PromptSpec(
        name='python_execution.stdout_limit', version='2026-10-27.v1', owner='python_execution',
        template='stdout已达到捕获限制；原件只包含实际捕获字节。',
    ),
    'python_execution.stderr_limit': PromptSpec(
        name='python_execution.stderr_limit', version='2026-10-27.v1', owner='python_execution',
        template='stderr已达到捕获限制；原件只包含实际捕获字节。',
    ),
    'python_execution.output_unavailable': PromptSpec(
        name='python_execution.output_unavailable', version='2026-10-27.v1', owner='python_execution',
        template='原作业输出不可恢复；未重新运行程序，不能按空输出来解释。',
    ),
    'python_execution.invalid_utf8': PromptSpec(
        name='python_execution.invalid_utf8', version='2026-10-27.v1', owner='python_execution',
        template='{stream}含无效UTF-8；保留捕获原字节，不提供文本预览。',
    ),
    'retrieval_experiment.authorization': PromptSpec(
        name='retrieval_experiment.authorization', version='2026-10-27.v1', owner='retrieval_experiment',
        template='本主体未获实验部署授权',
    ),
    'retrieval_experiment.request_digest': PromptSpec(
        name='retrieval_experiment.request_digest', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验请求与已接受摘要不一致',
    ),
    'retrieval_experiment.accepted_deployment': PromptSpec(
        name='retrieval_experiment.accepted_deployment', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验请求未被本run按原部署接受',
    ),
    'retrieval_experiment.result_not_successful': PromptSpec(
        name='retrieval_experiment.result_not_successful', version='2026-10-27.v1', owner='retrieval_experiment',
        template='结果必须来自本run已提交的成功实验',
    ),
    'retrieval_experiment.program_unreadable': PromptSpec(
        name='retrieval_experiment.program_unreadable', version='2026-10-27.v1', owner='retrieval_experiment',
        template='程序或配置不属于当前可读集合',
    ),
    'retrieval_experiment.program_not_draft': PromptSpec(
        name='retrieval_experiment.program_not_draft', version='2026-10-27.v1', owner='retrieval_experiment',
        template='程序或配置必须是本run对应类型的正式草稿',
    ),
    'retrieval_experiment.development_after_final': PromptSpec(
        name='retrieval_experiment.development_after_final', version='2026-10-27.v1', owner='retrieval_experiment',
        template='最终评测派发后不能继续开发调参',
    ),
    'retrieval_experiment.duplicate_input': PromptSpec(
        name='retrieval_experiment.duplicate_input', version='2026-10-27.v1', owner='retrieval_experiment',
        template='输入结果不能重复',
    ),
    'retrieval_experiment.input_rankings': PromptSpec(
        name='retrieval_experiment.input_rankings', version='2026-10-27.v1', owner='retrieval_experiment',
        template='输入排名数据或深度不满足开发配置',
    ),
    'retrieval_experiment.freeze_not_submitted': PromptSpec(
        name='retrieval_experiment.freeze_not_submitted', version='2026-10-27.v1', owner='retrieval_experiment',
        template='只能执行本run已提交的冻结方案',
    ),
    'retrieval_experiment.deployment_changed': PromptSpec(
        name='retrieval_experiment.deployment_changed', version='2026-10-27.v1', owner='retrieval_experiment',
        template='部署原件发生变化',
    ),
    'retrieval_experiment.clock': PromptSpec(
        name='retrieval_experiment.clock', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验时钟必须提供aware UTC时间',
    ),
    'retrieval_experiment.deadline': PromptSpec(
        name='retrieval_experiment.deadline', version='2026-10-27.v1', owner='retrieval_experiment',
        template='实验时间额度已耗尽',
    ),
    'retrieval_experiment.snapshot_changed': PromptSpec(
        name='retrieval_experiment.snapshot_changed', version='2026-10-27.v1', owner='retrieval_experiment',
        template='已接受输入快照已变化',
    ),
    'retrieval_experiment.private_digest': PromptSpec(
        name='retrieval_experiment.private_digest', version='2026-10-27.v1', owner='retrieval_experiment',
        template='私有评分原件摘要不一致',
    ),
    'retrieval_experiment.freeze_after_final': PromptSpec(
        name='retrieval_experiment.freeze_after_final', version='2026-10-27.v1', owner='retrieval_experiment',
        template='最终评测派发后不能替换冻结方案',
    ),
    'retrieval_experiment.projection_digest': PromptSpec(
        name='retrieval_experiment.projection_digest', version='2026-10-27.v1', owner='retrieval_experiment',
        template='公开文本投影与部署manifest摘要不同',
    ),
    'retrieval_experiment.unknown': PromptSpec(
        name='retrieval_experiment.unknown', version='2026-10-27.v1', owner='retrieval_experiment',
        template='执行终态尚未知，原预留额度保留。',
    ),
    'experiment_delivery.unsettled': PromptSpec(
        name='experiment_delivery.unsettled', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='实验仍有尚未确认的执行，不能完整交付',
    ),
    'experiment_delivery.successful_execution': PromptSpec(
        name='experiment_delivery.successful_execution', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='成功回执缺少对应的实际成功执行',
    ),
    'experiment_delivery.final_missing': PromptSpec(
        name='experiment_delivery.final_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='尚无成功执行的完整最终评测',
    ),
    'experiment_delivery.final_ambiguous': PromptSpec(
        name='experiment_delivery.final_ambiguous', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='存在互不相同的最终方案，不能由交付端代选',
    ),
    'experiment_delivery.freeze_missing': PromptSpec(
        name='experiment_delivery.freeze_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='最终评测之前没有本 run 的合法冻结',
    ),
    'experiment_delivery.frozen_file_missing': PromptSpec(
        name='experiment_delivery.frozen_file_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='原冻结文件不存在',
    ),
    'experiment_delivery.artifact_missing': PromptSpec(
        name='experiment_delivery.artifact_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='交付所需原文件不存在',
    ),
    'experiment_delivery.result_fact_missing': PromptSpec(
        name='experiment_delivery.result_fact_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='结果没有本 run 的实际成功记录',
    ),
    'experiment_delivery.result_artifact_missing': PromptSpec(
        name='experiment_delivery.result_artifact_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='结果所需原文件不存在',
    ),
    'experiment_delivery.candidate_source_missing': PromptSpec(
        name='experiment_delivery.candidate_source_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='实际候选缺少源码引用',
    ),
    'experiment_delivery.development_missing': PromptSpec(
        name='experiment_delivery.development_missing', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='需要完整成功的 BM25 与 dense 开发实验',
    ),
    'experiment_delivery.selected_identity': PromptSpec(
        name='experiment_delivery.selected_identity', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='冻结选中项不是冻结之前的开发结果',
    ),
    'experiment_delivery.final_split': PromptSpec(
        name='experiment_delivery.final_split', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='最终回执包含其他 split 的实验结果',
    ),
    'experiment_delivery.final_baseline': PromptSpec(
        name='experiment_delivery.final_baseline', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='最终评测缺少实际 BM25 基线',
    ),
    'experiment_delivery.final_selected': PromptSpec(
        name='experiment_delivery.final_selected', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='最终评测缺少唯一的冻结选中结果',
    ),
    'experiment_delivery.coverage': PromptSpec(
        name='experiment_delivery.coverage', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='实验不是当前完整数据集的结果',
    ),
    'experiment_delivery.query_facts': PromptSpec(
        name='experiment_delivery.query_facts', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='查询执行事实不完整或与实际排名不同',
    ),
    'experiment_delivery.per_query': PromptSpec(
        name='experiment_delivery.per_query', version='2026-10-27.v1', owner='retrieval_experiment_completion',
        template='逐查询指标没有覆盖完整查询集',
    ),
    'policy.deny_user': PromptSpec(
        name='policy.deny_user', version='2026-10-27.v1', owner='policy',
        template='用户 {user_id} 被策略禁止执行该动作。',
    ),
    'policy.deny_source': PromptSpec(
        name='policy.deny_source', version='2026-10-27.v1', owner='policy',
        template='入口来源 {source} 被策略禁止。',
    ),
    'policy.deny_tool': PromptSpec(
        name='policy.deny_tool', version='2026-10-27.v1', owner='policy',
        template='工具 {tool_name} 被策略禁止调用。',
    ),
    'policy.deny_scope': PromptSpec(
        name='policy.deny_scope', version='2026-10-27.v1', owner='policy',
        template='权限域 {scope} 被策略禁止。',
    ),
    'policy.tool_confirmation': PromptSpec(
        name='policy.tool_confirmation', version='2026-10-27.v1', owner='policy',
        template='工具 {tool_name} 为高风险操作，需用户确认后执行。',
    ),
    'policy.agent_confirmation': PromptSpec(
        name='policy.agent_confirmation', version='2026-10-27.v1', owner='policy',
        template='Agent {agent_id} 为高风险委托，需用户确认后执行。',
    ),
    'policy.react_not_allowed': PromptSpec(
        name='policy.react_not_allowed', version='2026-10-27.v1', owner='policy',
        template='工具 {tool_name} 不在当前 ReAct 允许列表中。',
    ),
    'policy.react_blocked': PromptSpec(
        name='policy.react_blocked', version='2026-10-27.v1', owner='policy',
        template='工具 {tool_name} 不允许在 ReAct 自主执行中调用。',
    ),
    'policy.owner_mismatch': PromptSpec(
        name='policy.owner_mismatch', version='2026-10-27.v1', owner='policy',
        template='资源 {resource} 不属于用户 {user_id}。',
    ),
    'policy.memory_delete_confirmation': PromptSpec(
        name='policy.memory_delete_confirmation', version='2026-10-27.v1', owner='policy',
        template='删除长期记忆需要确认后执行。',
    ),
    'policy.source_not_allowed': PromptSpec(
        name='policy.source_not_allowed', version='2026-10-27.v1', owner='policy',
        template='入口来源 {source} 不在允许列表中。',
    ),
    'policy.user_not_allowed': PromptSpec(
        name='policy.user_not_allowed', version='2026-10-27.v1', owner='policy',
        template='用户 {user_id} 不在允许列表中。',
    ),
    'tool_gateway.not_found': PromptSpec(
        name='tool_gateway.not_found', version='2026-10-27.v1', owner='tool_gateway',
        template='未找到工具：{tool_name}',
    ),
    'tool_gateway.rate_limited': PromptSpec(
        name='tool_gateway.rate_limited', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 触发速率限制，请稍后再试。',
    ),
    'tool_gateway.timed_out': PromptSpec(
        name='tool_gateway.timed_out', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 执行超时（>{seconds}s）。',
    ),
    'tool_gateway.not_executed': PromptSpec(
        name='tool_gateway.not_executed', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 未执行。',
    ),
    'tool_gateway.no_pending_call': PromptSpec(
        name='tool_gateway.no_pending_call', version='2026-10-27.v1', owner='tool_gateway',
        template='工具节点未收到待执行的工具调用。',
    ),
    'tool_gateway.idempotency_key_missing': PromptSpec(
        name='tool_gateway.idempotency_key_missing', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 执行高风险确认动作时缺少 idempotency_key。',
    ),
    'tool_gateway.idempotency_pending': PromptSpec(
        name='tool_gateway.idempotency_pending', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 的同一幂等调用正在执行且尚无可重放 receipt（idempotency_key={key}）。',
    ),
    'tool_gateway.domain_denied': PromptSpec(
        name='tool_gateway.domain_denied', version='2026-10-27.v1', owner='tool_gateway',
        template='工具 {tool_name} 的目标 URL 不在允许域名列表中。',
    ),
    'tool_gateway.workflow_not_found': PromptSpec(
        name='tool_gateway.workflow_not_found', version='2026-10-27.v1', owner='tool_gateway',
        template='未找到工作流工具：{tool_name}',
    ),
    'artifact_search.engine_missing': PromptSpec(
        name='artifact_search.engine_missing', version='2026-10-27.v1', owner='artifact_search',
        template='未安装 ripgrep，无法执行正文搜索。',
    ),
    'artifact_search.output_limit': PromptSpec(
        name='artifact_search.output_limit', version='2026-10-27.v1', owner='artifact_search',
        template='搜索引擎输出超过容量，未返回不完整匹配；请缩小搜索表达式。',
    ),
    'artifact_search.timeout': PromptSpec(
        name='artifact_search.timeout', version='2026-10-27.v1', owner='artifact_search',
        template='正文搜索超时，未将未完成搜索解释为零匹配。',
    ),
    'artifact_search.failed': PromptSpec(
        name='artifact_search.failed', version='2026-10-27.v1', owner='artifact_search',
        template='搜索表达式或引擎执行失败：',
    ),
    'web_source.body_limit': PromptSpec(
        name='web_source.body_limit', version='2026-10-27.v1', owner='web_source',
        template='来源正文超过单次容量，未交付不完整正文。',
    ),
    'python_backend.deployment': PromptSpec(
        name='python_backend.deployment', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python Command与固定执行部署不同',
    ),
    'python_backend.directory_symlink': PromptSpec(
        name='python_backend.directory_symlink', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python执行目录不得包含符号链接',
    ),
    'python_backend.directory_escape': PromptSpec(
        name='python_backend.directory_escape', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python执行目录越界',
    ),
    'python_backend.job_command': PromptSpec(
        name='python_backend.job_command', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python原作业与冻结Command不同',
    ),
    'python_backend.job_command_missing': PromptSpec(
        name='python_backend.job_command_missing', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python原作业缺少冻结Command，禁止重新执行',
    ),
    'python_backend.input_bytes': PromptSpec(
        name='python_backend.input_bytes', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python后端输入与冻结原字节不同',
    ),
    'python_backend.input_command': PromptSpec(
        name='python_backend.input_command', version='2026-10-27.v1', owner='python_execution_backend',
        template='执行输入与冻结Python Command不同',
    ),
    'python_backend.job_identity': PromptSpec(
        name='python_backend.job_identity', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python工作目录缺少原身份，禁止重新执行',
    ),
    'python_backend.input_symlink': PromptSpec(
        name='python_backend.input_symlink', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python输入目录不得是符号链接',
    ),
    'python_backend.input_snapshot': PromptSpec(
        name='python_backend.input_snapshot', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python输入快照冲突',
    ),
    'python_backend.cleanup_identity': PromptSpec(
        name='python_backend.cleanup_identity', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python清理未确认匹配的停止容器',
    ),
    'python_backend.job_record_symlink': PromptSpec(
        name='python_backend.job_record_symlink', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python原作业记录不得是符号链接',
    ),
    'python_backend.job_binding': PromptSpec(
        name='python_backend.job_binding', version='2026-10-27.v1', owner='python_execution_backend',
        template='Python后端作业与冻结Command不符',
    ),
    'python_recovery.identity_missing': PromptSpec(
        name='python_recovery.identity_missing', version='2026-10-27.v1', owner='python_execution_recovery',
        template='候选目录缺少原身份，禁止重新执行',
    ),
    'python_recovery.input_digest': PromptSpec(
        name='python_recovery.input_digest', version='2026-10-27.v1', owner='python_execution_recovery',
        template='恢复Python需要确切输入摘要或原件',
    ),
    'python_recovery.identity_mismatch': PromptSpec(
        name='python_recovery.identity_mismatch', version='2026-10-27.v1', owner='python_execution_recovery',
        template='原候选身份与恢复请求不同',
    ),
    'python_recovery.capture_binding': PromptSpec(
        name='python_recovery.capture_binding', version='2026-10-27.v1', owner='python_execution_recovery',
        template='原Python捕获与作业身份或限额不同',
    ),
    'python_recovery.output_incomplete': PromptSpec(
        name='python_recovery.output_incomplete', version='2026-10-27.v1', owner='python_execution_recovery',
        template='原候选输出不完整',
    ),
    'python_recovery.stderr_incomplete': PromptSpec(
        name='python_recovery.stderr_incomplete', version='2026-10-27.v1', owner='python_execution_recovery',
        template='原Python stderr捕获不完整',
    ),
    'experiment_backend.directory_escape': PromptSpec(
        name='experiment_backend.directory_escape', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='实验目录越界',
    ),
    'experiment_backend.deployment_stale': PromptSpec(
        name='experiment_backend.deployment_stale', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='实验部署身份已失效',
    ),
    'experiment_backend.execution_identity': PromptSpec(
        name='experiment_backend.execution_identity', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='原后端执行身份冲突',
    ),
    'experiment_backend.filename': PromptSpec(
        name='experiment_backend.filename', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='执行暂存文件名不合法',
    ),
    'experiment_backend.staging_bytes': PromptSpec(
        name='experiment_backend.staging_bytes', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='执行暂存原字节发生变化',
    ),
    'experiment_backend.input_binding': PromptSpec(
        name='experiment_backend.input_binding', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='实际输入与Command及部署许可不同',
    ),
    'experiment_backend.diagnostic_path': PromptSpec(
        name='experiment_backend.diagnostic_path', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断文件越出当前命令目录',
    ),
    'experiment_backend.diagnostic_symlink': PromptSpec(
        name='experiment_backend.diagnostic_symlink', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断路径不得包含符号链接',
    ),
    'experiment_backend.diagnostic_file': PromptSpec(
        name='experiment_backend.diagnostic_file', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断必须来自普通文件',
    ),
    'experiment_backend.diagnostic_snapshot': PromptSpec(
        name='experiment_backend.diagnostic_snapshot', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断捕获部分提交，缺少原结果快照',
    ),
    'experiment_backend.diagnostic_original': PromptSpec(
        name='experiment_backend.diagnostic_original', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断捕获部分提交，缺少固定原件',
    ),
    'experiment_backend.diagnostic_job': PromptSpec(
        name='experiment_backend.diagnostic_job', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断捕获与原作业身份不一致',
    ),
    'experiment_backend.diagnostic_authorization': PromptSpec(
        name='experiment_backend.diagnostic_authorization', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断不属于当前命令的许可候选作业',
    ),
    'experiment_backend.diagnostic_source': PromptSpec(
        name='experiment_backend.diagnostic_source', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断缺少命令绑定的源码',
    ),
    'experiment_backend.diagnostic_input': PromptSpec(
        name='experiment_backend.diagnostic_input', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断输入角色或源码配置摘要与命令不同',
    ),
    'experiment_backend.diagnostic_freeze': PromptSpec(
        name='experiment_backend.diagnostic_freeze', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断源码配置摘要与冻结不同',
    ),
    'experiment_backend.diagnostic_baseline': PromptSpec(
        name='experiment_backend.diagnostic_baseline', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='最终候选诊断缺少实际基线结果',
    ),
    'experiment_backend.diagnostic_parent': PromptSpec(
        name='experiment_backend.diagnostic_parent', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='最终候选诊断缺少实际父结果',
    ),
    'experiment_backend.diagnostic_parent_recipe': PromptSpec(
        name='experiment_backend.diagnostic_parent_recipe', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='最终候选诊断的父生成规则与冻结不同',
    ),
    'experiment_backend.diagnostic_digest': PromptSpec(
        name='experiment_backend.diagnostic_digest', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断作业或公开输入摘要与当前命令不同',
    ),
    'experiment_backend.diagnostic_size': PromptSpec(
        name='experiment_backend.diagnostic_size', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断原件长度与保存快照或捕获额度不同',
    ),
    'experiment_backend.diagnostic_changed': PromptSpec(
        name='experiment_backend.diagnostic_changed', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断读取期间原件长度发生变化',
    ),
    'experiment_backend.diagnostic_stdout_digest': PromptSpec(
        name='experiment_backend.diagnostic_stdout_digest', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选诊断 stdout 原字节摘要不符',
    ),
    'experiment_backend.diagnostic_unknown_nonempty': PromptSpec(
        name='experiment_backend.diagnostic_unknown_nonempty', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='旧未知候选捕获缺少容器身份却有非空内容',
    ),
    'experiment_backend.diagnostic_unbound_nonempty': PromptSpec(
        name='experiment_backend.diagnostic_unbound_nonempty', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选身份尚未确定却存在非空诊断捕获',
    ),
    'experiment_backend.stdout_encoding': PromptSpec(
        name='experiment_backend.stdout_encoding', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选 stdout 保留捕获原字节，含非 UTF-8 内容，不能作为 UTF-8 文本直接读取。',
    ),
    'experiment_backend.stderr_projection': PromptSpec(
        name='experiment_backend.stderr_projection', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='候选 stderr 为 UTF-8 诊断投影，非原字节；',
    ),
    'experiment_backend.stderr_replaced': PromptSpec(
        name='experiment_backend.stderr_replaced', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='发生非法字节替换；',
    ),
    'experiment_backend.stderr_not_replaced': PromptSpec(
        name='experiment_backend.stderr_not_replaced', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='未发生非法字节替换；',
    ),
    'experiment_backend.stderr_truncated': PromptSpec(
        name='experiment_backend.stderr_truncated', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='因发布字节额度在 UTF-8 字符边界截断。',
    ),
    'experiment_backend.stderr_not_truncated': PromptSpec(
        name='experiment_backend.stderr_not_truncated', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='未因发布字节额度截断。',
    ),
    'experiment_backend.result_path': PromptSpec(
        name='experiment_backend.result_path', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='后端结果路径越界',
    ),
    'experiment_backend.public_projection': PromptSpec(
        name='experiment_backend.public_projection', version='2026-10-27.v1', owner='retrieval_experiment_backend',
        template='公开文本投影与实际prepare产物摘要不同',
    ),
    'experiment_results.artifact_size': PromptSpec(
        name='experiment_results.artifact_size', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='实验原字节大小与 Artifact 登记不同',
    ),
    'experiment_results.publication_identity': PromptSpec(
        name='experiment_results.publication_identity', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='实验发布文件与原 result 身份不一致',
    ),
    'experiment_results.projection_binding': PromptSpec(
        name='experiment_results.projection_binding', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='数据投影与发布绑定不同',
    ),
    'experiment_results.projection_prepared': PromptSpec(
        name='experiment_results.projection_prepared', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='数据投影与部署实际准备数据不同',
    ),
    'experiment_rules.development_only': PromptSpec(
        name='experiment_rules.development_only', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='只能从开发结果冻结方案',
    ),
    'experiment_rules.coverage': PromptSpec(
        name='experiment_rules.coverage', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='冻结结果缺少完整且一致的开发查询执行事实',
    ),
    'experiment_rules.input_rankings': PromptSpec(
        name='experiment_rules.input_rankings', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='冻结提供的输入排名与实际运行不一致',
    ),
    'experiment_rules.baseline_inputs': PromptSpec(
        name='experiment_rules.baseline_inputs', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='首版仅冻结同数据开发集的受信基线输入',
    ),
    'experiment_rules.source_identity': PromptSpec(
        name='experiment_rules.source_identity', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='候选源码或配置与已执行版本不一致',
    ),
    'experiment_rules.final_dataset': PromptSpec(
        name='experiment_rules.final_dataset', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='test 数据与冻结的数据快照不一致',
    ),
    'experiment_rules.query_overlap': PromptSpec(
        name='experiment_rules.query_overlap', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='test 查询与开发查询重叠',
    ),
    'experiment_rules.final_recipe': PromptSpec(
        name='experiment_rules.final_recipe', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='实际 test 实现或模型与冻结版本不一致',
    ),
    'experiment_rules.final_candidate': PromptSpec(
        name='experiment_rules.final_candidate', version='2026-10-27.v1', owner='retrieval_experiment_rules',
        template='实际 test 候选身份与冻结方案不一致',
    ),
    'experiment_rankings.coverage': PromptSpec(
        name='experiment_rankings.coverage', version='2026-10-27.v1', owner='retrieval_experiment_rankings',
        template='排名必须完整且恰好包含当前 split 的全部查询',
    ),
    'experiment_rankings.scores': PromptSpec(
        name='experiment_rankings.scores', version='2026-10-27.v1', owner='retrieval_experiment_rankings',
        template='查询 {query_id} 的排名必须为文档分数字典',
    ),
    'experiment_rankings.depth': PromptSpec(
        name='experiment_rankings.depth', version='2026-10-27.v1', owner='retrieval_experiment_rankings',
        template='查询 {query_id} 超过 retrieve_k',
    ),
    'experiment_rankings.document': PromptSpec(
        name='experiment_rankings.document', version='2026-10-27.v1', owner='retrieval_experiment_rankings',
        template='查询 {query_id} 包含未知文档：{document_id}',
    ),
    'experiment_rankings.finite_score': PromptSpec(
        name='experiment_rankings.finite_score', version='2026-10-27.v1', owner='retrieval_experiment_rankings',
        template='查询 {query_id} 的文档 {document_id} 不是有限数值分数',
    ),
    'experiment_controller.dataset_digest': PromptSpec(
        name='experiment_controller.dataset_digest', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='数据产物摘要不匹配：{artifact_name}',
    ),
    'experiment_controller.result_digest': PromptSpec(
        name='experiment_controller.result_digest', version='2026-10-27.v1', owner='retrieval_experiment_results',
        template='结果产物摘要不匹配：{path}',
    ),
    'knowledge.consolidation.topic_missing': PromptSpec(
        name='knowledge.consolidation.topic_missing', version='2026-10-27.v1', owner='knowledge_consolidation',
        template='请提供要整理的知识主题。',
    ),
    'knowledge.consolidation.notes_missing': PromptSpec(
        name='knowledge.consolidation.notes_missing', version='2026-10-27.v1', owner='knowledge_consolidation',
        template='至少需要两条属于当前用户的相关笔记才能整理。',
    ),
    'knowledge.consolidation.draft_missing': PromptSpec(
        name='knowledge.consolidation.draft_missing', version='2026-10-27.v1', owner='knowledge_consolidation',
        template='未能生成综述草稿。',
    ),
    'tools.knowledge.consolidation_failed': PromptSpec(
        name='tools.knowledge.consolidation_failed', version='2026-10-27.v1', owner='knowledge_consolidation',
        template='主题整理失败。',
    ),
    'tools.research.digest_missing': PromptSpec(
        name='tools.research.digest_missing', version='2026-10-27.v1', owner='research',
        template='研究未生成简报。',
    ),
    'python_validation.filename': PromptSpec(
        name='python_validation.filename', version='2026-10-27.v1', owner='python_execution_validation',
        template='输入必须是合法、非保留的1—64字符ASCII平面文件名',
    ),
    'python_validation.program_size': PromptSpec(
        name='python_validation.program_size', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python程序超过128 KiB',
    ),
    'python_validation.input_names': PromptSpec(
        name='python_validation.input_names', version='2026-10-27.v1', owner='python_execution_validation',
        template='输入文件名不能重复或仅大小写不同',
    ),
    'python_validation.input_bytes': PromptSpec(
        name='python_validation.input_bytes', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python输入长度或原字节摘要不符',
    ),
    'python_validation.deadline': PromptSpec(
        name='python_validation.deadline', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python deadline必须晚于接受时间',
    ),
    'python_validation.reservation': PromptSpec(
        name='python_validation.reservation', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python预留超过冻结限额或deadline',
    ),
    'python_validation.program_identity': PromptSpec(
        name='python_validation.program_identity', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python程序身份或长度不合法',
    ),
    'python_validation.input_total': PromptSpec(
        name='python_validation.input_total', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python输入重复或超过64 MiB',
    ),
    'python_validation.input_owner': PromptSpec(
        name='python_validation.input_owner', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python Command只绑定本主体的Artifact',
    ),
    'python_validation.command_digest': PromptSpec(
        name='python_validation.command_digest', version='2026-10-27.v1', owner='python_execution_validation',
        template='Python Command摘要不一致',
    ),
    'experiment_validation.input_digest': PromptSpec(
        name='experiment_validation.input_digest', version='2026-10-27.v1', owner='retrieval_experiment_validation',
        template='实验快照与原字节摘要不符',
    ),
    'experiment_validation.deadline': PromptSpec(
        name='experiment_validation.deadline', version='2026-10-27.v1', owner='retrieval_experiment_validation',
        template='实验deadline必须晚于接受时间',
    ),
    'experiment_validation.command_digest': PromptSpec(
        name='experiment_validation.command_digest', version='2026-10-27.v1', owner='retrieval_experiment_validation',
        template='实验Command摘要不一致',
    ),
    'experiment_validation.input_owner': PromptSpec(
        name='experiment_validation.input_owner', version='2026-10-27.v1', owner='retrieval_experiment_validation',
        template='Command不保存其他主体或private标签引用',
    ),
    'web_source.response_limit': PromptSpec(
        name='web_source.response_limit', version='2026-10-27.v1', owner='web_source',
        template='网页响应超过 4 MiB 容量，未交付正文。',
    ),
    'tools.knowledge.note_unavailable': PromptSpec(
        name='tools.knowledge.note_unavailable', version='2026-10-27.v1', owner='knowledge_reading',
        template='未找到该用户可访问的笔记。',
    ),
    'research_validation.target_category': PromptSpec(
        name='research_validation.target_category', version='2026-10-27.v1', owner='research_verification',
        template='目标缺项须定位原验收编号；其他错误须定位当前 claim 片段或回答段落。',
    ),
    'verification.cited_support_rejection.explanation': PromptSpec(
        name='verification.cited_support_rejection.explanation', version='2026-10-27.v1', owner='interaction_verifier',
        template='本次提交的证据不足以支持所列草稿声明，暂不交付。这不证明原文没有依据或声明必然为假。请补充已有引用、继续取证或修订结论后重新提交；补充引用时可以保留有据的原稿，不必为了改稿而改变事实。',
    ),
}
