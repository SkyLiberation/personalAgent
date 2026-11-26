# personalAgent 当前核心架构

> 本文按现行代码说明全局责任和主链；实际包布局见[代码地图](code-map.md)，横切装配见[横切机制](cross-cutting.md)。实际结果按[评测盘点](../evals/02-current-case-inventory.md)中的归档身份解释，未闭环事项见[设计优化队列](../future/design-optimization-backlog.md)。

## 1. 核心判断

personalAgent 是一个受治理的知识智能体。模型负责开放世界语义判断，确定性系统负责权限、准入、状态迁移和不变量；执行系统产生事实，Verifier 判断目标是否语义满足，Completion 门禁检查必需结果契约是否齐全。

目标与回答核验默认开启，由 Settings 读取 typed feature flags、AgentRuntime 注入 Conversation、Journal 绑定运行及会话。关闭核验仍需实际接纳事实，也不会产生语义通过回执。开关契约见 [ADR 0050](../adr/0050-verification-feature-flags.md)。

```text
用户目标 + 可见 Context + 已提交 Observation
  -> 模型产生 typed Proposal
  -> Admission / Policy 接受或拒绝
  -> Tool / Agent / Application Use Case 产生执行事实
  -> Verification 判断语义结果
  -> Completion 关闭或保留待完成义务
```

Proposal 不是权限、Command、Receipt 或完成证明。工具返回成功、子智能体进入终态、Artifact 存在和 Verifier 单独通过，都只能证明各自阶段的事实。

## 2. 分层与依赖方向

架构约束的依赖方向是 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 在外部依赖与信任边界消费 Port，外层实现 Port，并在 Composition Root 装配；能力内部的确定性协作可以直接调用。

当前装配从 `AgentService` 创建存储与 `AgentRuntime` 开始，Web 的 `build_web_app_context()` 继续装配渠道和调度器。`AgentRuntime` 是运行依赖的集中装配点，同时仍包含部分业务协调方法；不能将其现状描述为纯装配模块。`domain/` 当前只有包声明，领域模型与不变量主要位于对应 `application` 模块及 `kernel` 的现行共享模型，具体坐标和后续修改约束见[代码地图](code-map.md)。

| 层次 | 当前责任 | 禁止承担 |
| --- | --- | --- |
| Interface | Web、CLI 和飞书的协议转换、身份解析与输入校验 | 补全业务语义、直接改写 Aggregate |
| Application Capability | 接收 Use Case，协调领域、模型、治理和执行 Port | 复制领域迁移、伪造执行成功 |
| Domain / Product Aggregate | 拥有 canonical business facts、合法迁移和核心不变量 | 依赖 ORM、LangGraph、网络或模型 SDK |
| Runtime Mechanism | 执行 Tool/Agent、管理 queue/lease、checkpoint、Artifact 与 Trace | 决定用户意图、业务计划或完成结论 |
| Projection / DTO | 从定义、可用性、曝光或资源可见性物化只读视图 | 成为定义或可用性的第二写入口 |

`AgentService` 是外部入口使用的统一外观。独立的业务事实仍归对应能力和存储契约；外观与装配代码中的协调方法不能因此成为第二写入口。

