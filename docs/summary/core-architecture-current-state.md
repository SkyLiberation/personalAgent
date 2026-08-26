# personalAgent 当前核心架构

> 本文只记录 2026-08-26 生产代码中仍成立的责任边界和主链。产品证据由[当前端到端用例盘点](../evals/02-current-case-inventory.md)拥有，尚未准入的设计由[设计优化队列](../future/design-optimization-backlog.md)拥有。本文不复制历史归档、候选方案或发布结论。

## 1. 核心判断

personalAgent 是一个受治理的知识智能体。模型负责开放世界语义判断，确定性系统负责权限、准入、状态迁移和不变量；执行系统产生事实，Verifier 判断目标是否语义满足，Completion 门禁检查必需结果契约是否齐全。

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

稳定依赖方向是 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 只依赖 Port，运行系统和服务提供方 Adapter 从外层实现 Port，`AgentRuntime` 在组合根集中装配。

| 层次 | 当前责任 | 禁止承担 |
| --- | --- | --- |
| Interface | Web、CLI 和飞书的协议转换、身份解析与输入校验 | 补全业务语义、直接改写 Aggregate |
| Application Capability | 接收 Use Case，协调领域、模型、治理和执行 Port | 复制领域迁移、伪造执行成功 |
| Domain / Product Aggregate | 拥有 canonical business facts、合法迁移和核心不变量 | 依赖 ORM、LangGraph、网络或模型 SDK |
| Runtime Mechanism | 执行 Tool/Agent、管理 queue/lease、checkpoint、Artifact 与 Trace | 决定用户意图、业务计划或完成结论 |
| Projection / DTO | 按身份和 Policy 物化临时可见能力与读取视图 | 成为定义或可用性的第二写入口 |

`AgentService` 是外部入口使用的统一外观；`AgentRuntime` 是组合根，二者都不拥有业务事实。

## 3. 正式入口与对话主链

普通用户只需表达目标，不需先选择 Tool、Workflow 或 Project。Web、CLI 和飞书最终复用 `AgentService.converse()` 与 `ConversationService`。已知的业务操作可以直接进入对应 Application Use Case，但必须复用同一 canonical 写入口。

`ConversationService` 的每轮运行依次完成：

1. 恢复已提交消息、当前工作项清单和可重读执行结果。
2. 按身份、权限范围和 Policy 生成 `EffectiveCapabilities`。
3. 将用户目标、已提交 `Observation` 和当前预算物化到 LLM Context。
4. 模型产生 `FinalMessage` 或 `ContinueTurnProposal`。
5. Application 对 Proposal 做 Schema、曝光、权限、预算和业务准入。
6. 已准入的 Tool/Agent/Application action 经对应执行网关产生 `Observation`。
7. 最终回答在 Verification 和 Completion 门禁后才能发送。

前台 `ConversationWorkingPlan` 只协调当前对话的可验收工作项。模型可以根据用户调整提出新版本，Application 保护已完成事实和新旧版本边界。工作项清单不保存 Project 的 ready set、queue、lease、审批、外部委托预算或 Completion obligation。

## 4. Durable Investigation Project

`InvestigationProject` 只用于需要跨请求、进程或用户轮次维持独立生命周期的调查。Conversation 可以创建 Project 并保存 `ProjectReference`；Project definition、accepted Plan、journal、budget、Outcome 和 Completion 仍由 Project Aggregate 拥有。

```text
创建 Project -> 入队 -> worker 恢复 journal
  -> Planner Proposal -> Plan Admission -> accepted Plan
  -> ready set -> Execution Proposal -> Tool / Agent / synthesis
  -> Evidence Admission -> Verification -> SubGoalOutcome
  -> Completion -> final ArtifactRef / report
```

初始 Plan 定义完整待执行图，修订 Plan 只能修改未冻结部分。普通修订和 verification repair 共享单一 `_PlanRevisionDraft`；repair 字段只在存在冻结 gap 时由动态 Schema 开放。已发生的 Proposal、ExecutionRef、Artifact 和 Outcome 不会被新 Plan 覆盖。

