# Personal Agent 面试问答速查

这份文档用于面试时快速说明当前工程涉及的 Agent 关键知识点。重点不是背概念，而是把项目里的真实实现、工程取舍、风险边界讲清楚。

一句话介绍：

> 这是一个面向个人知识管理的 Agent 系统。它把用户的文本、网页、文件和对话结论沉淀为长期记忆，用 LangGraph 编排入口流程和 checkpoint，用 Postgres 保存 note/chunk 真源，用 Graphiti/structural retriever 做语义关系检索，用 Evidence/ContextPack 约束回答依据，用 ToolGateway 和 HITL 约束真实副作用。

## 1. 项目整体 Agent 架构

### Q1：这个项目解决什么问题？

它解决的是个人知识长期沉淀和可靠使用的问题。

用户可以把零散文本、网页、上传文件、对话结论采集进知识库；后续提问时，系统会从长期记忆、图谱关系、结构化检索和必要的网络搜索中召回证据，再基于证据回答。

它不是单纯聊天机器人，而是覆盖了：

- 入口统一：Web、CLI、飞书、前端工作台。
- 意图路由：ask、capture、delete、solidify、summarize、direct answer。
- 记忆写入：文本、链接、文件、对话固化。
- 检索问答：Graphiti、structural retriever、本地 Postgres、web search。
- 工具执行：capture、graph search、web search、delete note。
- 安全治理：PolicyEngine、PlanValidator、ToolGateway、HITL、幂等、审计事件。
- 可恢复流程：LangGraph checkpoint、interrupt/resume。
- 评测闭环：retrieval、ask quality、plan/replan、GraphRAG 对照。

### Q2：它为什么算 Agent，而不只是 RAG Bot？

普通 RAG Bot 通常只做“上传文档后检索回答”。这个工程有更完整的 Agent 闭环：

- 能识别用户意图并选择不同 workflow。
- 能调用工具产生真实系统动作。
- 能把信息写入长期记忆，而不是只读文档。
- 能规划高风险流程，例如删除知识和固化对话。
- 能在删除等副作用动作前中断等待用户确认。
- 能保存执行现场并恢复。
- 能把证据、工具结果、回答校验和事件流统一起来。

更准确的定位是：一个工程型个人知识 Agent，而不是通用自主 Agent。

### Q3：当前核心链路是什么？

典型入口链路：

```text
Web / CLI / Feishu
  -> AgentRuntime
  -> EntryOrchestrator / LangGraph orchestration graph
  -> Router 判断 intent
  -> 普通分支：ask / capture / summarize / direct_answer
  -> 计划分支：delete_knowledge / solidify_conversation
  -> 工具、记忆、检索、生成、校验
  -> EntryResult / SSE / 前端展示
```

关键代码：

- `src/personal_agent/agent/runtime.py`：AgentRuntime 组合根。
- `src/personal_agent/agent/entry_orchestrator.py`：entry 编排入口。
- `src/personal_agent/agent/orchestration_graph.py`：LangGraph 总流程。
- `src/personal_agent/agent/router.py`：意图路由。
- `src/personal_agent/agent/runtime_ask.py`：问答执行链路。
- `src/personal_agent/agent/ingestion_pipeline.py`：采集入库链路。

## 2. LangGraph 与可恢复编排

### Q1：LangGraph 在项目里承担什么价值？

LangGraph 不是为了“让模型更聪明”，而是为了把 Agent 流程变成可恢复状态机。

项目用 `AgentGraphState` 保存：

- `messages`：同一 thread 内的对话现场。
- `plan`：计划步骤、当前步骤、步骤结果。
- `react`：单步 ReAct 循环状态。
- `tool_tracking`：工具调用归属。
- `pending_confirmation`：等待用户确认的动作。
- `events`：结构化执行事件。

这样删除知识时可以先 `interrupt`，用户确认后用同一 `thread_id` resume，不需要重新规划或重新找目标。

### Q2：checkpoint 保存的是事实吗？

不是。checkpoint 保存的是短期执行现场，不是长期事实真源。

项目里有一个很重要的边界：

