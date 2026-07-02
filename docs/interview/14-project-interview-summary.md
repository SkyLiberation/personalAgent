# 项目面试介绍总结稿

这份稿子用于面试中被要求“介绍一下当前项目 / 讲一个复杂问题 / 说说 Agent 工程师和传统后端或算法的区别”时快速组织回答。口径以当前代码和已落地能力为准，不把未来设想说成现状。

## 1. 当前项目介绍

我现在做的是一个 workflow-first 的个人知识 Agent。它解决的不是“接一个大模型做聊天”，而是把个人知识写入、检索问答、附件理解、会话固化、高风险删除和后台研究订阅放进一套可校验、可恢复、可审计、可评测的工程框架里。核心判断是：Agent 不应该把所有事情都交给一个自由循环，而应该让模型只在 query understanding、answer compose、delete resolve、research decision 等局部节点做语义判断；流程拓扑、工具副作用、HITL、恢复和评测交给确定性系统。

入口层会把 Web / CLI / Feishu 等来源统一成 `EntryInput`，进入同一个 `AgentService.entry()`。这里最近一个重要改动是 Artifact-first 上传：上传文件先成为 `ArtifactRef`，作为本轮对话证据存在，不默认写入知识库。用户说“总结这张图”或“回答这段语音里的问题”，会走 `analyze_artifact -> inspect_artifact`，只读理解图片、音频、PDF 或文本附件；只有明确说“保存 / 收录 / 写入知识库”，才走 `capture_file -> capture_text` 入库。这样 Agent 可以先理解和使用临时附件，而不是一上传就强制 capture。

路由层用结构化 `RouterDecision` 先表达 `user_goal / route_type / coverage / matched_capabilities`，再输出一个或多个有序 `Goal`，例如 `ask`、`analyze_artifact`、`capture_text`、`delete_knowledge`、`solidify_conversation`、`research_once` 等。这样 Router 不是已有能力菜单分类器，而是先理解用户目标，再判断当前能力是完整覆盖、部分覆盖、需要澄清还是不支持；它不生成执行步骤。复杂意图会交给 `WorkflowPlanner`，把每个 Goal 绑定到固定 `WorkflowSpec`，再投影成 `ExecutionStep`。多目标依赖可以由结构化 LLM 判断，但 LLM 只能引用已有 task id，不能自由发明工具、步骤或控制流，最后还要经过 DAG 校验和拓扑排序。

执行层用 LangGraph 做可恢复状态机。`StepRunState / StepExecutionState`、工具结果、pending confirmation、事件和错误都会进 checkpoint。ask 是 `retrieve -> compose -> verify -> repair`；附件理解是 `artifact-inspect -> artifact-compose`；保存附件是 `artifact-inspect -> capture_text`；删除知识是 `retrieve -> resolve -> delete_note + HITL -> compose`；research 是 prepare / initialize / loop / synthesize / verify 的 evidence-driven workflow。高风险动作第一次只生成确认 payload，用户确认后从同一个 checkpoint resume，而不是重新规划。

工具层不是裸函数，而是 `ToolExecutor + ToolGateway + ToolGovernance + PolicyEngine`。每个工具都有 schema、risk level、side effects、permission scope 和统一 `ToolArtifact` 返回结构，执行前经过策略、确认、幂等、timeout、retry、rate limit 和审计。`inspect_artifact` 是只读理解能力，`capture_text` 才是长期写入能力，`delete_note` 必须走固定 workflow 和人工确认。

记忆和证据层也分得很清楚：LangGraph checkpoint 管短期执行现场；Postgres `knowledge_notes` 和 chunk 是长期事实真源；Graphiti 是语义图谱索引；`MemoryEpisode` 记录历史任务。问答和研究前，不同来源会先投影成 `SourceDocument / EvidenceItem`，再由 `EvidenceEngine` 统一完成 context assembly、claim grounding 和 citation/match selection，保证模型看到的证据、校验使用的 evidence span 和用户看到的引用能对齐。research 的 `ResearchSource` 也会投影到同一套 evidence 语义，而不是另起一套验证逻辑。

