# personalAgent 当前核心架构

> 本文按现行代码说明全局责任和主链；实际包布局见[代码地图](code-map.md)，横切装配见[横切机制](cross-cutting.md)。实际结果按[评测盘点](../evals/02-current-case-inventory.md)中的归档身份解释，未闭环事项见[设计优化队列](../future/design-optimization-backlog.md)。

## 1. 核心判断

personalAgent 是一个受治理的知识智能体。模型负责开放世界语义判断，确定性系统负责权限、准入、状态迁移和不变量；执行系统产生事实，Verifier 判断目标是否语义满足，Completion 门禁检查必需结果契约是否齐全。

目标与结果核验默认开启，由 Settings 读取 typed feature flags，经 AgentRuntime 注入原回答模块和 Conversation，在 Journal 的运行及对话边界固定。关闭仅用于已登记的机制消融装配，接纳事实和未核验目标不会伪装为语义通过；具体契约由[实验组 1](../ablation/experiment.md)与 [ADR 0050](../adr/0050-verification-feature-flags.md)拥有。

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

`ConversationService` 的每轮运行依次完成：

1. 恢复已提交消息、当前工作项清单和可重读执行结果。
2. 从注册定义、服务可用性和曝光规则生成 `EffectiveCapabilities`；能力投影与调用授权的区别见 [Context](../topics/context-engineering.md#visibility-的定义与分层)。
3. 将用户目标、已提交 `Observation`、反馈和预算物化到 LLM Context。
4. 动作相位由模型原生调用提出业务动作或独立工作清单控制；Application 对 Proposal 做 Schema、曝光、权限、预算和业务准入。
5. 已准入动作经 Tool/Agent/Application 执行入口产生 `Observation`，回到同一循环。
6. 回答模块按部署提供普通完整提交或claim选证／写作操作。普通回答拒稿后沿原Loop继续取证或完整重提，不提供答案按段修订工具，见[ADR0049](../adr/0049-answer-regeneration-in-original-loop.md)。模型提交完整候选，运行系统持久化`SubmittedFinal`，再执行适用核验及领域文件检查，通过后交付同一稿件。模型协议见[ADR0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)，检索实验的领域检查见[ADR0037](../adr/0037-experiment-submission-first-delivery.md)。
7. 运行系统按装配契约完成适用核验和 Completion，交付确切 `FinalMessage` 正文。用户授权的无语义核验诊断不产生通过回执，也不计完整产品 E2E；边界见 [ADR 0041](../adr/0041-replaceable-answer-result-modules.md)。

独立Python direct分析由Conversation约束每轮先维护目标；`maintain_goal`完整写入、`retain_goal`沿用及可选的`read_current_goal`共用原Journal目标事实。目标正文只保留一个`objective`字符串，不另存成果引用；每次主请求物化当前完整目标，读取仅供按需查看，不是回答或修复的前提，也不修改版本；目标提议先语义核验，通过后维护成功事实。现行契约与验证边界见[目标维护 Spec §9.9](../optimization/to_verify/analysis-goal-maintenance.md#99-单一目标正文与取消目标内成果引用)。

当前相位、研究接入和重试契约分别由 [Runtime](../topics/runtime.md)、[核验专题](../topics/verification-and-completion.md)和 [ADR 0032](../adr/0032-conversation-research-claims.md)拥有。

当前[职责分离设计](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)将非读取目标操作接到目标定义核验，将最终交付接到回答核验。两者复用原执行网关与回执，使用独立提示、判据及同职责历史；目标通过不代表交付完成。

`ConversationWorkingPlan` 只协调当前对话的可验收工作项。模型可以根据用户调整提出新版本，Application 保护已完成事实和新旧版本边界。工作项清单不拥有 queue、lease、审批或 Agent 运行事实。

### 3.1 当前主循环的职责混合

独立Python分析的direct路径在目标写入前核验任务定义，required路径在交付前核验实际回答。`task_context.kind`由Runtime绑定，`turns`按用户轮次保留完整原话，events只含本职责的提议及对应判决、修订；每个回答事件从当时已接受目标操作恢复确切 passed 回执作为 `verified_goal`，跨轮及同轮目标修订不会覆盖旧回答。核验请求逐条呈现原话、提交及判决，通过报告在主循环与核验发送投影中精简，失败反馈完整。原Journal为唯一事实来源，准入和完成消费原报告，主循环原生调用配对保持。摘要按职责独立绑定，普通工具材料不交给核验，原claims与来源核验路径保持；契约见[ADR0047](../adr/0047-user-goal-verification-context.md)，机制与限定证据见[固化方案](../optimization/completed/verification-context-goal-binding.md)。

上述主链是责任说明，当前实现尚未把这些责任完整隔离。`answer_results.py` 提供可替换的直接／claim 操作定义、提交解释和同稿接纳；`ConversationService` 继续驱动请求、Journal、研究适用性与部分 Context 物化。原生协议已接入，直接回答装配的实际生成、连续交付及恢复范围见 [Loop 运行结果](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)；研究子流程的职责拆分仍是候选。

claim 操作的适用性取决于 writer 装配、冻结标准、当前稿和已成功 Web 来源。来源出现使选证操作可用，写作仍由模型选择；周期 `ResearchService` 另有订阅、调度和投递生命周期。

默认 required 核验装配下，普通最终答案只有 `ReviewCriteria.requires_review` 成立才调用整稿核验；研究交付消费同版本统一报告。普通核验器固定追加通用来源标准，现有计算样本已经出现范围和支持判断缺口，语义修复仍暂放，见[现状与候选](../optimization/to_verify/conversation-loop-boundaries.md)。完整研究子流程封装仍是候选；当前只替换回答提交模块，不新增第二套模型循环。

## 4. 后台持续运行边界

当前 Conversation 只在请求内执行 Tool 或委托 Agent；GPT Researcher 是 `AgentGateway` 后的执行资源，不拥有第二套业务 Plan、Completion 或研究循环。明确要求响应结束后继续运行、稍后查询、暂停或调整的输入，会在交互意图派生后返回 typed limitation，并记录 `capability_missing`。

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

MCP discovery 拥有远端名称和 Schema 观测；本工程 mapping 拥有曝光名称、风险、权限范围和结果契约。只有已受治理的 mapping 才能进入 `EffectiveCapabilities`。

智能体委托通过 `AgentGateway` 和类型化 `DelegationGrant` 执行。子运行的 definition、submission binding、status 和 `ArtifactRef` 由智能体运行存储拥有；父级 Application 仍负责判断子结果是否满足用户目标。用户取消和预算超时分别记录为 `cancelled` 与 `timed_out`，两者不共用一个业务原因。

## 7. 模型与服务提供方边界

模型调用的正式 Port 是 `StructuredModelClient`，由组合根注入，覆盖结构化、原生工具调用和文本请求。默认结构化承载按 `StructuredConfig.output_transport` 选择 `StrictJsonSchemaAdapter` 或 `JsonObjectStructuredAdapter`；请求也可明确声明 `native_tool` 或 `prompted_json`，均由同一 Pydantic 契约校验结果。

模型适配的阅读入口按职责组织：`infra/structured_model.py` 拥有公开工厂、SDK 调用、超时、协议修复、重试与观测装配；`infra/model_response.py` 集中响应 envelope、流内容、原生动作调用和用量归一化。现有 Adapter 与计量包装器直接消费这些解析函数，业务准入仍由 Application 拥有。解析规则的局部修改从新模块及其 typed 契约进入，调用与恢复问题从原适配入口进入。

Conversation普通主请求使用`auto`，优先处理工具调用。没有调用时，`AnswerResult`将完整合法的assistant正文转为`FinalMessage`候选；显式submit_final可携带沟通属性及引用。普通稿被拒后沿同一Loop完整重提，claims继续使用自己的业务编辑。候选沿同一`SubmittedFinal`、核验与Completion链交付，正文、Verifier原稿及回执digest使用同一原字符串。独立Python direct分析仍由主模型直接理解并行动，无前置criteria调用；每个用户轮次先提供目标维护工具并使用`required`（首次仅maintain_goal，已有目标再提供retain_goal），目标核验及真实成功回执成立后恢复完整工具面及`auto`；未维护时可用独立澄清操作向用户提问，或用 submit_final 提交限制或失败。测试模式按模型工具禁用名单关闭澄清。目标事实由原Journal保存，目标与Runtime反馈持续进入原上下文，协议及待验语义见[ADR0048](../adr/0048-conversation-goal-maintenance.md)。其他已有意图提取消费者使用prompted_json，原生typed输出请求使用required工具，修复沿用各自承载。原完整运行证据见[Loop Spec](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)。

模型工厂以显式包装器组合单次调用准入、观测、用量和重试，实际顺序、SDK 流式 transport 与正式 SSE 的边界见[横切机制](cross-cutting.md#2-模型调用的实际组合)。模型配置见[生成式模型配置](../env.md#llm-配置)；JSON Object Adapter 把版本化 Schema instruction 与 Pydantic 校验绑定，不做运行时 transport 降级。网页搜索绑定与正文读取配置由[工具专题](../topics/tools.md)和[环境配置](../env.md)拥有。配置只证明部署选择，不证明服务健康或产品结果。

GPT Researcher 在独立进程中运行，不会继承主工程的 `STRUCTURED_OUTPUT_TRANSPORT`。远端 `choose_agent()` 的自由文本 JSON 处理属于 GPT Researcher 调用边界，不能通过切换主工程 Adapter 修复。

## 8. 持久化、恢复与观测

PostgreSQL 保存业务 Aggregate 认可的 canonical facts、必要 journal、queue/lease 和幂等执行事实。Artifact Store 保存大结果；其他状态只保存带责任主体和作用域的资源引用。

恢复必须重放已冻结的 Command 和执行事实，不得重新调用模型生成 Command，也不得重复外部副作用。幂等 digest、submission key、Receipt 和 journal 只在确有审批、跨请求恢复或外部结果关联时使用。

Trace、event、receipt 和评测归档记录事实，不改变生产决策。发布资格只由匹配代码身份、配置样本组、评测器、追踪记录和 checksum 的证据建立。

策略决定以 `PolicyDecisionEvent` 传给所属 Runtime 的 `PolicyDecisionRecorder`，由组合根将本实例存储绑定到三个调用点；日志与可选持久化不再通过全局 setter 路由。可选 sink 错误隔离及实际验收边界见[横切机制](cross-cutting.md#4-横切实现的强制边界)和 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)。

## 9. 当前不变量

事实归属、唯一写入口与依赖方向由 [ARC](../devSpec/architecture-ownership.md)约束；Proposal、准入、执行和完成的边界由 [EXE](../devSpec/agentic-execution.md)约束；跨层类型和 Prompt 契约由 [COD](../devSpec/code-structure.md)约束。这些是维护门禁，具体实现与差异按上文和代码地图核对。

## 10. 当前证据边界

- Conversation、Memory、Tool 和多种治理机制已有各自限定范围的实际证据，不能拼成“所有智能体能力都已交付”。
- Conversation 的任意目标后台持续调查当前不是产品能力；普通 Conversation 的研究链路已接入代码，完整用户结果仍须按对应证据验收。
- 定向 E2E、Offline Eval 和历史回归只支持已声明范围；当前发布资格须绑定目标代码与完整产品矩阵。单元测试按 [QLT](../devSpec/quality-security.md#1-测试职责与覆盖)停用。

证据结论、命令和归档坐标不在本文重复维护，统一见：

- [当前端到端用例盘点](../evals/02-current-case-inventory.md)；
- [Baseline-first 审计](../evals/03-baseline-first-audit.md)；
- [评测执行与发布](../evals/04-running-and-release.md)；
- [设计优化队列](../future/design-optimization-backlog.md)。

独立分析的目标核验与回答核验已按职责拆分，当前契约见[Spec §9.14](../optimization/to_verify/analysis-goal-maintenance.md#914-分离目标核验与回答核验的职责及历史)。两者分别输出`UserRequirementAssessment`并聚合为原回执；新连续前三轮已交付，原分[1,1,1]、预声明用户结果通过／通过／失败，见[记录§34](../optimization/to_verify/verify_results/analysis-correctness.md#34-分离目标与回答核验的空会话连续前三轮)；旧失败由[记录§33](../optimization/to_verify/verify_results/analysis-correctness.md#33-逐项用户要求核验的空会话连续前三轮)保留。