```text
LangGraph checkpoint：保存当前 thread 的执行现场
Postgres knowledge_notes：保存长期知识事实
```

对话历史里可能包含助手猜测、用户临时想法、废弃方案和错误回答，所以不能直接当长期知识。长期事实必须通过 capture 或 solidify 明确写入。

### Q3：plan_steps 和 execution_trace 有什么区别？

`plan_steps` 是真实会被执行和恢复的计划步骤，目前主要用于 `delete_knowledge` 和 `solidify_conversation`。

`execution_trace` 是普通固定分支的轻量执行说明，例如 ask/capture/direct answer，不代表一个可恢复的规划步骤图。

这样前端不会把普通问答路径误展示成“Agent 自主规划了很多步骤”。

## 3. 意图路由 Router

### Q1：Router 做什么？

Router 把入口文本分类为具体 intent，并输出风险、是否检索、是否工具、是否规划、是否确认、是否需要澄清等控制字段。

典型 intent：

- `ask`
- `capture_text`
- `capture_link`
- `capture_file`
- `delete_knowledge`
- `solidify_conversation`
- `summarize_thread`
- `direct_answer`
- `unknown`

### Q2：为什么 Router 不直接用关键词规则？

当前 Router 是 LLM-first，并在模型不可用时明确返回不可用提示，而不是用关键词硬猜。

原因是入口意图影响后续是否调用工具、是否删除数据、是否写长期记忆。错误路由的代价很高，所以宁愿保守失败，也不把“看起来像删除”的句子用规则直接送进高风险流程。

### Q3：Router 输出为什么要有 risk 和 confirmation？

因为 Agent 的关键不是只判断“用户想干什么”，还要判断“这个动作风险多大，能不能直接执行”。

例如：

- 普通问答：低风险，可直接执行。
- 采集文本：写长期记忆，中低风险。
- 删除知识：高风险，必须规划和确认。

这个风险字段会影响 PlanValidator、ToolGateway 和 HITL。

## 4. 规划层 Planning

### Q1：当前 planning 是怎么落地的？

当前 planning 已经落地为 Workflow / Step Planning Layer，而不是开放式自主 planner。

固定流程下沉到 `WorkflowSpec / WorkflowStepSpec`，由 `WorkflowRegistry` 按 intent 选择；只有 `delete_knowledge`、`solidify_conversation` 这类需要步骤状态、HITL 或 checkpoint 恢复的 workflow，才由 `DefaultTaskPlanner` 确定性投影成 `PlanStep`。规划路径不再让 LLM 临场生成流程拓扑；LLM 只在执行期的局部 decision node 里做语义判断，例如删除目标 resolve、固化草稿 compose、query understanding。

普通 ask、capture、summarize、direct answer 有自己的 workflow 分支，不需要进入步骤投影。真正投影成 `PlanStep` 并进入计划执行图的主要是：

- `delete_knowledge`
- `solidify_conversation`

它们的主干流程由 `WorkflowSpec.steps: WorkflowStepSpec[]` 显式声明，再投影成 `PlanStep`，用于步骤展示、校验、checkpoint、HITL 和事件流。投影后的 step 会保留 `workflow_id / workflow_version / workflow_step_id / projection_kind`，方便从运行时状态追溯回 workflow 契约。

### Q2：为什么删除知识要进入 planning？

删除是高风险副作用，不能让模型一句话就删。

典型流程：

```text
retrieve -> resolve -> delete_note -> compose
```

- `retrieve`：找候选笔记。
- `resolve`：把模糊描述解析成真实 note_id。
- `delete_note`：第一次只生成确认 payload，确认后才删除。
- `compose`：生成用户可见结果。

核心点：`note_id` 不能由 LLM 编造，必须来自运行时检索和 resolve。

### Q3：PlanValidator 防什么？

PlanValidator 当前是 StepProjectionValidator 的兼容入口，在执行前检查 workflow step projection 是否安全，包括：

- step_id 是否重复。
- action_type 是否合法。
- 依赖是否存在、是否有环。
- tool 是否真实注册。
- tool_input 是否符合 Pydantic args schema。
- risk_level / on_failure / execution_mode 是否合法。
- ReAct 是否越权调用高风险工具。
- `delete_knowledge` 是否包含 resolve 和 delete_note。
- `solidify_conversation` 的 capture_text 是否依赖 compose。