稳定性上有三类门禁：layer / cycle gate 限制包依赖方向；workflow registry gate 在 CI 阶段拦截错误 workflow；运行时 `StepProjectionValidator` 检查工具和参数是否可执行。再加上 router、workflow、工具治理、RAG、orchestration 和 research 的单测 / eval，保证改 prompt、planner 或工具策略后能评估是否真的变好。

一句话总结：这个项目的核心不是让 Agent 更“自由”，而是把 LLM 的不确定性限制在局部语义判断里，把业务流程、工具副作用、长期记忆、证据链、HITL、恢复和评测做成确定性工程系统。

## 2. 当前工程能力清单

如果面试官问“这个工程现在到底有什么能力”，可以按“入口 -> workflow -> 记忆 -> 主动闭环 -> 治理观测”来讲，而不是只说它是一个 RAG 项目。

| 能力 | 当前已落地的内容 |
| --- | --- |
| 多端统一入口 | Web API / SSE、CLI、飞书文本和文件入口都会归一成 `EntryInput`，进入同一套 `AgentService.entry()` / `AgentRuntime.entry()`。入口层负责 user/session/thread 绑定、文本归一、artifact 引用、飞书消息去重和结果回传。 |
| Artifact-first 上传 | 上传文件先成为 `ArtifactRef`，作为本轮对话证据进入 Agent，不默认写入长期知识。`inspect_artifact` 只读理解图片、音频、PDF 或文本附件；`analyze_artifact` 用于总结/问答；只有显式保存意图才进入 `capture_file -> capture_text` 入库。 |
| 语义路由与复合目标拆分 | `DefaultIntentRouter` 用结构化模型输出 `user_goal / route_type / coverage / matched_capabilities` 和有序 `Goal`，支持 `ask`、`analyze_artifact`、`capture_text`、`capture_link`、`capture_file`、`delete_knowledge`、`solidify_conversation`、`summarize_thread`、`direct_answer` 等意图；能力不足时走 `unsupported`，目标不清时走 clarify / interrupt。 |
| Workflow-first 执行 | 固定业务流程由 `WorkflowSpec / WorkflowRegistry` 声明，`WorkflowPlanner` 编译成 task-level `ExecutionPlan` 和 step-level `ExecutionStep`。LLM 不生成任意执行拓扑，只在 task dependency、query understanding、answer compose、delete resolve、solidify draft、ReAct 单步选择等局部语义节点参与。 |
| Step projection workflow | 当前已注册并进入 `StepExecutionGraph` 的主流程包括：`capture_text`、`capture_link`、`capture_file`、`analyze_artifact`、`ask`、`summarize_thread`、`delete_knowledge`、`solidify_conversation`、`research_once`、`execute_research_run`、`direct_answer`。每个流程都有步骤状态、事件、checkpoint、失败处理和前端 steps 展示。 |
| Ingest / Capture 入库 | 支持文本、URL 和显式保存的上传 artifact 入库。URL 先提取正文；文件先由 `inspect_artifact` 转成可入库文本；最终统一调用 `capture_text` 进入 `IngestionPipeline`，完成去重、parent note、结构化 chunk、child note、关联、复习卡和 graph sync 调度。 |
| Ask / RAG 问答 | `ask` 固定拆成 `ask-retrieve -> ask-compose -> ask-verify -> ask-repair`。retrieve 做 query understanding、retrieval plan、多源召回、证据归一、候选增强、rerank 和 ContextPack；compose 只基于 ContextPack 生成答案；verify 做校验和有界 retry；repair 显式处理反证补充、web fallback 和最终证据不足标注。 |
| Evidence Engine | 长期知识来自 Postgres note/chunk，图谱索引用 Graphiti，另有 structural retriever、本地 lexical/vector、web search、episodic memory 和 research source。不同来源先归一成 `SourceDocument / EvidenceItem`，再由 `EvidenceEngine` 统一做 dedupe、RRF、candidate enrichment、compression、rerank、`ContextPack` 选择、`Citation`/match selection 和 `evidence_text_spans` claim grounding，让 ask 生成、answer verification、research digest verification 和对外 citation 使用同一套证据语言。 |
| 对话固化 | `solidify_conversation` 从 checkpoint 的历史消息中选择本次请求真正指向的知识，生成可独立入库的草稿，再复用 capture 链路写入长期记忆，避免把“帮我保存一下”这种操作指令本身入库。 |
| 高风险删除与恢复 | `delete_knowledge` 固定为 `del-1 retrieve -> del-2 resolve -> del-3 delete_note + HITL -> del-4 compose`。删除前先检索候选、解析真实 `note_id`，再通过 ToolGateway、PolicyEngine、用户确认、幂等 key、软删除快照和审计执行；`restore_note` 可从删除快照恢复 note、chunk 和 review card。 |
| 受控 ReAct | ReAct 不是全局自主循环，而是某个 step 的局部执行模式。默认只允许 `graph_search / web_search` 等只读工具；高风险、删除、外发、不可逆和 workflow-only 工具不能被 ReAct 自主调用。 |
| 工具治理 | 工具不是裸函数，而是 `BaseTool + ArgsSchema + ToolGovernance + ToolGateway + ToolArtifact`。已覆盖 schema 校验、risk level、side effects、permission scope、timeout、retry、rate limit、allowed domains、HITL、幂等账本和结构化审计。 |
| 复习与知识巩固 | capture 时生成 `ReviewCard`；`ReviewDigestUseCase` 可以生成每日知识简报，`ReviewDigestJob / Scheduler` 按订阅和用户时区投递到飞书；用户可通过 Web 或飞书提交“记得 / 忘了 / 稍后”反馈并更新复习间隔。 |
| 主动知识闭环 | `KnowledgeGapUseCase` 能基于图谱拓扑和近期笔记检测知识孤岛、潜在矛盾并主动提问；`consolidate_knowledge` 能按主题整理多条笔记生成综述，并将原笔记标记为 superseded；Review Digest 里也有知识增长 section。 |
| 持续研究 / 情报订阅 | 支持一次性研究和定时研究订阅。`research_once` 是 evidence-driven loop：`research_prepare_run -> research_initialize_state -> research_run_loop -> research_synthesize_digest -> research_verify_digest -> research-compose`。它保留 `ResearchDecision -> ResearchSource -> ResearchEvent -> DigestClaim` 的可审计链路，digest claim 验证复用共享 evidence span，而不是只信 URL 或标题。 |
| 后台任务与 durable queue | Postgres `worker_queue_tasks` 提供 enqueue、lease、heartbeat、优先级、重试、dead-letter 和 per-user concurrency。capture 后的 chunk-level graph sync、research run 等都可以通过 worker queue 后台执行。 |
| Workflow 平台化能力 | workflow definition / deployment / eval gate 已持久化到 Postgres；active deployment 可以 pin stable/canary/disabled 版本。`workflow_events / workflow_artifacts / workflow_replay_runs` 支持事件溯源、step-level artifact、retention/redaction、按 `step_id` 查询、checkpoint replay/fork 和 debug bundle。 |
| 观测、审计与 API | `AgentEvent` 暴露 step、tool、HITL、answer 等事件；Web SSE 可返回步骤进度、工具结果、确认 payload、答案和错误。工具审计进入 Postgres，可按 user/tool/thread/run/risk/mode 等维度查询，并支持字段脱敏和策略决策记录。 |
| CI 与评测门禁 | `.github/workflows/architecture.yml` 有 layer/cycle gate 和 workflow registry gate；测试覆盖 workflow validator、projection、HITL、tool governance、policy、storage 等确定性边界；evals 覆盖 RAG、router、orchestration、tool quality、research quality、Open RAGBench、MultiHopRAG 等策略质量。 |

