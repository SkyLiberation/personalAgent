# 项目面试介绍总结稿

这份稿子用于面试中被要求“介绍一下当前项目 / 讲一个复杂问题 / 说说 Agent 工程师和传统后端或算法的区别”时快速组织回答。口径以当前代码和已落地能力为准，不把未来设想说成现状。

## 1. 当前项目介绍

我现在做的是一个 workflow-first 的个人知识 Agent。它不是简单把 LLM 接上几个工具，而是把用户的知识写入、问答检索、历史任务记忆、高风险操作和执行恢复都放进一套可校验、可恢复、可审计、可评测的工程边界里。

一次请求进来后，入口层会统一 Web / CLI / Feishu 等来源，先做 intent routing。Router 输出的不是自由计划，而是结构化的 `RouterDecision`，里面包含一组有序 `Goal`，例如 `ask`、`capture_text`、`capture_link`、`capture_file`、`delete_knowledge`、`solidify_conversation`、`summarize_thread`、`direct_answer` 等。

复杂意图输出后不是直接交给模型继续发挥，而是由 `WorkflowPlanner` 组织成两层结构。第一层是 task-level 的 `ExecutionPlan`：每个 `Goal` 会绑定一个固定 `WorkflowSpec`，形成一个 `WorkflowTask`，记录 `task_id / intent / input / workflow_id / workflow_version / depends_on`。第二层是 step-level 的 `ExecutionStep`：每个 `WorkflowSpec` 会被 deterministic projection 展开成步骤。如果一次请求包含多个 goal，Planner 会把 step id namespace 成 `goal_id::step_id`，再用结构化 LLM 判断 goal 之间的语义依赖，并由确定性规则做安全补强：长期写入后的 ask 要依赖写入完成，连续长期写入要串行，带“继续 / 上述 / 刚才”等指代线索的 goal 依赖前一个 task；多个互不相关的只读 ask 不会被强行串行。依赖边生成后，Planner 会对 task DAG 做引用校验、环检测和稳定拓扑排序，再按排序后的 task 顺序投影 step DAG。比如“先保存 DNS 这段，再问为什么 DNS 需要缓存”会变成 `save::cap-structure -> question::ask-retrieve -> question::ask-compose -> question::ask-verify`，同时 `ExecutionPlan.tasks` 里保留 `question` 依赖 `save`。

组织完成后，`project_workflow_steps` 节点会把 `ExecutionPlan` 和步骤状态写入 graph state，并发出 `steps_projected` 事件，事件里同时包含 tasks 和 steps，方便前端展示、debug bundle 和 replay。接着 `validate_projected_steps` 会按 task 分组调用 `StepProjectionValidator`，只做运行时工具可执行性检查；workflow 拓扑是否正确则由 `WorkflowSpecValidator` 和 CI 的 `Workflow registry gate` 在声明期拦截。最后通过校验的步骤进入 LangGraph step execution graph。

这里的 Planner 不是开放式 autonomous planner，而是 workflow-first planner。固定业务流程由 `WorkflowSpec / WorkflowRegistry` 作为唯一流程真源维护，`WorkflowPlanner` 负责把已识别 Goal 编译成 `ExecutionPlan / ExecutionStep`，并用结构化 LLM 判断 task 语义依赖；LLM 只能引用已有 task id，不能生成 workflow step、工具调用或新控制流，输出还会经过 task DAG 门禁和拓扑排序。Router 只做语义拆分，不输出执行依赖。LLM 主要出现在局部语义节点里，比如 task dependency planning、query understanding、answer compose、delete target resolve、solidify draft、ReAct 单步工具选择。

Executor 层用 LangGraph 做可恢复状态机。`StepRunState / StepExecutionState` 会进 checkpoint，工具结果、pending confirmation、事件、错误和步骤状态都能被恢复。像删除知识这种高风险流程，会通过 LangGraph interrupt/resume 做 HITL：第一次运行生成确认 payload，用户确认后用同一个 checkpoint resume，而不是重新规划。

工具层不是裸函数暴露给模型，而是 `ToolExecutor + ToolGateway + ToolGovernance + PolicyEngine`。工具有 schema、risk level、side effects、permission scope 和统一 `ToolArtifact` 返回结构。模型可以提出工具调用意图，但真正执行前还要经过工具 schema、策略、确认、幂等、timeout、retry、rate limit 和审计。比如 `delete_note` 不能被 ReAct 自主删除，必须走固定 workflow、目标 resolve、用户确认和幂等账本。

记忆层分得比较清楚。LangGraph checkpoint 管短期执行现场；Postgres 的 `knowledge_notes` 和 chunk 管长期事实；Graphiti 是语义索引层，不是事实真源；`MemoryEpisode` 记录过往任务的意图、结果和决策；`MemoryItem` 承载 reflection / procedural 候选。问答时，不同来源会统一成 `EvidenceItem`，再进入 `ContextPack` 做去重、排序和预算裁剪，保证模型看到的证据和用户看到的 citation 对得上。