它防的是 workflow projection 或步骤注入阶段出现结构不完整、工具不存在、参数无效或风险边界不对的问题。

### Q4：PlanStep 和 PlanStepState 区别是什么？

`WorkflowStepSpec` 是 workflow 源契约，描述固定节点、依赖、decision node、工具、副作用、HITL 和恢复策略。

`PlanStep` 是从 `WorkflowStepSpec` 投影出的运行时步骤视图，描述“这个 workflow 的关键节点这次要怎么执行”，并携带 workflow 来源字段。

`PlanStepState` 是 checkpoint-safe 的运行时状态，描述“执行到了哪里、成功失败、重试次数、结果是什么”。

一个是计划，一个是可恢复现场。

## 5. ReAct 的使用边界

### Q1：项目里有没有 ReAct？

有，但不是全局主循环。ReAct 只在单个计划步骤内部使用，主要用于低风险检索探索。

例如删除知识前的 `retrieve` 步骤，可以让 ReAct 在有限轮次内调用 `graph_search` 或 `web_search` 找候选。

### Q2：为什么不让 ReAct 自主调用所有工具？

因为 ReAct 是探索式循环，不适合直接执行写入、删除、外发等副作用动作。

当前约束：

- 只在 `execution_mode="react"` 的步骤里启用。
- 默认只允许低风险只读工具。
- 有 `allowed_tools` 和 `max_iterations` 限制。
- 阻止 `delete_`、`capture_` 等高风险或写长期记忆工具。
- 高风险工具必须走 deterministic plan + HITL。

面试表述：ReAct 用来受控探索，不用来绕过 workflow。

## 6. 工具层 ToolGateway

### Q1：工具层和直接暴露函数给 LLM 有什么区别？

项目里的工具不是裸函数，而是带治理契约的系统能力。

工具通过注册中心进入 `ToolExecutor/ToolGateway`，并带有：

- Pydantic 参数 schema。
- risk_level。
- side_effects。
- requires_confirmation。
- timeout。
- retry。
- rate limit。
- domain allowlist。
- idempotency key。
- audit event。
- 统一 PolicyEngine 决策。
- 统一 `ToolArtifact` 返回结构。

这样 LLM 只能提出工具调用意图，真正执行前必须通过系统边界。当前 `PolicyEngine` 会基于 `PolicyInput` 统一判断 `allow / deny / require_confirmation / require_escalation`，并被 ToolGateway、MemoryFacade 等层消费。

### Q1.1：PolicyEngine 当前落地到了哪里？

PolicyEngine 已经从“治理元数据”落成统一策略层，核心代码在 `src/personal_agent/policy/`。

它接收 `PolicyInput`，包含 action、user_id、session_id、source_platform、tool_name、resource、risk_level、side_effects、permission_scope、confirmed、react_allowed_tools、resource_owner 等字段；输出 `PolicyDecision`，包含 allow、deny、require_confirmation、require_escalation、rule、reason 和 audit_required。

当前主要接入点：

- `ToolGateway`：统一处理 ReAct 自主守卫、高风险确认门、deny override。
- `MemoryFacade`：长期记忆读写删做 owner 校验和删除确认策略。
- `AgentRuntime`：从 Settings 构造 `PolicyRules`，把同一个 engine 注入工具层和记忆层。
- `record_policy_decision`：记录为什么允许、拒绝或要求确认。

### Q2：ToolArtifact 为什么统一成 ok/data/error/evidence？

因为不同工具的原始返回结构不同，如果直接塞进消息里，编排层很难判断成功、失败、证据和待确认状态。

统一 artifact 后，编排层可以稳定处理：

- `ok=true`：工具成功。
- `ok=false`：工具失败。
- `error_kind`：参数错误、权限错误、瞬时错误、不可恢复错误。
- `data`：机器可读结果。
- `evidence`：可进入回答证据池的内容。

### Q3：为什么删除需要 idempotency key？