其中 `IngestionPipeline` 可以单独展开，因为它是长期记忆质量的关键：

```text
capture_text / capture_url / capture_file(artifact-inspect -> capture_text)
  -> AgentRuntime.execute_capture(...)
  -> IngestionPipeline.ingest(...)
     -> source fingerprint dedupe
     -> capture_node
     -> structural_chunk_node
     -> chunk_reconcile_node
     -> enrich_node
     -> link_node
     -> schedule_review_node
     -> _ingest_to_graph
```

各子步骤的职责是：

- `source fingerprint dedupe`：用 `text + source_type + source_ref` 计算 sha256，同一用户同一来源已入库时直接返回已有 parent note 和 chunks，避免重复写入。
- `capture_node`：把 `RawIngestItem` 转成 parent `KnowledgeNote`，写入 source、fingerprint、metadata、title、content、summary、tags。parent note 是整篇内容的展示和来源回溯锚点。
- `structural_chunk_node`：用 Unstructured-backed partition/chunk 生成 `ChunkDraft[]`，保留 `title_path / page_number / element_ids / source_span / category` 等结构信息，而不是简单固定长度切分。
- `chunk_reconcile_node`：把 `ChunkDraft` materialize 成 child `KnowledgeNote`。child chunk 是检索和证据单元，parent note 是文档级聚合单元；如果只有一个 draft，则不额外生成 child chunks，只把结构元数据写回 parent。
- `enrich_node`：更新摘要和标签，让 note 更适合后续检索、展示和复习。
- `link_node`：调用相似笔记发现，把 parent 和 chunk 的 `related_note_ids` 写回，建立本地知识之间的关联线索。
- `schedule_review_node`：为新知识生成 `ReviewCard`，纳入后续 Review Digest 和复习反馈闭环。
- `_ingest_to_graph`：如果图谱可用且有 child chunks，parent note 标为 `skipped`，graph sync 委托给 chunk；chunk 按预算标为 `pending / skipped`，pending chunk 入 `worker_queue_tasks(queue="graph", task_type="graph_sync_note")`，后台 worker 再执行 `sync_note_to_graph(note_id)`。如果没有 child chunks，则按配置走 parent note 后台入队或前台 `graph_store.ingest_note()`，并把 episode、entity、relation 和质量指标回写到本地 note。