稳定性上有三类门禁。第一类是 `.github/workflows/architecture.yml` 里的 `Layer / cycle gate`，它运行 `scripts/check_layers.py`，检查 `src/personal_agent` 顶层模块依赖必须符合 `kernel -> infra -> memory -> application -> tools -> governance -> planning -> orchestration -> adapters` 的分层方向，不能有包级循环依赖，也不能出现低层反向依赖高层。第二类是 `Workflow registry gate`，它运行 `tests/test_workflow_validator.py`，把错误的 `WorkflowRegistry / WorkflowSpec` 写法挡在 PR / push 阶段，比如 step id 重复、依赖不可解析、DAG 有环、工具未注册、高风险删除未声明 HITL。第三类是运行时 `StepProjectionValidator`，它不再重复校验 workflow 拓扑，只做执行前工具门禁：当前 `ToolExecutor` 是否有工具、工具输入是否满足 schema、哪些字段允许由上游 step 动态注入、ReAct allowed tools 是否可用。

评测方面，项目里有普通单测和 Agent eval 两类。单测验证确定性边界，比如 workflow contract、工具治理、HITL 状态、幂等、policy。evals 则评估策略效果，比如 Open RAGBench、MultiHopRAG、ask quality、router quality、orchestration quality，用 MRR、Recall、NDCG、引用正确性等指标判断检索、rerank、plan/replan 是否真的变好。

一句话总结：这个项目的核心不是“让模型更自由”，而是把 LLM 的不确定性放进确定性 workflow、工具治理、记忆分层、证据模型、checkpoint 和 CI/eval 门禁里。

## 2. 当前工程的优秀分层架构

面试里介绍这个项目时，建议主动强调它的分层架构。这个项目的亮点不是某一个 prompt 或某一个工具，而是每一层都有清楚职责，LLM 的不确定性只出现在被允许的局部节点里。

这套分层不是只停留在文档口径里，而是由 `scripts/check_layers.py` 门禁固化为顶层包依赖方向：`kernel -> infra -> memory -> application -> tools -> governance -> planning -> orchestration -> adapters`。高层可以依赖低层，低层不能反向依赖高层，也不能形成包级循环。

| 层级 | 关键组件与作用 |
| --- | --- |
| `kernel` 基础模型层 | `Settings / config models`：承载运行时配置、模型配置、工具治理配置等基础参数。<br>`EntryInput / AgentState / KnowledgeNote / RawIngestItem`：跨层共享的核心领域模型，避免上层各自定义私有数据结构。<br>`EvidenceItem / ContextPack / Citation`：统一证据和引用模型，让 memory、ask、tools、orchestration 对“证据是什么”有同一套语言。<br>`prompt_templates`：存放稳定 prompt 模板和输出契约，避免 prompt 分散在执行节点里。 |
| `infra` 基础设施层 | `LlmClient / structured model client`：封装模型调用、结构化输出、streaming 和 LangSmith tracing 接入。<br>Postgres stores：封装 memory、workflow event、artifact、audit、worker queue、research 等持久化访问。<br>runtime LLM / storage adapters：把外部 SDK、数据库和网络能力收束到基础设施边界，不让业务层直接散落调用。 |
| `memory` 记忆层 | `MemoryFacade`：长期记忆读写删除的统一入口，屏蔽底层 store 和图谱索引细节。<br>Postgres note / chunk：长期事实真源，parent note 表达文档级知识，chunk 保存引用粒度证据。<br>Graphiti store：语义图谱索引层，用于实体、关系和多跳线索发现，不替代 Postgres 事实真源。<br>`MemoryEpisode / MemoryItem`：分别承载任务情景记忆和 reflection / procedural 候选记忆。<br>Structural retriever：基于结构化 note/chunk 的检索能力，给 ask 和应用服务复用。 |
| `application` 应用服务层 | `CaptureService`：工具背后的正文获取服务，统一处理 URL、上传文件等来源到文本的转换。<br>`IngestionPipeline`：capture 入库应用服务，负责 fingerprint 去重、note/chunk 写入、review card、graph sync 调度和图谱结果合并。<br>Ask pipeline / retrievers / verifier：完成 query understanding、检索、rerank、context assembly、answer verification 等问答应用能力。<br>`KnowledgeConsolidationUseCase`：围绕已有知识做主题检索、整理、生成和入库。<br>`ReviewDigestUseCase / ResearchService / KnowledgeGapUseCase`：封装复习摘要、长期研究订阅和知识缺口分析等业务用例。 |
| `tools` 工具层 | `BaseTool / @tool`：定义模型可调用工具的统一 schema、描述、输入输出和治理元数据。<br>`capture_text / capture_url / capture_upload`：面向 workflow 暴露的 capture 业务工具，底层委托 application capture service。<br>`graph_search / web_search`：面向检索和 ReAct 暴露的只读搜索工具。<br>`delete_note / restore_note / update_note`：面向固定 workflow 暴露的记忆生命周期工具。<br>research / review / diagnostic tools：把研究订阅、复习摘要、worker queue 检查等能力包装成稳定工具入口。 |
| `governance` 治理层 | `ToolExecutor`：工具注册与调用入口，内部通过 `ToolGateway` 执行真实工具。<br>`ToolGateway`：模型意图和真实副作用之间的执行边界，统一处理 policy、确认、幂等、timeout、retry、rate limit 和审计。<br>`ToolGovernance`：描述 risk level、side effects、permission scope、confirmation 等工具能力声明。<br>`ToolArtifact`：工具统一返回契约，用 `ok / data / error / error_kind / evidence` 表达成功、失败和证据。<br>`PolicyEngine`：统一输出 allow / deny / require confirmation / require escalation 等策略决策。 |
| `planning` 规划层 | `DefaultIntentRouter`：用结构化模型把用户输入分类为一个或多个业务 intent。<br>`Goal / RouterDecision`：承载路由后的领域目标、有序任务和澄清状态。<br>`WorkflowSpec / WorkflowStepSpec / WorkflowRegistry`：固定业务 workflow 的声明式真源，维护步骤、依赖、风险、HITL 和恢复策略。<br>`ExecutionPlan / WorkflowTask`：把复杂意图组织成 task-level DAG，记录每个 Goal 绑定的 workflow、输入、依赖和步骤集合。<br>`WorkflowPlanner`：把有序 Goal 编译成 `ExecutionPlan / ExecutionStep`，多 goal 时负责 step id namespace；跨 task 依赖由结构化 LLM 判断语义关系，再由确定性规则做安全补强，随后通过 task DAG 引用校验、环检测和稳定拓扑排序生成投影顺序。<br>`WorkflowSpecValidator`：在声明期校验 workflow contract，例如 step id、依赖 DAG、条件边、风险和 HITL 约束。<br>`StepProjectionValidator`：运行时工具门禁，只检查当前 `ToolExecutor`、工具 schema、动态参数注入和 ReAct allowed tools 是否可用。 |
| `orchestration` 编排层 | `AgentRuntime`：组合根，装配 settings、store、LLM client、memory、tools、planner、orchestrator 和 graph contexts。<br>`EntryOrchestrator`：封装 entry graph 的执行、resume、history、snapshot、replay/fork 等入口级编排能力。<br>`orchestration_graph`：定义 LangGraph 父图，把 route、workflow projection、step execution、fallback 等节点连成可恢复状态机。<br>`GraphContexts / RoutingContext / PlanningContext / StepExecutionContext / ReactContext`：把运行时依赖切成窄上下文，避免节点直接依赖整个 Runtime。<br>`StepRunState / StepExecutionState / AgentEvent`：checkpoint-safe 的步骤状态和事件模型，支撑 interrupt/resume、HITL、replay 和前端展示。 |
| `adapters` 入口适配层 | Web routes：把 HTTP 请求适配为 service 调用，负责参数、响应和 SSE 等 Web 传输形态。<br>CLI：把命令行输入适配为同一套 service 调用，用于本地调试和脚本化操作。<br>Feishu service：把飞书消息、命令和交互回调适配为内部 Agent 请求。<br>`AgentService`：对外暴露统一 service 边界，隐藏 `AgentRuntime` 内部装配细节。 |