确认请求可能被重复提交，checkpoint resume 可能重放，网络失败后也可能重试。

`idempotency_key` 用来标识同一次确认动作，防止重复删除。

当前实现是进程内幂等账本，能覆盖单进程重复提交；生产化还需要持久化幂等表。

## 7. 记忆系统 Memory

### Q1：项目里有哪些记忆？

主要有四类：

- 短期执行现场：LangGraph checkpoint。
- 长期知识记忆：Postgres `knowledge_notes` 和 `review_cards`。
- 图谱语义索引：Graphiti episode/entity/relation/fact。
- 情节记忆：`MemoryEpisode` 记录每次 entry run 的 workflow、结果、工具、关联 note、open items。

### Q2：为什么长期知识用 parent/chunk？

parent note 表达文档级或主题级知识；chunk note 保存细粒度片段、source span 和 citation 单元。

好处：

- 长文不会整体塞进 prompt。
- 检索可以命中精确片段。
- 回答引用可以回到具体 chunk。
- 展示时又能回到 parent note。
- 删除 parent 时可以级联删除 chunk。

### Q3：Graphiti 是长期事实真源吗？

不是。Graphiti 是语义索引层，不是业务真源。

长期事实真源是 Postgres note/chunk。Graphiti 帮助发现实体、关系、多跳线索，但回答和引用仍应回查 note/chunk。

这样可以避免图谱抽取错误、孤儿 episode 或关系漂移直接污染最终答案。

### Q4：MemoryEpisode 有什么价值？

`MemoryEpisode` 记录一次 Agent run 的过程摘要，例如：

- 用户请求。
- workflow/intent。
- outcome。
- decisions。
- open_items。
- tool_refs。
- note_refs。

它用于回答“之前做过什么、为什么这么做、还有什么没完成”这类 episodic context 问题，而不是替代长期知识库。

## 8. Capture / Ingestion

### Q1：capture 链路是什么？

核心链路：

```text
raw input
  -> source fingerprint 去重
  -> capture_node
  -> Unstructured partition / chunk_by_title
  -> chunk_reconcile_node
  -> enrich_node
  -> link_node
  -> schedule_review_node
  -> Postgres note/chunk
  -> Graphiti sync
```

关键代码在 `src/personal_agent/agent/ingestion_pipeline.py`。

### Q2：为什么要做 source fingerprint？

为了避免同一用户重复采集同一来源和内容时产生重复知识。

fingerprint 基于内容、source_type、source_ref 生成。命中已有 note 时直接返回已有笔记和 chunks，不重复跑抽取、入库、图谱同步。

### Q3：Unstructured 在 capture 中做什么？

Unstructured 是 capture 的结构化处理层，会把原始正文或文档内容 partition 成 Title、NarrativeText、ListItem、Table 等 typed elements，再用 `chunk_by_title` 生成 child chunks。

它的价值：

- chunk 不再只是固定长度切片，而是基于文档元素和标题边界。
- child chunk 可以携带 title_path、page_number、element_ids 和 element metadata。
- parent note 仍是整篇文档的来源锚点，child chunk 是证据和检索单元。
- Graphiti 直接消费 chunk-level notes；LangExtract 不再作为 Graphiti 的默认前置步骤。

## 9. Ask / RAG 问答

### Q1：ask 链路是什么？

核心链路：

```text
question
  -> QueryUnderstanding
  -> RetrievalPlan
  -> graph / structural / local / web 多源检索
  -> EvidenceItem
  -> candidate enrichment
  -> rerank
  -> ContextPack
  -> grounded generation
  -> AnswerVerifier
  -> retry / fallback
```

关键代码：

- `src/personal_agent/agent/runtime_ask.py`
- `src/personal_agent/agent/query_planner.py`
- `src/personal_agent/agent/ask_pipeline_factory.py`
- `src/personal_agent/core/evidence.py`
- `src/personal_agent/agent/verifier.py`

### Q2：QueryUnderstanding 做什么？

它在检索前把用户问题结构化，输出：

- 是否需要最新信息。
- 是否需要个人记忆。
- 是否需要图谱关系推理。
- 是否需要 episodic context。
- query rewrite。
- sub queries。
- filters。
- answer policy。