这条 ingest workflow 的面试重点是：写入长期记忆不是“把文本塞进向量库”，而是先做来源去重，再形成 parent/chunk 双层知识实体，保留结构化来源元数据，生成复习卡，建立相关笔记关系，并把图谱同步变成可重试的后台任务。这样后续 ask、review、consolidate、delete/restore 都能共享同一套长期记忆真源。

## 3. 当前工程的优秀分层架构

面试里介绍这个项目时，建议主动强调它的分层架构。这个项目的亮点不是某一个 prompt 或某一个工具，而是每一层都有清楚职责，LLM 的不确定性只出现在被允许的局部节点里。

这套分层不是只停留在文档口径里，而是由 `scripts/check_layers.py` 门禁固化为顶层包依赖方向：`kernel -> infra -> memory -> application -> tools -> governance -> planning -> orchestration -> adapters`。高层可以依赖低层，低层不能反向依赖高层，也不能形成包级循环。

| 层级 | 关键组件与作用 |
| --- | --- |
| `kernel` 基础模型层 | `Settings / config models`：承载运行时配置、模型配置、工具治理配置等基础参数。<br>`EntryInput / ArtifactRef / AgentState / KnowledgeNote / RawIngestItem`：跨层共享的核心领域模型，区分本轮临时 artifact 和长期知识。<br>`SourceDocument / EvidenceItem / ContextPack / Citation`：统一来源、证据、上下文包和引用模型，让 ask、research、memory、tools、orchestration 对“证据是什么”有同一套语言。kernel 只放模型和纯转换，复杂装配由 application 层 `EvidenceEngine` 承担。<br>`prompt_templates`：存放稳定 prompt 模板和输出契约，避免 prompt 分散在执行节点里。 |
| `infra` 基础设施层 | `LlmClient / structured model client`：封装模型调用、结构化输出、streaming 和 LangSmith tracing 接入。<br>Postgres stores：封装 memory、workflow event、artifact、audit、worker queue、research 等持久化访问。<br>runtime LLM / storage adapters：把外部 SDK、数据库和网络能力收束到基础设施边界，不让业务层直接散落调用。 |
| `memory` 记忆层 | `MemoryFacade`：长期记忆读写删除的统一入口，屏蔽底层 store 和图谱索引细节。<br>Postgres note / chunk：长期事实真源，parent note 表达文档级知识，chunk 保存引用粒度证据。<br>Graphiti store：语义图谱索引层，用于实体、关系和多跳线索发现，不替代 Postgres 事实真源。<br>`MemoryEpisode / MemoryItem`：分别承载任务情景记忆和 reflection / procedural 候选记忆。<br>Structural retriever：基于结构化 note/chunk 的检索能力，给 ask 和应用服务复用。 |
| `application` 应用服务层 | `ArtifactService`：保存上传 artifact，并提供图片理解、音频转写、PDF/文本提取等“本轮上下文理解”能力，不默认入库。<br>`CaptureService`：工具背后的正文获取服务，统一处理 URL 等来源到文本的转换。<br>`IngestionPipeline`：capture 入库应用服务，负责 fingerprint 去重、note/chunk 写入、review card、graph sync 调度和图谱结果合并。<br>`EvidenceEngine`：共享证据引擎，负责 source normalization、context assembly、claim grounding、selected citations/matches，是 ask 和 research 之间复用 evidence 能力的核心边界。<br>Ask pipeline / retrievers / verifier / repair：完成 query understanding、检索、answer compose 和显式补证修复，证据装配与 claim grounding 交给 EvidenceEngine。<br>`ResearchService`：围绕 topic/window 做 decision、collect、event clustering、personal ranking、digest synthesis 和 claim verification，digest claim verification 复用 EvidenceEngine。<br>`KnowledgeConsolidationUseCase / ReviewDigestUseCase / KnowledgeGapUseCase`：封装知识整理、复习摘要和知识缺口分析等业务用例。 |
| `tools` 工具层 | `BaseTool / @tool`：定义模型可调用工具的统一 schema、描述、输入输出和治理元数据。<br>`inspect_artifact`：只读理解当前上传 artifact，供 `analyze_artifact` 或 `capture_file` 的上游步骤复用。<br>`capture_text / capture_url`：面向 workflow 暴露的 capture 业务工具，其中长期写入由 `capture_text` 承担。<br>`graph_search / web_search`：面向检索和 ReAct 暴露的只读搜索工具。<br>`delete_note / restore_note / update_note`：面向固定 workflow 暴露的记忆生命周期工具。<br>research / review / diagnostic tools：把研究订阅、复习摘要、worker queue 检查等能力包装成稳定工具入口。 |
| `governance` 治理层 | `ToolExecutor`：工具注册与调用入口，内部通过 `ToolGateway` 执行真实工具。<br>`ToolGateway`：模型意图和真实副作用之间的执行边界，统一处理 policy、确认、幂等、timeout、retry、rate limit 和审计。<br>`ToolGovernance`：描述 risk level、side effects、permission scope、confirmation 等工具能力声明。<br>`ToolArtifact`：工具统一返回契约，用 `ok / data / error / error_kind / evidence` 表达成功、失败和证据。<br>`PolicyEngine`：统一输出 allow / deny / require confirmation / require escalation 等策略决策。 |
| `planning` 规划层 | `DefaultIntentRouter`：用结构化模型理解用户目标，判断能力覆盖度和路由类型，再输出一个或多个业务 Goal。<br>`Goal / RouterDecision`：承载 `user_goal / route_type / coverage / matched_capabilities`、有序任务和澄清状态。<br>`WorkflowSpec / WorkflowStepSpec / WorkflowRegistry`：固定业务 workflow 的声明式真源，维护步骤、依赖、风险、HITL 和恢复策略。<br>`ExecutionPlan / WorkflowTask`：把复杂意图组织成 task-level DAG，记录每个 Goal 绑定的 workflow、输入、依赖和步骤集合。<br>`WorkflowPlanner`：把有序 Goal 编译成 `ExecutionPlan / ExecutionStep`，多 goal 时负责 step id namespace；跨 task 依赖由结构化 LLM 判断语义关系，再由确定性规则做安全补强，随后通过 task DAG 引用校验、环检测和稳定拓扑排序生成投影顺序。<br>`WorkflowSpecValidator`：在声明期校验 workflow contract，例如 step id、依赖 DAG、条件边、风险和 HITL 约束。<br>`StepProjectionValidator`：运行时工具门禁，只检查当前 `ToolExecutor`、工具 schema、动态参数注入和 ReAct allowed tools 是否可用。 |
| `orchestration` 编排层 | `AgentRuntime`：组合根，装配 settings、store、LLM client、memory、tools、planner、orchestrator 和 graph contexts。<br>`EntryOrchestrator`：封装 entry graph 的执行、resume、history、snapshot、replay/fork 等入口级编排能力。<br>`orchestration_graph`：定义 LangGraph 父图，把 route、workflow projection、step execution、fallback 等节点连成可恢复状态机。<br>`GraphContexts / RoutingContext / PlanningContext / StepExecutionContext / ReactContext`：把运行时依赖切成窄上下文，避免节点直接依赖整个 Runtime。<br>`StepRunState / StepExecutionState / AgentEvent`：checkpoint-safe 的步骤状态和事件模型，支撑 interrupt/resume、HITL、replay 和前端展示。 |
| `adapters` 入口适配层 | Web routes：把 HTTP 请求适配为 service 调用，负责参数、响应和 SSE 等 Web 传输形态。<br>CLI：把命令行输入适配为同一套 service 调用，用于本地调试和脚本化操作。<br>Feishu service：把飞书消息、命令和交互回调适配为内部 Agent 请求。<br>`AgentService`：对外暴露统一 service 边界，隐藏 `AgentRuntime` 内部装配细节。 |