Conversation 的个人知识读取投影由 Application 内的 `ConversationKnowledgeReadAdapter` 实现既有 Port，消费同一 `KnowledgeService`；组合根负责构造与注入。当前实现坐标见[代码地图](code-map.md#2-从功能进入代码)。

## 3. 正式入口与对话主链

普通用户只需表达目标，不需先选择 Tool 或 Workflow。Web、CLI 和飞书最终复用 `AgentService.converse()` 与 `ConversationService`。已知的业务操作可以直接进入对应 Application Use Case，但必须复用同一 canonical 写入口。

`ConversationService` 在一次对话运行内反复决策和处理结果，直至返回交付、待确认、澄清或限制结果，或遇到运行错误。主链包括：

1. 恢复已提交消息、当前工作项清单和可重读执行结果。
2. 从注册定义、服务可用性和曝光规则生成 `EffectiveCapabilities`；能力投影与调用授权的区别见 [Context](../topics/context-engineering.md#visibility-的定义与分层)。
3. 将用户目标、已提交 `Observation`、反馈及适用的步骤接续信息物化到 LLM Context。
4. 动作相位由模型原生调用提出业务动作或独立工作清单控制；Application 对 Proposal 做 Schema、曝光、权限、预算和业务准入。
5. 已准入动作经 Tool/Agent/Application 执行入口产生 `Observation`，回到同一循环。
6. 模型以完整正文提交普通答复，以 `control_report_turn_status` 报告限制或失败；两条入口产生同一类 `FinalMessage`。Runtime 保存 `SubmittedFinal`，执行适用核验及领域检查后交付同一稿件。拒稿后，原循环可继续取证或完整重提。提交规格见 [ADR 0055](../adr/0055-unified-conversation-answer.md)，检索实验的领域检查见 [ADR 0037](../adr/0037-experiment-submission-first-delivery.md)。
7. 运行系统按装配契约完成适用核验和 Completion，交付确切 `FinalMessage` 正文。用户授权的无语义核验诊断不产生通过回执，也不计完整产品 E2E；边界见 [ADR 0050](../adr/0050-verification-feature-flags.md)。

Conversation 约束每个用户轮次先维护目标。`submit_goal_patch` 提交任务选择和版本化条目增量，`read_current_goal` 可按需读取生效快照。Journal 保存任务归属、执行控制和已接纳补丁。主循环、代码与回答核验从同一可见分支的选中任务恢复适用历史。启用目标核验时，通过后提交任务归属和增量。[任务切换上下文](../context/agent-loop.md#同一对话中的任务切换)

相位、提交与重试见 [Runtime](../topics/runtime.md)，判据与交付边界见[核验专题](../topics/verification-and-completion.md)。

当前[职责分离设计](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)将非读取目标操作接到目标定义核验，将最终交付接到回答核验。两者复用原执行网关与回执，使用独立提示、判据及同职责历史；目标通过不代表交付完成。

`ConversationWorkingPlan` 只协调当前对话的可验收工作项。模型可以根据用户调整提出新版本，Application 保护已完成事实和新旧版本边界。工作项清单不拥有 queue、lease、审批或 Agent 运行事实。

### 3.1 当前主循环的职责混合

启用目标核验时在目标写入前核验任务定义，启用回答核验时在普通交付前核验实际回答。`task_context.kind`由Runtime绑定，`turns`按用户轮次保留完整原话，events只含本职责的提议及对应判决、修订；每个回答事件从当时已接受目标操作恢复确切 passed 回执作为 `verified_goal`，跨轮及同轮目标修订不会覆盖旧回答。核验请求逐条呈现原话、提交及判决，通过报告在主循环与核验发送投影中精简，失败反馈完整。原Journal为唯一事实来源，准入和完成消费原报告，主循环原生调用配对保持。摘要按职责独立绑定，普通工具材料不交给核验；契约见[ADR0047](../adr/0047-user-goal-verification-context.md)，机制与限定证据见[固化方案](../optimization/completed/verification-context-goal-binding.md)。

上述主链是责任说明，当前实现尚未完整隔离各职责。`answer_results.py` 解释完整正文及结构化提交；`ConversationService` 仍驱动请求、适用核验、Journal 和部分 Context 物化。原生协议的生成、交付及恢复证据见 [Loop 运行结果](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)。

网页及其他工具回执供主模型写作，不切换交付协议。周期 `ResearchService` 另有订阅、调度和投递生命周期。

### 3.2 会话、运行与主决策的现状

**Session** 由认证主体和 `session_id` 确定。Journal 在同一会话内按已提交顺序追加 Turn。Conversation 按任务和可见性选择适用前史。

**Turn** 由 `InteractionTrace` 持有。新输入创建 `turn_id`，查询、确认和恢复使用原标识。Conversation 校验主体、会话、输入和适用执行绑定。SQLite 记录每轮的原话和已冻结的前驱修订。内部 `interaction_run_ref` 承载同一轮次身份。

**Step** 对应 Turn 中的一次主模型决策。Journal 在登记请求原件时分配 `step_no`，逻辑调用用 `invocation_id` 定位；重试消费原调用身份。历史和压缩从原决策记录读取顺序和对应结果。`ConversationWorkingPlanStep` 表达业务工作项。[代码坐标](code-map.md#2-从功能进入代码) · [生命周期 Spec](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)

续聊只提交当前用户输入。主循环读取已提交前驱，再恢复用户原话、已交付答复和适用的原生工具交互。[生命周期 Spec](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期)。

## 4. 后台持续运行边界

当前 Conversation 只在请求内执行 Tool 或委托 Agent；GPT Researcher 是 `AgentGateway` 后的执行资源，不拥有第二套业务 Plan、Completion 或研究循环。明确要求响应结束后继续运行、稍后查询、暂停或调整的输入，经已接纳目标中的交付方式识别后返回 `limitation`。

周期 Research、知识缺口提问和复习简报有各自的调度入口，由 Web Context 装配。它们执行已定义的业务任务，不意味着 Conversation 已支持任意目标的后台接续。

旧后台调查的 Application、Aggregate、持久化、API 和 worker 已按 [ADR 0015](../adr/0015-withdraw-investigation-project.md)删除。普通 Conversation 研究仍有独立质量缺口；最新执行结果和失败边界只由[评测盘点](../evals/02-current-case-inventory.md)维护。

## 5. Context、Memory 与检索

Memory 不等于单一长期记忆库。当前代码按生命周期区分六类责任：

| 类型 | 责任 |
| --- | --- |
| Agent State | 保存当前运行需要的小型结构化状态 |
| LLM Context | 保存本次模型调用实际可见的临时内容 |
| Checkpoint | 保存恢复执行所需快照，不作为知识事实源 |
| Artifact Store | 保存大文本、文件和中间产物，State 优先保存 `ArtifactRef` |
| Long-term Memory | 保存跨会话可召回的用户事实或经验 |
| Retrieval Index | 为召回构建可重建投影，不是业务事实源 |

Context 按 `Visibility -> Requirement Retrieval -> Semantic Selection -> Budget Materialization` 处理。权限和作用域过滤必须早于语义召回；检索命中不会自动把内容提升为 canonical fact。详细契约分别由 [Memory 设计](../topics/memory.md)和 [Context Engineering](../topics/context-engineering.md)拥有。

## 6. 工具、MCP 与智能体

工具执行主链是“临时能力投影 -> Proposal -> Schema/曝光校验 -> Policy/Admission -> 执行网关 -> Observation -> Verification/Completion”。模型看到的 Tool Schema 从注册定义与当前能力集合物化；资源读取按身份过滤，工具调用由 Admission/Gateway 授权，投影不代表获准执行。

MCP 发现提供远端工具名和 Schema。部署映射声明本地名称、风险、权限范围与结果契约。`AgentService` 持有 MCP 客户端，`bind_mcp_tools()` 发现并绑定工具，`AgentRuntime` 校验名称后注册。Conversation 按当前主体与渠道投影已注册能力。Policy 拥有判定，ToolGateway 只派发允许的调用。部署可将工作区写入映射交给独立 Application，通过正式确认端口执行并持有回执。宿主结束时关闭所持客户端，stdio 断线后由显式重启建立新会话。[工具派发门禁](../adr/0052-tool-policy-dispatch-gate.md) · [装配与关闭](../adr/0051-mcp-client-lifecycle.md) · [工作区授权](../adr/0053-workspace-change-approval.md)

智能体委托通过 `AgentGateway` 和类型化 `DelegationGrant` 执行。子运行的 definition、submission binding、status 和 `ArtifactRef` 由智能体运行存储拥有；父级 Application 仍负责判断子结果是否满足用户目标。用户取消和预算超时分别记录为 `cancelled` 与 `timed_out`，两者不共用一个业务原因。

## 7. 模型与服务提供方边界

模型调用的正式 Port 是 `StructuredModelClient`，由组合根注入，覆盖结构化、原生工具调用和文本请求。默认结构化承载按 `StructuredConfig.output_transport` 选择 `StrictJsonSchemaAdapter` 或 `JsonObjectStructuredAdapter`；请求也可明确声明 `native_tool` 或 `prompted_json`，均由同一 Pydantic 契约校验结果。

模型适配的阅读入口按职责组织：`infra/structured_model.py` 拥有公开工厂、SDK 调用、超时、协议修复、重试与观测装配；`infra/model_response.py` 集中响应 envelope、流内容、原生动作调用和用量归一化。现有 Adapter 与计量包装器直接消费这些解析函数，业务准入仍由 Application 拥有。解析规则的局部修改从新模块及其 typed 契约进入，调用与恢复问题从原适配入口进入。

Conversation 普通主请求使用 `auto`。没有工具调用时，`AnswerResult` 将完整合法的 assistant 正文转为 `FinalMessage` 候选。显式提交可以携带沟通状态和引用。稿件拒绝后沿同一循环修复。Conversation 在目标待维护阶段使用 `required`，提供增量、已有目标查询、澄清及受限结束动作。补丁接纳后，按执行控制开放业务工具及 `auto`。交付方式和验收条件来自已接纳目标。[主循环上下文](../context/agent-loop.md) · [Loop Spec](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)

模型工厂以显式包装器组合单次调用准入、观测、用量和重试，实际顺序、SDK 流式 transport 与正式 SSE 的边界见[横切机制](cross-cutting.md#2-模型调用的实际组合)。模型配置见[生成式模型配置](../env.md#llm-配置)；JSON Object Adapter 把版本化 Schema instruction 与 Pydantic 校验绑定，不做运行时 transport 降级。网页搜索绑定与正文读取配置由[工具专题](../topics/tools.md)和[环境配置](../env.md)拥有。配置只证明部署选择，不证明服务健康或产品结果。

GPT Researcher 在独立进程中运行，不会继承主工程的 `STRUCTURED_OUTPUT_TRANSPORT`。远端 `choose_agent()` 的自由文本 JSON 处理属于 GPT Researcher 调用边界，不能通过切换主工程 Adapter 修复。

## 8. 持久化、恢复与观测

PostgreSQL 保存业务 Aggregate 认可的 canonical facts、必要 journal、queue/lease 和幂等执行事实。Artifact Store 保存大结果；其他状态只保存带责任主体和作用域的资源引用。

组合根注入 `SqliteInteractionJournal`。Turn 及修订由 SQLite 提交，模型请求与响应原件按轮次和调用保存为文件。对话历史、压缩输入和用户返回视图从已提交记录投影。待确认命令及副作用回执沿所属业务入口恢复。普通 MCP 写调用由 Conversation 在工具派发前登记。恢复时缺少原结果的已登记写调用生成未知回执，交回原轮次的模型决策。[Conversation 恢复坐标](code-map.md#2-从功能进入代码) · [MCP 派发与恢复](../mcpDesign/README.md#普通-mcp-写调用的进程恢复)

会话锁内，Journal 复用同一主体、会话和修订下已校验的当前轮与前驱。数据库在每次读取时确定实际修订，释放会话锁后释放该次解码视图。轮内修订以增量提交，首次终态保存完整快照，恢复时从最近快照重建所需修订。[读取机制与验收](../optimization/to_verify/conversation-loop-boundaries.md#轮内增量修订)

恢复必须重放已冻结的 Command 和执行事实，不得重新调用模型生成 Command，也不得重复外部副作用。幂等 digest、submission key、Receipt 和 journal 只在确有审批、跨请求恢复或外部结果关联时使用。

Trace、event、receipt 和评测归档记录事实，不改变生产决策。发布资格只由匹配代码身份、配置样本组、评测器、追踪记录和 checksum 的证据建立。

策略决定以 `PolicyDecisionEvent` 传给所属 Runtime 的 `PolicyDecisionRecorder`，由组合根将本实例存储绑定到三个调用点；日志与可选持久化不再通过全局 setter 路由。可选 sink 错误隔离及实际验收边界见[横切机制](cross-cutting.md#4-横切实现的强制边界)和 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)。

## 9. 当前不变量

事实归属、唯一写入口与依赖方向由 [ARC](../devSpec/architecture-ownership.md)约束；Proposal、准入、执行和完成的边界由 [EXE](../devSpec/agentic-execution.md)约束；跨层类型和 Prompt 契约由 [COD](../devSpec/code-structure.md)约束。这些是维护门禁，具体实现与差异按上文和代码地图核对。

## 10. 当前证据边界

- Conversation、Memory、Tool 和多种治理机制已有各自限定范围的实际证据，不能拼成“所有智能体能力都已交付”。
- Conversation 的任意目标后台持续调查当前不是产品能力；普通 Conversation 使用工具资料完成答复，外部资料任务的完整用户结果按对应证据验收。
- 定向 E2E、Offline Eval 和历史回归只支持已声明范围；当前发布资格须绑定目标代码与完整产品矩阵。单元测试按 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)停用。

证据结论、命令和归档坐标不在本文重复维护，统一见：

- [当前端到端用例盘点](../evals/02-current-case-inventory.md)；
- [Baseline-first 审计](../evals/03-baseline-first-audit.md)；
- [评测执行与发布](../evals/04-running-and-release.md)；
- [设计优化队列](../future/design-optimization-backlog.md)。

独立分析的目标核验与回答核验已按职责拆分，当前契约见[Spec §9.14](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)。两者分别输出`UserRequirementAssessment`并聚合为原回执；新连续前三轮已交付，原分[1,1,1]、预声明用户结果通过／通过／失败，见[记录§34](../optimization/to_verify/verify_results/analysis-correctness.md#34-分离目标与回答核验的空会话连续前三轮)；旧失败由[记录§33](../optimization/to_verify/verify_results/analysis-correctness.md#33-逐项用户要求核验的空会话连续前三轮)保留。