然后转成 `RetrievalPlan`，决定查 graph、local、web 中哪些来源，是否并行，是否带 filters。

### Q3：为什么要统一 EvidenceItem？

因为不同来源的证据结构完全不同：

- Postgres note/chunk。
- Graphiti graph fact。
- web search result。
- tool artifact。
- memory episode。

如果直接塞进 prompt，去重、排序、引用和预算会混乱。

`EvidenceItem` 把它们统一为：

- `source_type`
- `source_id`
- `title`
- `snippet`
- `fact`
- `source_span`
- `url`
- `score`
- `metadata`

然后 `ContextPack` 负责排序、去重、预算控制和最终 prompt 选择。

### Q4：ContextPack 的价值是什么？

ContextPack 是回答前的证据出口。

它保证：

- 只有 selected evidence 进入 prompt。
- dropped evidence 可用于调试。
- 有 char budget，避免无限塞上下文。
- 有 source diversity，避免同一来源重复占满预算。
- 用户看到的 citations 尽量和模型实际看到的证据一致。

### Q5：AnswerVerifier 做什么？

它检查回答是否被证据支撑，目前主要是规则型和启发式校验：

- evidence 是否充足。
- citation 是否有效。
- answer 和 selected evidence 是否有基本 overlap。
- 是否存在明显不支撑或冲突。

如果不足，会触发重试或 fallback。

## 10. 图谱与结构化检索

### Q1：Graphiti 在项目里做什么？

Graphiti 负责图谱语义索引：

- capture 时把 note/chunk 写成 episode。
- 抽取 entity、relation、fact。
- ask 时进行实体/关系/episode 检索。
- 返回 node_refs、edge_refs、fact_refs、citation_hits。

它擅长发现“谁和谁有什么关系”“多个实体之间如何连接”等问题。

### Q2：为什么还要 structural retriever？

Graphiti 擅长图谱关系，但图谱抽取有成本和质量风险。

StructuralRetriever 基于 Postgres note/chunk 构建 parent-section 结构索引，更贴近原文层级，适合文档结构、章节、局部片段召回。

当前系统支持 graph provider 切换和对照评测，避免押注单一路径。

### Q3：图谱最大的风险是什么？

主要是抽取质量黑盒：

- 实体抽错。
- 关系方向反了。
- 同名实体没消歧。
- 多跳推理放大错误。
- note 删除后 graph episode 残留。

当前防御：

- Graphiti 不做真源，只做索引。
- graph fact 回查 note/chunk。
- Unstructured chunk metadata 支撑回溯；Graphiti 直接消费 chunk-level note。
- graph quality metrics 记录实体数、关系数、弱关系、零实体等。
- 删除 note 时尝试清理 graph episode。

未来需要补人工标注评测、alias 表、关系归一化、孤儿 episode 对账。

## 11. HITL 与高风险操作

### Q1：删除知识完整流程是什么？

```text
用户请求删除
  -> Router: delete_knowledge, high risk, requires_confirmation
  -> Planner: retrieve -> resolve -> delete_note -> compose
  -> retrieve 找候选
  -> resolve 解析真实 note_id
  -> delete_note 第一次返回 pending confirmation
  -> LangGraph interrupt
  -> 用户确认 resume
  -> 注入 confirmed=true 和 idempotency_key
  -> delete_note 真正删除 note/chunk/review/graph episode
  -> compose 返回结果
```

### Q2：用户说“不要确认，直接删”，系统能不能照做？

不能。

确认要求来自工具治理契约和系统策略，不应该被用户指令绕过。用户可以表达删除意图，但高风险副作用必须走 HITL、幂等和审计。

### Q3：如果用户拒绝确认会怎样？

Graph 会清空 pending confirmation，把当前步骤标记为 skipped/cancelled，后续依赖步骤也不会执行。长期知识不会被删除。

## 12. 上下文工程

### Q1：对话历史如何进入回答？

对话历史只作为线索，用于理解指代、追问、用户更正和当前目标。