这套分层的核心价值是：领域模型和证据模型在 `kernel`，外部系统访问在 `infra`，长期记忆在 `memory`，业务用例在 `application`，模型可调用能力在 `tools`，副作用治理在 `governance`，路由和 workflow 真源在 `planning`，LangGraph 状态机在 `orchestration`，Web/CLI/飞书入口在 `adapters`。ask 和 research 的业务 workflow 保持分开，但共享 application 层 `EvidenceEngine`：source normalization、context assembly、selected citation/match 和 claim grounding 都不再散落在各自 workflow 里；模块依赖无环由 `.github/workflows/architecture.yml` 的 `Layer / cycle gate` 执行，workflow contract 由 `Workflow registry gate` 执行，评测和单测负责验证策略质量与确定性边界。

面试里可以把它总结成一句话：

> 这个项目的优秀之处在于不是用一个大 Agent loop 包打天下，而是把 Agent 拆成 kernel、infra、memory、application、tools、governance、planning、orchestration、adapters 九层；工具定义和工具治理分离，workflow 真源和执行状态分离，业务 workflow 和 EvidenceEngine 分离，LLM 只在局部语义判断里发挥作用，系统级安全、证据链和恢复由确定性工程保证。

## 4. 最复杂的问题或架构挑战

### 4.1 高风险长期知识删除：自然语言目标到确定性副作用