这套分层的核心价值是：领域模型和证据模型在 `kernel`，外部系统访问在 `infra`，长期记忆在 `memory`，业务用例在 `application`，模型可调用能力在 `tools`，副作用治理在 `governance`，路由和 workflow 真源在 `planning`，LangGraph 状态机在 `orchestration`，Web/CLI/飞书入口在 `adapters`。模块依赖无环由 `.github/workflows/architecture.yml` 的 `Layer / cycle gate` 执行，workflow contract 由 `Workflow registry gate` 执行，评测和单测负责验证策略质量与确定性边界。

面试里可以把它总结成一句话：

> 这个项目的优秀之处在于不是用一个大 Agent loop 包打天下，而是把 Agent 拆成 kernel、infra、memory、application、tools、governance、planning、orchestration、adapters 九层；工具定义和工具治理分离，workflow 真源和执行状态分离，LLM 只在局部语义判断里发挥作用，系统级安全和恢复由确定性工程保证。

## 3. 最复杂的问题或架构挑战

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

## 4. Agent 工程师和传统后端 / 算法工程师的区别

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

## 5. 30 秒压缩版

这是一个 workflow-first 的个人知识 Agent。Router 只识别 intent 和 Goal，固定流程由 `WorkflowSpec / WorkflowRegistry` 维护，deterministic projection 编译成 `ExecutionStep`，LangGraph 负责 checkpoint、interrupt/resume 和步骤状态。记忆层区分短期 checkpoint、长期 note/chunk、Graphiti 语义索引和 episodic memory；回答前统一成 Evidence/ContextPack。工具层通过 ToolGateway、PolicyEngine、HITL、幂等和审计控制副作用。模块依赖是否无环由 `.github` 的 `Layer / cycle gate` 拦截，workflow 写错由 registry gate 和 `WorkflowSpecValidator` 在 PR 阶段拦截；运行时 `StepProjectionValidator` 只做工具可执行性门禁。这个项目最核心的工程价值，是把 LLM 的不确定性限制在局部语义判断里，把流程、安全、恢复和评测交给确定性系统。

---

[← 返回索引 INDEX.md](INDEX.md)