项目里明确有一条策略：对话线索不是事实证据；如果和当前 evidence 冲突，以当前 evidence 为准。

### Q2：为什么不能把助手历史回答当事实？

因为助手历史里可能有幻觉、猜测、未验证方案。把它们长期保存并再次检索，会形成“自我污染”。

因此长期知识必须通过 capture 或 solidify 写入。结构化 ThreadSummary 已经落地，把用户明确事实、助手假设、未确认声明分字段保存并随 checkpoint 持久化；剩余待补的是让 solidify 强制只消费其已确认字段。

### Q3：solidify_conversation 风险在哪里？

风险是把助手猜测或废弃方案写进长期知识。

当前固化流程会先 compose 草稿，再调用 capture_text。若无法生成合格正文则不写入。

更稳的做法是（结构化 ThreadSummary 已落地，区分字段已具备，剩下是让 solidify 真正只采信已确认部分）：

- 结构化 ThreadSummary 已分字段保存用户明确事实、已确认决策、助手假设、未验证声明。
- solidify 的 compose 强制只消费已确认字段，对助手假设 / 未验证声明默认不写入。
- 对不确定内容要求用户确认。

## 13. 模型分工

### Q1：项目里模型如何分工？

控制流用小模型，内容生成用主模型，结构化抽取和图谱可以独立配置。

典型分工：

- Router：小模型，输出 intent/risk/confirmation。
- Planner：不调用模型，按 `WorkflowRegistry / WorkflowStepSpec` 确定性投影需要步骤执行的 workflow。
- ReAct：小模型，输出工具选择 JSON。
- Replanner：小模型，失败后生成替代步骤。
- Query planner：优先使用支持 strict json schema 的 LangExtract/OpenAI-compatible 模型。
- Final answer：主模型，基于证据生成自然语言回答。
- Graphiti：图谱 LLM 抽取实体关系，embedding 模型做语义检索。

### Q2：为什么不所有地方都用一个大模型？

不同环节目标不同：

- 路由和规划需要稳定 JSON、低成本、低温度。
- 最终回答需要表达质量和综合能力。
- 图谱抽取需要 schema 兼容和实体关系稳定。
- embedding 需要检索质量和成本平衡。

模型解耦能降低成本，也能避免某个链路模型变更影响全系统。

## 14. 观测、事件与评测

### Q1：系统如何观测 Agent 执行过程？

项目有多层观测：

- `AgentEvent`：entry_started、intent_classified、plan_created、tool_called、confirmation_required、answer_completed 等事件。
- SSE：前端实时展示执行状态、计划步骤、回答流。
- run snapshot：查询 run 状态。
- tool audit：记录工具调用、耗时、失败、rate limit、timeout。
- graph quality logs：记录图谱抽取质量指标。
- LangSmith tracing：可选上传 LLM 调用和链路 trace。

### Q2：evals 和单元测试有什么区别？

单元测试验证代码边界是否正确，例如：

- PlanValidator 是否阻断危险计划。
- ToolGateway 是否要求确认。
- Evidence 转换是否正确。
- API 和 storage 是否按契约工作。

evals 验证 Agent 策略是否真的有效，例如：

- 检索 Recall@k/MRR/NDCG。
- graph/structural/local/hybrid 哪个更好。
- rerank 是否提升证据质量。
- 多跳问题是否召回正确 evidence。
- plan/replan 是否符合预期。

没有 evals，很多 Agent 优化只是“看起来更高级”。

### Q3：当前评测覆盖哪些方向？

工程里有：

- `evals/open_ragbench/`：RAG 检索指标。
- `evals/multihoprag/`：多跳检索评测。
- `evals/test_retrieval_strategies.py`：检索策略对照。
- `evals/test_ask_quality.py`：问答质量。
- `evals/test_plan_replan.py`：规划和重规划。
- `tests/`：router、planner、validator、tools、memory、API、Graphiti、observability 等单测。

## 15. 工程取舍与不足

### Q1：当前最值得讲的工程亮点是什么？

最值得讲的是边界设计：