我会讲删除长期知识这条链路，因为它同时涉及 planner、executor、memory、tool gateway、HITL、checkpoint 和幂等。

用户常说的是“删掉之前那条 DNS 知识”这类自然语言目标，但真正可删除的是 Postgres 里的 `note_id`。中间可能经过图谱 episode、chunk、parent note、标题摘要等多个对象。如果让 LLM 直接生成 `note_id` 或直接调用删除工具，风险很高：可能删错、重复删、确认后状态丢失，或者图谱命中的对象和 Postgres 真源对不上。

所以我把删除设计成固定 workflow：

```text
del-1 retrieve/react
  -> del-2 resolve
  -> del-3 tool_call(delete_note) + HITL
  -> del-4 compose
```

`del-1` 只做候选检索，可以用受限 ReAct，但只允许只读 `graph_search`。`del-2` 从候选里解析真实目标，LLM 只能在候选集合里选择，不能编造 note id。`del-3` 第一次不会直接删除，而是生成 pending confirmation；用户确认后通过 LangGraph resume 回到同一个 checkpoint，再带 confirmed 和 idempotency key 执行真实删除。`del-4` 负责生成用户可见结果。

这个问题里最重要的工程判断是：高风险动作不能靠 prompt 说“请谨慎”，必须靠系统边界约束。流程拓扑由 `WorkflowSpec` 固定；错误 registry 写法由 CI gate 提前拦截；运行时工具可用性由 `StepProjectionValidator` 检查；真实副作用由 ToolGateway / PolicyEngine / HITL / 幂等账本 / 审计接管；状态恢复由 LangGraph checkpoint 承担。