当前调查入口和后台生命周期可达，但当前 MiMo + GPT Researcher 样本组没有交付最终报告。该路径不是已稳定交付的产品能力；完整证据边界见[调查项目当前状态](durable-investigation-project-current-state.md)。

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

工具执行主链是“临时能力投影 -> Proposal -> Schema/曝光校验 -> Policy/Admission -> 执行网关 -> Observation -> Verification/Completion”。模型看到的 Tool Schema 是按当前身份生成的只读投影，不是工具注册真源。

MCP discovery 拥有远端名称和 Schema 观测；本工程 mapping 拥有曝光名称、风险、权限范围和结果契约。只有已受治理的 mapping 才能进入 `EffectiveCapabilities`。

智能体委托通过 `AgentGateway` 和类型化 `DelegationGrant` 执行。子运行的 definition、submission binding、status 和 `ArtifactRef` 由智能体运行存储拥有；父级 Application 仍负责判断子结果是否满足用户目标。用户取消和预算超时分别记录为 `cancelled` 与 `timed_out`，两者不共用一个业务原因。

## 7. 模型与服务提供方边界

Application 只依赖 `StructuredModelClient`。组合根根据 `StructuredConfig.output_transport` 选择 `StrictJsonSchemaAdapter` 或 `JsonObjectStructuredAdapter`；两者都在调用边界携带 Schema，并将结果物化为同一 Pydantic 契约。

当前本地配置使用 `mimo-v2.5 + json_schema`，关闭 thinking；网页搜索显式绑定 AnySearch，URL 正文读取绑定 builtin。配置只证明部署选择，不证明服务健康或产品结果。

GPT Researcher 在独立进程中运行，不会继承主工程的 `STRUCTURED_OUTPUT_TRANSPORT`。远端 `choose_agent()` 的自由文本 JSON 处理属于 GPT Researcher 调用边界，不能通过切换主工程 Adapter 修复。

## 8. 持久化、恢复与观测

PostgreSQL 保存业务 Aggregate 认可的 canonical facts、必要 journal、queue/lease 和幂等执行事实。Artifact Store 保存大结果；其他状态只保存带责任主体和作用域的资源引用。

恢复必须重放已冻结的 Command 和执行事实，不得重新调用模型生成 Command，也不得重复外部副作用。幂等 digest、submission key、Receipt 和 journal 只在确有审批、跨请求恢复或外部结果关联时使用。

Trace、event、receipt 和评测归档记录事实，不改变生产决策。发布资格只由匹配代码身份、配置样本组、评测器、追踪记录和 checksum 的证据建立。

## 9. 当前不变量

1. 一个业务事实只有一个 canonical model、责任主体和合法写入口。
2. 身份、作用域、digest 和资源引用跨层时使用 typed contract。
3. Admission 只接受或拒绝 Proposal，不补业务字段或生成替代目标。
4. 最终回答不能由工具成功、子智能体终态或 Verifier 自述直接推导。
5. Application 能力定义归对应 Application Use Case；模型可见菜单只是按当前身份生成的投影。
6. 固定事务不为形式统一包装为 Planner、Workflow、Command、Event 或 Project。
7. 产品能力只能由正式入口的用户结果证明；内部对象和 Trace 只能用于定位。

## 10. 当前证据边界

- Conversation、Memory、Tool 和多种治理机制已有各自限定范围的实际证据，不能拼成“所有智能体能力都已交付”。
- Durable Investigation Project 当前仍为失败的产品路径；局部 Plan、调度或预算机制通过不等于最终报告交付。
- 当前工作树的全量单元/集成回归通过不等于 clean-revision 发布资格。

证据结论、命令和归档坐标不在本文重复维护，统一见：

- [当前端到端用例盘点](../evals/02-current-case-inventory.md)；
- [Baseline-first 审计](../evals/03-baseline-first-audit.md)；
- [评测执行与发布](../evals/04-running-and-release.md)；
- [设计优化队列](../future/design-optimization-backlog.md)。