- checkpoint 管短期现场，Postgres 管长期事实。
- Graphiti 是语义索引，不是真源。
- EvidenceItem/ContextPack 是回答前统一证据出口。
- ToolGateway 把 LLM 工具意图变成受治理的系统动作。
- PolicyEngine 已统一工具、记忆和入口来源的 allow/deny/confirmation 判断。
- 高风险流程通过 PlanValidator + HITL + idempotency 保护。
- ReAct 被限制在低风险单步探索里。
- evals 用数据验证检索和规划策略。

### Q2：当前项目最大不足是什么？

主要不足：

- PolicyEngine 已落地，但还需要接入更完整的 workspace/tenant/RBAC/ABAC 权限模型。
- 工具审计和 policy 决策还需要独立持久化审计表与查询界面。
- 幂等账本目前是进程内，不适合多实例生产。
- ThreadSummary 已结构化并随 checkpoint 持久化，但 solidify 还没强制只消费已确认字段，仍有污染风险。
- 知识冲突、版本链、过期知识治理还不完整。
- 图谱抽取质量缺少人工标注 precision/recall 回归集。
- Context compression 和 LLM/entailment verifier 还可以加强。

### Q3：如果继续生产化，优先做哪三件事？

第一，把现有 PolicyEngine 扩展到 workspace/tenant 级权限，并把工具审计和 policy decision 独立落库。

第二，补 memory 和 planning eval golden set，覆盖删除目标解析、solidify 污染、evidence 引用正确率、图谱多跳。

第三，补知识治理，包括版本链、冲突检测、Graphiti 孤儿 episode 对账、alias/关系归一化。

## 16. 面试追问速答

### Q1：如果 graph search 找到了事实，但 note/chunk 已删除，怎么办？

不能把它当强证据。Graphiti 只是索引，无法回查到 Postgres note/chunk 的 graph fact 应降权或过滤，并记录为 orphan。后续需要图谱对账和重试清理。

### Q2：如果 web search 和本地 memory 冲突，信哪个？

看问题类型。

如果问用户自己的知识或项目内部信息，优先本地 memory。若问外部最新事实，优先 web evidence，并说明与本地记忆存在差异。

关键是显式处理证据来源和时间，不让模型自行混合猜测。

### Q3：如果工具 content 看起来成功，但 artifact.ok=false，信哪个？

信结构化 artifact。

`ToolArtifact.ok/error/data` 是工具层机器契约，content 只是展示或观察文本。

### Q4：如果用户刚说“记住我生日是 1 月 1 日”，算长期事实吗？

在当前 thread 中可以作为对话线索，但要长期记住，必须通过 capture 或 solidify 写入 `knowledge_notes`。

### Q5：为什么不用 Graphiti 替代 Postgres？

因为 Graphiti 擅长语义关系和图检索，但不适合作为业务事实真源。Postgres 保存原文、chunk、source metadata、review card、graph mapping 和删除边界。

### Q6：为什么不用一个通用 autonomous planner 处理所有请求？

因为生产 Agent 里确定流程应该用 workflow，不确定局部才用 LLM decision node。当前项目已经把固定流程下沉为 `WorkflowSpec / WorkflowRegistry`；ask/capture 走固定 workflow 分支，delete/solidify 才投影成步骤化 workflow，比全局自由规划更可控。

### Q7：你怎么证明这个 Agent 在变好？

用 evals，而不是只看主观感觉。

检索看 Recall@k、MRR、NDCG；问答看 evidence 支撑、引用正确率、unsupported claim；规划看高风险步骤是否被阻断、目标解析是否准确、失败后是否能重规划。

## 17. 最后一段总结口径

可以这样收尾：

> 这个项目的重点不是让模型自由发挥，而是把模型放进可恢复、可校验、可审计的系统边界里。LangGraph 管流程和 checkpoint，Postgres 管长期事实，Graphiti 和 structural retriever 管语义索引，Evidence/ContextPack 管回答依据，WorkflowSpec/WorkflowRegistry 管固定流程拓扑，PolicyEngine 管策略决策，ToolGateway 管真实副作用，PlanValidator 和 HITL 管高风险动作。这样模型可以参与理解、局部决策和生成，但不能绕过记忆真源、工具治理和用户确认。