如果线上用户反馈“删除卡住了”或“候选选错了”，也不是只拿用户原话重新问一遍，而是通过 thread_id、run_id、checkpoint history 定位当时的状态，从失败节点 replay / fork。这样能判断问题到底发生在 router、retrieve、resolve、confirmation payload、tool input 注入、ToolGateway 还是 resume 状态恢复。

### 4.2 Research 端到端延迟：质量、成本和可评测性的冲突

另一个更像真实 Agent 工程坑的案例，是 `research_once` 端到端链路的 latency 问题。

一次前端对话框触发的研究任务表面上只是“调研 OpenAI GPT-5 mini 的最新公开动态，最多整理 1 条高可信事件”，但实际链路会经过 `research_prepare_run -> research_initialize_state -> research_run_loop -> research_synthesize_digest -> research_verify_digest`。其中 `research_run_loop` 又会动态执行 web search、URL 抓取、LangExtract 事件抽取、事件聚类、个人知识图谱检索和排序。最开始我看到的问题是：workflow 没有被校验阻断，工具也确实在跑，但前端等待很久后显示 research-loop 超时。

这个问题的坑在于，不能简单把 timeout 加大。因为 latency 本身就是质量指标，golden test 如果只看最终有没有结果，不看耗时和工具调用数，就会把一个“能跑但不可用”的 Agent 误判成通过。定位时我按 run_id 拆了审计日志，发现显性耗时主要来自两块：`graph_search` 连续多次打满 15 秒超时，7 次就超过 100 秒；`capture_url` 结束到首个 `graph_search` 之间还有一段较长黑箱，大概率是 LangExtract 对多源全文逐条抽取。也就是说它不是 while 死循环，而是单轮研究内部候选太多、每个候选都做昂贵处理，导致一轮就吃满外层 240 秒。

这个案例里我学到的工程判断是：Agent 的 eval 不能只评效果，还要评成本和延迟。`max_items=1` 这种用户约束不能只影响最终 digest 数量，还要传导到候选规模、抓取上限、抽取上限和排序上限；否则系统会为了产出 1 条结果处理几十个候选。另一方面，ToolGateway 的 timeout 如果只是 `future.result(timeout)`，底层线程并不会被真正取消，外层超时后后台工具还可能继续写日志，表现得像“死循环没拦住”。这类问题需要阶段级观测和可取消执行，而不是靠 prompt 或总 timeout 兜底。

如果面试官追问“后来怎么改”，可以说我的思路不是降级跳过质量步骤，而是把 latency 变成一等指标：给 `plan / collect / capture / extract / personalize / rank` 加阶段级 metric；把 `ResearchBudget.max_tool_calls` 这种已有预算真正接到 direct tool 调用上；在 golden test 里加入总耗时、阶段耗时和工具调用数断言；同时优化图谱检索避免每个事件重复触发慢初始化。这个案例体现的是，Agent 工程里最难的不是让链路跑通，而是让它在质量、成本、延迟、可取消性和可评测性之间形成稳定契约。

## 5. Agent 工程师和传统后端 / 算法工程师的区别

我理解 Agent 工程师最大的区别是：他要把非确定性的模型能力放进确定性的工程控制面里。

传统后端更关注接口、事务、权限、队列、幂等、观测和稳定性；算法工程师更关注模型、召回、排序、训练和评估。Agent 工程师夹在中间：既要理解 LLM 能在哪些局部决策上产生价值，也要知道哪些地方绝不能交给模型自由发挥。

所以 Agent 工程师需要同时关心几类问题：

- 哪些流程应该固定成 workflow，哪些节点才允许 LLM 做局部判断。
- 工具调用是否有 schema、权限、确认、幂等、审计和失败恢复。
- 短期上下文、长期事实、图谱索引、情景记忆、反思记忆之间的边界是否清楚。
- 模型看到的 evidence 和最终展示的 citation 是否一致。
- 线上失败能不能通过 checkpoint replay 复现，而不是只能“重新问一次”。
- 改了 prompt、planner、reranker 或工具策略后，有没有 eval 证明真的变好。
- 架构约束应该沉到 CI gate、spec validator 和测试里，而不是靠文档口径或运行时兜底。

一句话收口：传统后端主要让确定性系统稳定运行，算法工程师主要提升模型效果，Agent 工程师则要设计“模型能参与但不能越界”的系统。他的价值不是让 Agent 看起来更聪明，而是让 Agent 在真实系统里做对事、做错可控、出问题可复现、改动能评测。

## 6. 30 秒压缩版

这是一个 workflow-first 的个人知识 Agent。Router 先理解 `user_goal`，判断 `route_type / coverage / matched_capabilities`，再输出有序 Goal；固定流程由 `WorkflowSpec / WorkflowRegistry` 维护，deterministic projection 编译成 `ExecutionStep`，LangGraph 负责 checkpoint、interrupt/resume 和步骤状态。上传文件先是 `ArtifactRef`，可通过 `analyze_artifact / inspect_artifact` 被总结或问答，只有显式保存才进入 `capture_file -> capture_text` 入库。记忆层区分短期 checkpoint、长期 note/chunk、Graphiti 语义索引和 episodic memory；ask 和 research 保持不同 workflow，但共享 `EvidenceEngine` 把来源归一、上下文组装、claim grounding 和 citation selection 收敛到一处。工具层通过 ToolGateway、PolicyEngine、HITL、幂等和审计控制副作用。模块依赖是否无环由 `.github` 的 `Layer / cycle gate` 拦截，workflow 写错由 registry gate 和 `WorkflowSpecValidator` 在 PR 阶段拦截；运行时 `StepProjectionValidator` 只做工具可执行性门禁。这个项目最核心的工程价值，是把 LLM 的不确定性限制在局部语义判断里，把流程、安全、证据链、恢复和评测交给确定性系统。

---

[← 返回索引 INDEX.md](INDEX.md)
