# Durable Investigation Project 长任务能力目标设计

> 状态：目标设计，尚未实现。本文不描述当前生产能力，也不构成“已验证”声明。
> 当前事实由 [`core-architecture-current-state.md`](../summary/core-architecture-current-state.md)
> 和 [`phase0-capability-release-baseline.md`](../summary/phase0-capability-release-baseline.md)
> 所有。实施完成后将事实迁入 summary/workflow/API/运维文档并删除本文。

## 1. Goal

增加一个具体产品能力：**架构调查项目（Investigation Project）**。

用户可以创建一个需要几十分钟到数天、跨仓库、GitHub、Notion、网页和 bounded specialist
Agent run 的调查项目，例如：

> 综合当前仓库、GitHub issue、Notion 设计文档和外部资料，分析架构、安全、成本与迁移风险；
> 过程中允许我补充约束、批准受控外发或取消分支；服务重启后继续，最终交付带证据的完整报告。

这个业务需要：

- 动态子目标和依赖，不能完全由固定 Workflow 预先展开；
- Tool 与 Agent run 并行执行，依赖满足后确定性 join；
- 任务跨进程、跨用户轮次和授权边界；
- Observation 或用户 steering 只能修订尚未冻结的工作；
- Tool/Agent success、Artifact 存在和模型自述均不能直接代表项目完成；
- 所有 required deliverable 必须被 admitted evidence 支持并通过验证。

进入 Project 不能只看耗时，必须同时满足“动态路径”和“durable lifecycle”：

| 任务特征 | 生产路径 |
| --- | --- |
| 路径固定、可在一次请求完成 | 普通 Workflow/Use Case |
| 路径局部动态、无需跨轮次恢复 | Conversation ReAct |
| 耗时很长但拓扑固定 | Durable Domain Workflow |
| 路径由 Observation 动态改变，且跨进程/用户轮次/审批 | Investigation Project |

例如批量导入一万篇文档即使运行数小时，也应使用固定 durable Workflow；只有运行前无法可靠
确定 SubGoal/依赖，并需要跨恢复边界维持交付契约时，才创建 Investigation Project。

第一版模型、状态和存储属于 `InvestigationProject` 领域。没有第二个真实业务及同构 E2E
前，不抽取通用 `DurableTask` framework。

## 2. Current Incorrect Behavior and Simplest Baseline

当前最简单 baseline 有三类：

| 任务形态 | 当前路径 | 已知边界 |
| --- | --- | --- |
| 短、动态 | Conversation ReAct loop | 受单次 Interaction 预算约束；WorkingPlan 不驱动 durable 调度 |
| 长、固定拓扑 | ResearchRun、Scheduled Intelligence、Delete/Restore | 领域 Workflow 和状态机可以预定义 |
| 单次外部委托 | AgentGateway + ChildAgentRun | bounded sub-goal；当前 store 和父任务依赖不是 durable Project |

`WorkingPlanSnapshot` 只回注 Prompt 和 trace，不计算 ready set、dispatch、progress、coverage 或
Completion。当前 Conversation 崩溃恢复只重建已提交 Interaction facts，不保存 durable
SubGoal 依赖和交付义务。

因此当前路径不能机械保证：

1. Interaction 预算耗尽后等待用户并继续同一语义项目；
2. worker 重启后不重复外部 Command 或 child submission；
3. 多个 child completed 后父项目仍按 deliverable coverage 判断完成；
4. steering 不覆盖已审批 Command、已完成 Outcome 或既有 Artifact；
5. tenant/workspace/project scope 贯穿 Connector、Agent、Artifact 和恢复状态。

这些结论必须由 Stage 0 两组 baseline E2E 冻结：

- Conversation ReAct 对照证明 durable lifecycle 的必要性；
- 固定 Durable Workflow 对照证明 Observation-driven Plan 的必要性。

本文和外部评估都不能替代已执行证据。

## 3. Required Production Capabilities and Missing-capability Delivery

### 3.1 能力基线

下表区分“已有基础”“需扩展”和“缺失”。“已有”只表示生产代码存在；发布可信度仍由同
revision E2E 决定。

| 所需能力 | 当前基础 | 判定 | 本设计中的落地 |
| --- | --- | --- | --- |
| structured semantic decision | `StructuredModelClient` | 已有基础 | 新增 Project Planner、Execution Proposer、Verifier typed schema 与 Golden Set |
| GitHub/Notion 读取 | MCP Host、ToolGateway、可选 profile | 已有基础 | 同一 Project capability snapshot 中联合装配并做 scope/availability admission |
| 网页研究 | Web search/Research、GPT Researcher A2A | 已有基础 | 作为 Tool 或 registered Agent profile 使用，不创建测试专用 Provider |
| capability resolution | Registry/Resolver、EffectiveCapabilities | 需接入 | Project 使用真实 inventory；Plan 不直接获得授权 |
| Tool 执行 | ToolGateway policy/idempotency/audit | 需扩展 scope | 使用 typed Project scope、accepted execution proposal 和 execution ref |
| child lifecycle | AgentGateway submit/poll/cancel | 能力不足 | 增加 durable run store、幂等 submit、reconcile、callback admission 和 late disposition |
| governed external delegation | A2A data egress +领域专用 delete/restore approval | 缺失 | 新增 `InvestigationExternalDelegationCommand` 及 Project approval use case |
| generated report Artifact | upload-oriented ArtifactService | 缺失 | 扩展唯一 Artifact owner，增加 scoped generated Artifact 写入口 |
| project journal/scheduler | worker queue、durable run/journal primitives | 缺失 | 新增 Project aggregate/store/scheduler；不恢复旧通用 Task 主链 |
| tenant/workspace/project scope | user/session 为主的现有 context | 能力不足 | 引入 typed `ExecutionScope`，非兼容迁移 Gateway、ResourceRef、Credential 和 Store |
| semantic outcome verification | structured model、局部 verifier contracts | 需领域化 | 新增 Project SubGoal/FinalReport assessment 与 deterministic Completion Gate |
| budget recovery | Interaction usage、worker facts | 缺失 | Project event journal 拥有 reservation/usage facts，projection 重建 ledger |

禁止把以下内容当作能力已存在的证据：

- 类名、Protocol、DTO、配置项或未接入 Composition Root 的实现；
- 只验证 schema 的 Fake；
- GitHub、Notion、A2A 各自通过但从未在同一正式旅程组合；
- Agent `completed`、Tool `ok`、Artifact 存在或数据库新增记录；
- 未来 Stage 名称或“复用现有 Gateway”的文字声明。

### 3.2 缺失能力的准入规则

每个缺失能力必须同时具有：

1. canonical owner 和唯一写入口；
2. Project 实际消费的 typed Port/contract；
3. Composition Root 的生产装配；
4. 明确失败语义，不存在相似能力 fallback；
5. Unit/contract/integration test；
6. 至少一个正式入口 E2E 的正向和反事实断言。

外部 Provider Fake 只能冻结不可控边界，必须实现与生产 Adapter 相同 Port 并通过 contract
test。Fake 不得创造生产中没有的 Tool、Agent profile、审批路径、Artifact store 或
Completion 决策。

## 4. Expected User-visible Result

用户从正式 API 创建项目后能够观察：

- 项目目标、scope、当前状态、预算、usage 和最近更新时间；
- accepted SubGoal、依赖、执行类型、进行中/等待/完成/失败状态；
- 等待用户输入、审批、能力或外部环境的原因；
- Artifact、admitted evidence、specialist Outcome 和 requirement mapping；
- steering 被接受或拒绝的原因，以及被 supersede 的未冻结工作；
- cancel receipt、late result disposition；
- 最终报告、证据清单、未满足项和 limitation。

反事实必须成立：

- 不因 Tool 或 child success 提前完成父项目；
- 不因重启、重复回调或重复提交产生第二次副作用/child run；
- 不让 steering 覆盖已审批 Command、Receipt、Outcome 或 Artifact；
- 不跨 tenant/workspace 使用 Artifact、Credential、Agent、检索结果或 checkpoint；
- 缺少 report、verification、coverage 或 required receipt 时不返回 completed。

## 5. Out of Scope

第一版不做：

- 将普通 Conversation、Research workflow 或所有后台 job 迁入 Project；
- 恢复旧 `TaskAnalyzer -> GoalGraph -> AdaptivePlanner -> Executive` 主链；
- 任意 DAG 编辑器、BPMN、Agent marketplace、自治角色协商或 Agent 自复制；
- 任意数据外发能力；只支持本设计定义的 external Agent delegation；
- 用字符串包含、相似度、模型自述或步骤数量证明完成；
- 通用 callback bus、Saga framework 或通用 durable-task framework；
- 自动安装、申请或替换缺失 capability。

## 6. E2E First

实现代码前先登记并创建测试；可以先失败，但不得 skip：

```powershell
# 开发期目标用例
uv run pytest -q evals/e2e_quality/test_durable_investigation_project.py --e2e-scope=release
uv run pytest -q evals/e2e_quality/test_durable_investigation_recovery.py --e2e-scope=release

# 发布矩阵
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
uv run pytest -q evals/e2e_quality --e2e-scope=release --e2e-require-complete-matrix -s
```

每个 LT 节点必须进入 `evidence_catalog.py`；release gate 的 required product evidence set 同步
加入 LT01–LT13。未登记节点、skip、dirty/mismatched revision 或缺 trace checksum 均不能产生
发布声明。

Release E2E 从正式 HTTP 入口进入独立 Web/worker 进程，使用真实 PostgreSQL、真实领域模型、
真实 structured model；LT01 必须使用 Composition Root 实际装配的 GitHub、Notion 和 A2A
profile。仅故障注入、危险外发、并发时序和 paired deterministic eval 可使用通过 contract
test 的冻结 Adapter；相应真实 Provider profile 必须另有同 revision release evidence，两侧
baseline 必须使用相同外部边界。Fake 不得替 Planner、Policy、Verifier、Artifact owner 或
Completion Gate 决策。

### LT01：完整架构调查

```text
Given: tenant A 的 workspace 已连接 GitHub、Notion 和 registered external Agent；用户明确提出架构、安全、成本、迁移四项 UserRequirement
When: POST /api/investigation-projects，并通过正式查询入口等待终态
Then: 最终 generated Artifact 引用四类 admitted evidence，四项 requirement 均映射 verified Outcome
And not: 任一 execution success 不能单独完成项目；不得引用 tenant B 或未 admitted 内容
Path: HTTP -> Project use case -> Planner -> execution proposal -> capability admission -> scheduler -> Gateway -> evidence admission -> Verifier -> Completion Gate
Required capabilities: combined MCP/A2A inventory、typed execution proposal、generated Artifact、Project verifier
Allowed fakes: 无；GitHub、Notion、A2A 使用实际 production profile
Evidence: capability revision、plan/execution revisions、execution/artifact refs、admission、verification、completion report
```

### LT02：Command dispatch 崩溃与恢复

```text
Given: external delegation Command 已审批、冻结并写入 outbox
When: worker 在 provider accept 后、receipt commit 前终止并重启
Then: 使用同一 ExecutionCommandDigest reconcile，最终只产生一次外发
And not: 不重新请求模型生成 payload，不创建 superseding Command，不重复 provider submission
Path: project lease -> Command/outbox journal -> AgentGateway submission binding -> reconcile -> project scheduler
Required capabilities: immutable external delegation Command、durable submission、provider reconcile
Allowed fakes: 可按 digest/submission key 查询结果的故障注入 A2A Adapter
Evidence: command/grant digest、outbox、provider task id、receipt、project event sequence
```

### LT03：用户 Steering

```text
Given: 架构和安全已完成，成本 child 正在运行，迁移尚未开始
When: 用户要求停止成本分析并比较两种迁移顺序
Then: 保存 immutable SteeringCommand；Replanner 只修订未冻结范围；用户明确 waive 成本 UserRequirement，并新增迁移顺序要求
And not: Planner 不自行删除/弱化 UserRequirement；不改写 completed Outcome/Receipt；late result 不进入新计划
Path: HTTP -> steering use case -> project event -> Replanner -> plan admission -> scheduler
Required capabilities: versioned steering、frozen boundary、cancel/late disposition
Allowed fakes: 可控制 cancel/late 时序的 A2A Adapter
Evidence: steering digest、old/new plan、frozen refs、cancel receipt、late disposition
```

### LT04：并行 child run 与依赖 Join

```text
Given: 两个互不依赖的 bounded specialist subgoal 和一个依赖二者的 synthesis subgoal
When: 项目开始执行
Then: 两个 child run 在预算内并行；两者 verified Outcome committed 后 synthesis 才 ready
And not: 任一 child 失败/未验证时不得 dispatch synthesis
Path: accepted plan -> ready calculation -> AgentGateway -> evidence admission -> outcome join -> synthesis
Required capabilities: durable AgentGateway、bounded parallel dispatch、deterministic join
Allowed fakes: 具有可控完成顺序的同 Port A2A Adapter
Evidence: dependency ids、dispatch batch、child refs、outcome sequence、join decision
```

第一版的“specialist”是每个 `AgentTask` 的 bounded role，不要求创建新 Agent 类。两个 child
可以绑定同一 registered profile，也可以绑定不同 profile；只有 capability contract、scope 和
预算满足时才允许绑定。测试不得临时注册生产中不存在的 specialist profile。

### LT05：外部委托审批

```text
Given: accepted AgentExecutionProposal 要把两个 private ArtifactRef 的受限摘录发送给 external Agent
When: Policy 要求审批，用户从 Project approval API 批准后执行
Then: 对应 SubGoal 显示 approval_required；若其他分支 ready，Project 保持 active；Confirmation 绑定 AuthorizationDigest；执行绑定同一 CommandDigest
And not: Planner/Admission/Command materializer 不补 Artifact、目标或 disclosure payload；参数变化产生 superseding Command
Path: execution proposal -> policy -> immutable ExternalDelegationCommand -> approval -> disclosure materialization -> AgentGateway -> receipt
Required capabilities: Project approval use case、disclosure manifest、immutable Command、durable AgentGateway
Allowed fakes: 记录 digest、payload digest 和副作用次数的 A2A Adapter
Evidence: proposal、policy decision、authorization/command digest、confirmation、grant、receipt
```

### LT06：预算耗尽与部分结果

```text
Given: 项目预算不足以完成全部 requirement
When: reservation 使 remaining budget 到达硬限制
Then: 停止超预算派发；若所有剩余 required work 都被预算阻塞则 Project 进入 paused，并返回已有 Artifact 和 unmet requirements
And not: 不生成伪完整报告、不把部分覆盖标记 completed、不静默扩大预算
Path: scheduler -> budget reservation -> usage commit/release -> project transition -> partial report
Required capabilities: durable budget facts、并发 reservation、coverage report
Allowed fakes: 仅外部 Provider
Evidence: reservation/usage events、budget decision、coverage report、project state
```

### LT07：取消与 Late Result

```text
Given: 项目有两个 running child，其中一个 Provider 不支持立即取消
When: 用户取消项目，随后 Provider 返回 completed
Then: Project 为 cancelled；可取消 child 收到 cancel；late Artifact 作为隔离审计事实保存
And not: late result 不推进 plan、不触发新步骤、不反转 cancelled
Path: cancel use case -> project event -> AgentGateway cancel -> callback/poll admission -> late disposition
Required capabilities: durable child state、cancel receipt、terminal callback admission
Allowed fakes: 延迟完成 A2A Adapter
Evidence: cancel command/event、child receipt、late callback、quarantined Artifact ref
```

### LT08：Scope 隔离

```text
Given: tenant A/B 存在同名 workspace、仓库、文档和 Artifact
When: tenant A 创建、执行并恢复项目
Then: retrieval、Tool、Agent、Credential、Artifact、journal 和 checkpoint 均校验 typed scope
And not: plan、trace、报告、provider payload 和恢复状态中均无 tenant B 引用
Path: auth principal -> SecurityScope + ExecutionScope -> context visibility -> Gateway contexts -> scoped stores
Required capabilities: typed principal/security/execution scope、owner-scoped ResourceRef、credential binding、storage predicates
Allowed fakes: 外部 Adapter 必须断言收到的 scope/grant
Evidence: scoped ids、visibility/policy decisions、provider request digest、trace redaction
```

### LT09：最简单 Baseline 对照

```text
Given: 与 LT01 相同输入、capability revision、模型、数据、外部 fixtures 和预算上限
When: 分别运行 Conversation ReAct baseline 与 Investigation Project，并在中途终止进程
Then: Project 恢复后 requirement coverage=4/4、duplicate side effects=0；baseline 无法恢复同一 deliverable contract
And not: 不以 plan/subgoal/trace 数量或对象存在证明收益
Path: 两个正式产品入口；同一 scorer 读取用户结果、coverage、receipts 和 usage
Required capabilities: paired run identity、相同输入 digest、可重复 crash point、result scorer
Allowed fakes: 两边完全相同的冻结外部边界
Evidence: paired ids、input/capability digest、coverage、evidence precision、duplicate count、latency、cost
```

发布硬门槛是恢复后的完整交付和零重复副作用；质量、成本和延迟同时报告。若简单 Workflow
或扩展 Conversation 能满足同一硬门槛，则停止 Project 主链实施。

### LT10：Child submit 崩溃与恢复

```text
Given: ready subgoal 已生成 accepted AgentExecutionProposal，但 child result 尚未 committed
When: worker 在 provider 返回 task id 后、AgentRun submission commit 前崩溃
Then: 按稳定 submission key 找回同一个 child run 并继续 poll
And not: 不创建第二个 provider task、不重新请求 Planner/Execution Proposer
Path: project event -> AgentGateway submit reservation -> provider -> submission reconcile -> child store
Required capabilities: durable AgentRun store、idempotent provider submit/reconcile
Allowed fakes: 支持按 submission key 查询的 A2A Adapter
Evidence: proposal digest、submission key、唯一 provider task id、AgentRun events
```

### LT11：Capability Missing

```text
Given: accepted plan 需要 notion.retrieve_page_markdown，但当前 capability snapshot 不含 Notion
When: scheduler 尝试 materialize ready subgoal
Then: 保存 typed CapabilityMissing；其他 ready 分支继续；若 required work 全局阻塞则 Project 进入 paused 并显示缺失 contract
And not: 不改用 GitHub/web/Agent、不让 Fake 注册 Notion、不生成替代业务内容
Path: capability snapshot -> execution proposal admission -> project transition -> limitation view
Required capabilities: capability inventory、typed missing feedback、fail-closed transition
Allowed fakes: 无；缺失事实来自真实 production assembly
Evidence: capability revision、rejected proposal、feedback、zero dispatch audit
```

### LT12：Observation 驱动的动态 Plan 必要性

```text
Given: 用户要求分析架构和迁移风险；运行前未知系统是单体还是事件驱动微服务；固定 Workflow baseline 只能预写通用分支
When: 首个仓库调查 Outcome 证明系统为事件驱动微服务，并暴露跨服务事务风险
Then: Replanner 新增消息一致性与补偿事务 SubGoal，supersede 尚未执行的单体迁移分析，ready set 和后续 ToolCall 随 revision 改变
And not: 不重新执行已完成仓库扫描；不修改其 Outcome；不预写覆盖所有架构类型的固定分支
Path: admitted Observation -> ReplanRequest -> Replanner -> Plan Admission -> new ready set -> different execution proposals
Required capabilities: typed plan assumptions、bounded ReplanRequest、logical SubGoal identity、fixed Workflow paired baseline
Allowed fakes: 两侧使用相同冻结仓库/Tool Adapter；模型、Replanner、Admission 和 scheduler 真实
Evidence: old/new plan digest、assumption conflict、superseded/reused SubGoal refs、不同 dispatch、coverage/无效调用对照
```

LT12 的发布门槛不是“产生了新 Plan”，而是动态 revision 相对固定 Durable Workflow 提高
required coverage 或减少无效执行，并保持 frozen Outcome 和零重复副作用。

### LT13：异步创建与最小 Project 恢复

```text
Given: 一个只使用 read-only Tool + synthesis 的 Investigation Project
When: POST 创建后 Planner 尚未返回，随后 planning/执行 worker 分别发生一次进程终止
Then: 创建立即返回同一个 project_id 和 planning 状态；重启后从 definition、UserRequirement、journal 和 accepted proposal 继续直至完成
And not: 不产生第二个 Project、不丢失用户要求、不重新执行 committed read、不依赖 external Agent/approval
Path: HTTP create -> definition transaction -> worker planning -> journal/checkpoint -> read-only ToolGateway -> Completion Gate
Required capabilities: idempotent async create、Project journal、accepted proposal replay、generated Artifact
Allowed fakes: 冻结 read-only 外部 Tool Adapter；模型、Project store、scheduler、Verifier 真实
Evidence: create idempotency key、project/event ids、planning failure/recovery、execution order、completion report
```

## 7. Decision Ownership

| 决策/事实 | Owner | 禁止事项 |
| --- | --- | --- |
| 用户目标、UserRequirement、waiver | 用户或外部权威 | Planner 不删除、弱化或改写 |
| DerivedRequirement、动态 SubGoal、依赖、semantic revision | Planner/Replanner | Policy 不生成或重排 Plan |
| SubGoal 所需能力契约 | Planner/Replanner | 不绑定具体 Tool、Provider 或 Agent profile |
| 具体 Tool/Agent/synthesis payload | Execution Proposer | Scheduler、Admission、Adapter 不补 payload |
| Proposal 类型、引用、DAG、revision 合法性 | Plan/Execution Admission | 不修复 objective、arguments 或依赖 |
| 具体 Tool/Agent/operation 选择 | Execution Proposer | 不修改 Plan 的能力契约 |
| 等价 Adapter/Provider 绑定 | Capability Resolver | 仅完整 equivalence class 可确定性绑定 |
| ready/join、预算、lease、合法迁移 | Project Runtime | 模型不声明执行状态 |
| 权限、风险、审批和 disclosure | Policy/Project Command use case | Prompt 不代替授权 |
| Tool/Agent/Command 实际结果 | 对应 Gateway/Executor | Project 不伪造 Receipt |
| Evidence 是否可进入验证 | Evidence Admission | Provider success 不等于 admitted |
| Outcome 是否满足 SubGoal | Project Semantic Verifier | Tool success 不等于 verified |
| required deliverable 是否齐全 | Completion Gate | Verifier 不推翻 execution fact |
| steering 内容 | 用户或外部权威 | Runtime 不将文本静默改写成 Plan |

结构化 Proposal 不合法时返回 `DecisionFeedback`，包含原因、repairable/immutable fields、
required repair、revision scope 和 disposition。只允许同 digest transport retry；禁止代码补
业务字段或无反馈重复 Prompt。

## 8. Fact Ownership and Write Path

### 8.1 Canonical Facts

| Fact | Canonical owner | 唯一写入口 | 失效/重建 |
| --- | --- | --- | --- |
| `InvestigationProjectDefinition` | Project aggregate | `CreateInvestigationProject` definition transaction | immutable |
| `UserRequirementVersion` | Project definition | create/explicit user steering or waiver | immutable；Planner 不可 supersede |
| `DerivedRequirementVersion` | Accepted plan | `AcceptPlanProposal` | Replanner 可 supersede；历史不覆盖 |
| `AcceptedPlanVersion` | Project aggregate | `AcceptPlanProposal` | immutable；可 supersede |
| `SubGoalDefinitionVersion` | Accepted plan | 与 plan 原子写入 | logical id 稳定；definition 变化创建新 version |
| `AcceptedExecutionProposal` | Project aggregate | `AcceptSubGoalExecutionProposal` | 绑定 plan/subgoal/event sequence |
| `ProjectEvent` | Project journal | Project transaction | append-only |
| `ProjectBudgetReservation/UsageCharge` | Project journal | scheduler reservation / usage receipt admission | projection 重建 |
| `ExecutionRef` | Tool/Command/Agent owner | Gateway/Executor | Project 只引用 |
| `AgentRunRecord` | AgentGateway | AgentGateway submit/poll/callback | durable events 重建 |
| `ArtifactRef` | Artifact service | Artifact write use case | body 不复制到 Project |
| `DisclosureManifest` | Context visibility use case | accepted external delegation preparation | immutable；绑定 Artifact revision/span/digest |
| `EvidenceAdmissionDecision` | Evidence Admission | admission use case | 绑定 evidence/artifact digest |
| `SubGoalOutcome` | Project aggregate | accepted verification transaction | immutable；纠正为新 assessment |
| `SteeringCommand` | Project aggregate | authenticated steering use case | digest 去重 |
| `ExternalDelegationCommand` | Project command aggregate | accepted execution proposal + Policy | immutable；参数变化 supersede |
| `VerificationAssessment` | Project Verifier | verify use case | versioned、digest-bound |
| `CompletionReport` | Completion Gate | completion transaction | coverage 齐全才 complete |

`ProjectProjection` 从 definition、requirements、plans、execution proposals 和 events 重建，
不是第二写入口。
Checkpoint 只加速投影；丢失时从 journal 重建。大型文本和报告只保存 ArtifactRef。

### 8.2 Project Lifecycle

```text
planning -> active
planning -> paused | failed | cancelled
active -> paused | cancelling | completing | failed
paused -> active | cancelling | failed
cancelling -> cancelled
completing -> completed | active | failed
```

Project 主状态不承载每个分支的等待原因。Projection 从 SubGoal/Command/Provider facts 派生：

```text
WaitingReason
  subgoal_ref
  reason: approval_required | user_input_required | capability_missing
        | provider_unavailable | budget_exhausted | dependency_pending
        | outcome_unknown | verification_repair
  recovery_authority: runtime | planner | user | provider
  blocking_required_work: bool

is_globally_blocked =
  no ready/running work
  and active required work remains
  and every remaining item has a waiting reason
```

一个分支等待审批时，只要还有 ready/running work，Project 保持 `active`。全局阻塞时根据 typed
`FailureDisposition` 确定性处理：

- transient/retryable：保持 active，并保存下一次 retry fact；
- user/provider recoverable：进入 paused；
- replan recoverable：创建有界 `ReplanRequest`，预算耗尽则 paused；
- terminal：只有 required goal 已不可实现时进入 failed。

禁止写 `paused/failed` 这种模糊结果。`completed`、`failed`、`cancelled` 为终态；终态 callback
只形成 AgentGateway event、ArtifactRef 和 late disposition，不改变 Project state。

## 9. Core Contracts

### 9.1 Typed Scope

入口必须解析：

```text
AuthenticatedPrincipal
  tenant_id
  user_id

SecurityScope
  tenant_id
  workspace_id

ExecutionScope
  security_scope
  principal_id
  project_id
  plan_version
  subgoal_version
  execution_id

ResourceRef
  resource_id
  revision
  owner_scope: SecurityScope
```

API key 配置从 `key -> user_id` 非兼容迁移为 `key -> principal`；单租户部署也必须显式配置
tenant/workspace。`SecurityScope` 决定资源所有权与 ACL；`ExecutionScope` 只记录本次使用属于
哪个 Project/Plan/SubGoal/Execution，不能成为 Artifact 的 owner scope。同一 workspace
Artifact 可以被多个 Project 引用而不复制。

ToolGatewayContext、AgentGatewayContext 和 trace 使用 `ExecutionScope`；ResourceRef、Artifact
store、Credential resolver 和 visibility 使用 `SecurityScope` 加 principal authorization。
禁止空值、隐式 default、把 project_id 写成资源 owner，或只在 Prompt 中传 scope。

### 9.2 Plan Proposal

```text
PlanProposal
  project_id
  based_on_event_sequence
  capability_snapshot_revision
  revision_reason
  assumptions[]
    assumption_id
    statement
    affected_logical_subgoal_ids[]
  derived_requirements[]
    requirement_id
    statement
    acceptance_contract
    completion_relevance: required | supporting
  subgoals[]
    logical_subgoal_id
    subgoal_version
    definition_digest
    supersedes_version?
    objective
    depends_on[]
    required_output
    capability_contract
  requirement_mappings[]
```

`UserRequirementVersion` 在创建 transaction 中由用户输入固化，Planner 只能引用。Planner
可以增加 `DerivedRequirementVersion`，但不能删除、合并、弱化或 waive UserRequirement。
只有 authenticated user steering/waiver 能产生新的 UserRequirementVersion。

Planner 只表达“需要什么能力”的 versioned `capability_contract`，不绑定 Tool ID、Provider、
Agent profile 或 operation kind。Plan Admission 只验证 scope、UserRequirement 保持、引用、
ID、DAG、frozen boundary、capability contract 存在、数量/预算和 digest，不补步骤、output、
Provider 或依赖。

### 9.3 Plan Revision and SubGoal Identity

Replanner 通过 logical identity 复用工作：

- 定义未改变：复用 `logical_subgoal_id + subgoal_version + definition_digest`；
- objective、required_output 或 capability contract 改变：同 logical id 创建新 version，并
  `supersedes` 旧 version；
- completed 且仍有效：新 Plan 引用已有 verified Outcome，不重新 dispatch；
- completed 但不再需要：Outcome 保留为历史事实，不计入 active coverage；
- 未开始且与新 Observation 冲突：新 version supersede；
- running/approved/frozen：不得被 revision 覆盖，只能按执行契约等待、取消或 reconcile。

Plan Admission 拒绝把同一 definition 换新 ID、把不同 definition 复用旧 digest，或让
requirement mapping 指向 inactive version。

### 9.4 SubGoal Execution Proposal

ready 只表示允许请求执行 Proposal，不表示可直接 dispatch：

```text
SubGoalExecutionProposal
  project_id
  plan_version
  subgoal_id
  based_on_event_sequence
  proposal_id
  operation:
    ToolExecutionProposal
      tool_name
      typed_arguments
      expected_artifact_type
    AgentExecutionProposal
      agent_id
      bounded_sub_goal
      context_artifact_refs[]
      expected_artifact_types[]
      token/cost/time budget
    SynthesisProposal
      input_artifact_refs[]
      requirement_refs[]
      output_contract
    UserInputProposal
      question
      required_fields[]
```

第一版复用当前 Tool/Agent typed contract 的业务字段，但增加 Project/revision/scope binding。
Execution Proposer 是 structured model 调用；它只能看到当前 `EffectiveCapabilities` 和 admitted
context。Admission 验证 tool/agent 存在、schema、scope、budget、revision 和重复 action，不
修补 arguments、AgentTask 或 context refs。

accepted Tool proposal 进入 ToolGateway。accepted Agent proposal 先经过 data-egress Policy：
无需审批时创建 DelegationGrant；需要审批时确定性复制 Proposal 字段形成 immutable
`ExternalDelegationCommand`。Scheduler 不能根据 SubGoal objective 猜 payload。

### 9.5 Capability Binding

accepted Plan 绑定 `capability_snapshot_revision`，dispatch 前读取最新 inventory：

- Execution Proposer 根据 capability contract 选择当前具体 operation、Tool 或 Agent；
- exact tool/agent id 存在且 contract 满足：继续 Admission；
- 多个 Provider 完整属于同一 `CapabilityEquivalenceClass`：Resolver 可确定性绑定；
- 存在语义差异：返回 feedback，由 Execution Proposer 或用户选择；
- capability 缺失、denied 或 unhealthy：typed failure，pause/fail closed；
- 禁止选择“最像”能力或换 Provider 冒充用户指定结果。

## 10. Missing-capability Production Delivery

### 10.1 Durable AgentGateway

保留 AgentGateway 对 child lifecycle 的所有权，新增：

```text
AgentRunStorePort
  reserve_submission(submission_key, definition_digest)
  commit_submission(agent_run_id, provider_task_id)
  append_event(expected_revision, event)
  put_artifact_ref(...)
  get/list_by_parent_scope(...)

AgentAdapter
  submit(..., submission_key)
  lookup_submission(submission_key)
  poll(provider_task_id)
  cancel(provider_task_id)
```

`PostgresAgentRunStore` 保存 immutable definition、submission binding、events、projection
checkpoint 和 ArtifactRef。Provider 返回的 Artifact 正文必须先通过 `ArtifactWritePort`
写入 Artifact owner，AgentRun 只保存 ref。`submission_key` 由
`project_id + plan_version + subgoal_id + accepted_execution_proposal_digest` 确定性生成。

迁移现有 Conversation A2A 调用方使用同一 durable store；不保留第二个 in-memory 生产路径。
不支持 lookup 的 Provider 在 submit 结果未知时返回 `OutcomeUnknown` 并暂停，禁止盲目重提。
若 Provider 提供 callback，callback 只进入 AgentGateway admission；Project 通过 child ref
消费 committed event，不直接信任 HTTP callback。

### 10.2 Governed External Delegation

第一版唯一新增 governed action 是“向 registered external Agent 发送 Project Artifact 的
受限 materialization”。Command 包含：

```text
InvestigationExternalDelegationCommand
  command_id
  SecurityScope
  ExecutionScope
  plan_version / subgoal_id / execution_proposal_digest
  target_agent_id
  bounded_sub_goal
  context_artifact_refs[]
  disclosure_manifest_ref
  token/cost/time budget
  authorization_digest
  execution_command_digest
```

`DisclosureManifest` 由 Context Visibility use case 产生，记录允许外发的 Artifact revision、
section/span、redaction policy 和 content digest；它不复制正文。Command materializer 只能
复制 accepted proposal 和 policy decision，不能增加 Artifact 或改写任务。

新增正式入口：

```text
POST /api/investigation-projects/{project_id}/commands/{command_id}/decision
```

Confirmation 绑定 AuthorizationDigest；Grant、outbox、AgentGateway submission 和 Receipt
绑定 ExecutionCommandDigest。参数改变必须创建 superseding command 并重新审批。

### 10.3 Generated Artifact Write

扩展现有 Artifact owner，而不是创建 Project 内正文副本：

```text
ArtifactWritePort.write_generated(
  security_scope,
  execution_scope,
  producer_key,
  producer_ref,
  kind,
  content,
  content_digest,
  source_artifact_refs,
  evidence_refs
) -> ArtifactRef
```

`producer_key` 必须由
`project_id + plan_version + logical_subgoal_id|final_report + producer_operation_digest`
确定性生成。同一 producer key 与 content digest 重试时返回原 ArtifactRef；同一 key
出现不同 digest 时拒绝为 `InvariantViolation`，内容变化必须由新的 plan/subgoal version
或显式 superseding producer operation 产生。

Artifact store 校验 SecurityScope、producer key、digest 和 immutable revision；Project
transaction 只提交返回的 ref。partial report、final report、synthesis 和 late Artifact
使用明确 kind/disposition。写失败时 Completion fail closed，不把模型文本直接塞进
Projection。

### 10.4 Budget Ledger

预算事实作为 Project events。ProjectDefinition 至少给出总预算和以下适用类别的上限：

- `planning`：初始 Planner 与 Replanner；
- `execution_proposal`：SubGoal 内的模型决策；
- `semantic_verification`：SubGoal 与 final report Verifier；
- `synthesis`：中间与最终报告生成；
- `external_delegation`：child Agent/外部模型能力。

每次模型或 Gateway 调用必须先归属且只归属一个类别；分类额度不能绕过总额度。记账流程：

- dispatch 前按 category CAS 写 `BudgetReserved`；
- Gateway/Model 返回 usage receipt 后按同一 category 写 `ProjectUsageCharged`；
- 未执行或取消写 `BudgetReleased`；
- outcome unknown 保留 reservation，reconcile 后 charge/release；
- projection 分类别并汇总 token、cost、tool/agent calls、并发和 wall time。

并行 dispatch 先原子预留所有 batch budget，避免每个 worker 单独判断导致超支。Usage
provider metadata 缺失时按 policy 上界记账并标记 estimated，不静默记零。原始 provider
usage receipt 仍由 Model/Gateway owner 保存，Project 只保存引用和按 Project policy 计算的
charge，禁止复制原始 usage fact。

### 10.5 Evidence Admission and Verification

Tool/Agent output 先写其 owner，再经过 Evidence Admission：

- scope、source、provider、artifact digest、execution ref 必须存在且一致；
- late/quarantined、denied、跨 scope 或 unverifiable 内容不能进入 active evidence set；
- Admission 只判断机械可信边界，不判断结论是否正确；
- Project Verifier 使用 admitted evidence 产生 typed `SubGoalVerificationAssessment`；
- FinalReport Verifier 检查报告 claim、citation、limitation 与 requirement mapping；
- Planner/Verifier schema、Prompt 和边界行为进入 Golden Set。

### 10.6 Plan Quality Golden Set

Plan 质量不能由“生成了 DAG”或“Admission 通过”证明。改变 Planner、Replanner、能力目录或
Requirement schema 前，必须先冻结真实输入、UserRequirement、capability snapshot 和 baseline
结果，并评估：

- UserRequirement 语义覆盖，且未被 DerivedRequirement 静默替换、弱化或删除；
- 依赖正确性、可执行性、必要步骤最小性和安全并行关系；
- capability contract 与当前 inventory 相符；
- 新 Observation 出现后能局部修订错误假设，并保留仍有效的 frozen work；
- 修订不会重跑无关已完成工作，也不会为了分数增加无生产消费者的步骤；
- 最终 requirement coverage、错误副作用、模型轮次、token、成本、延迟和恢复结果。

确定性 Admission 只检查引用、DAG、不变量、scope、schema、frozen boundary 和 capability
grounding；覆盖是否语义充分由模型 Verifier/离线 scorer 判断。Golden Set 分数只用于发布
评估，不成为生产分支规则。LT12 必须证明动态 Plan 改变了用户结果；LT09 只证明 durable
lifecycle 相对 Conversation 的恢复价值，二者不得互相替代。

## 11. Execution Loop

```text
POST Create Project + idempotency key
  -> persist ProjectDefinition + UserRequirementVersion atomically
  -> return 202 + project_id + state=planning
  -> enqueue planning work
  -> worker snapshots scoped EffectiveCapabilities
  -> Planner proposes DerivedRequirements/subgoals/dependencies
  -> Plan Admission accepts or returns DecisionFeedback
  -> persist AcceptedPlanVersion + ProjectEvent atomically
  -> scheduler computes ready set and reserves budget
  -> Execution Proposer returns typed SubGoalExecutionProposal
  -> capability/schema/scope/policy admission
  -> optional immutable Command + approval
  -> ToolGateway / AgentGateway / synthesis use case
  -> commit execution ref + categorized ProjectUsageCharge
  -> Evidence Admission
  -> Project Semantic Verifier
  -> commit SubGoalOutcome
  -> admitted ReplanRequest may trigger Replanner for unfrozen work
  -> Completion Gate checks required coverage
  -> FinalReport Verifier
  -> ArtifactWritePort + CompletionReport transaction
```

HTTP 创建成功不依赖 Planner、模型或 worker 当场可用；进程在创建返回后崩溃时，恢复器必须
只认已经持久化的 ProjectDefinition、UserRequirementVersion 和 planning work key，不得创建
第二个 Project 或丢失原始用户要求。

Workflow 保护稳定事务骨架；Plan 表达动态 SubGoal/依赖；bounded ReAct 只允许在某个 SubGoal
内产生 execution proposal，不接管 Project lifecycle。若删除 Plan 后 ready、dispatch、
progress、coverage 不变，必须删除 Plan。

## 12. Recovery, Idempotency and Concurrency

Project 恢复依赖 definition、accepted plans、accepted execution proposals、events、
execution refs、budget events 和 ArtifactRefs；checkpoint 不是事实 owner。

Replay 规则：

1. accepted Plan/Execution Proposal 不重新请求模型；
2. frozen Command 使用原 digest/outbox reconcile；
3. committed Observation/Outcome/ProjectUsageCharge 不重复执行；
4. unknown Tool/Agent invocation 走对应 Gateway reconcile；
5. 只有 accepted `ReplanRequest` 才允许新 revision；
6. Project 与 AgentRun 各自拥有 journal，通过 ref/digest 关联，不双写状态。

`ReplanRequest` 是 typed fact，包含 trigger kind/ref、affected requirement/subgoal、允许修订的
scope、feedback/observation digest 和 request digest。只允许以下触发：

- 用户提交新的 Steering 或明确 waiver；
- admitted Observation 反驳 accepted Plan 中显式记录的 assumption；
- capability snapshot 变化使未冻结工作不可执行；
- Verifier 返回可修复的 coverage/evidence gap；
- 没有 ready SubGoal、coverage 未完成且不存在合法等待原因；
- Admission 返回要求 Planner 修改的 typed DecisionFeedback。

普通成功、无结构影响的补充证据、重复 callback、相同 feedback digest、Provider 瞬时重试，
均不得触发 Replanner。每个 Project 必须配置 `max_plan_revisions` 和
`same_feedback_revision_limit`；新 Proposal 与当前 accepted plan digest 相同则 no-op，不产生
PlanVersion。Admission 必须证明 changed set 非空、未覆盖 frozen work 且修订未超出 request
scope；禁止用字符串相似度判定“变化足够大”。

同一 Project 同时只有一个 scheduler lease owner。claim 携带
`SecurityScope + project_id + lease_epoch + event_sequence`，提交时 CAS。过期 worker 可将外部结果写入
Gateway owner，但不能直接推进 Project。

并行只发生在 accepted Plan 中无依赖、Policy 允许且预算已预留的 ready SubGoal。join 的
“所有依赖 Outcome committed”由代码判断；Outcome 是否足以支持 synthesis 由 Verifier 判断。

## 13. Steering, Cancellation and Multi-Agent Boundary

`SteeringCommand` 包含 SecurityScope、project_id、expected plan revision、文本或 typed constraint、
idempotency key 和 timestamp。Application 先保存 command/event，再交给 Replanner。

冻结边界：

- completed Outcome、committed Receipt、approved Command、Artifact revision 不可覆盖；
- running read-only action 可等待或显式取消；
- running governed action 只能按 Command/Provider contract cancel、compensate 或 reconcile；
- not-started SubGoal 可 supersede；
- late result 由 AgentGateway 保存，Project 默认 quarantine，只有新 active proposal 明确引用且
  重新通过 Evidence Admission 才可形成 Outcome。

AgentGateway 拥有 child definition、event、projection 和 Artifact index；Project 只保存
child ref。父项目传递 scope、bounded goal、admitted context、预算和 Artifact contract，
并独立完成 Evidence Admission、semantic verification 和 requirement mapping。

## 14. Verification and Completion

```text
Execution Fact
  Tool/Command/Child 实际发生什么

Evidence Admission
  哪些 execution output 可进入当前 Project 的验证上下文

Semantic Verification
  Outcome/Artifact 是否满足 SubGoal 和 required_output

Completion Decision
  所有 active required UserRequirement/DerivedRequirement 是否映射到有效 assessment/Artifact/Receipt
```

Completion Gate 只做确定性完备性检查：required coverage 全部存在、assessment digest 有效、
必要 Receipt/Artifact 可读、没有 unresolved blocking failure、final report verification
passed。Gate 不用关键词拼报告，不补内容。部分报告必须显式标记 limitation；Project 是否
继续 active、转 paused 或 failed 由 lifecycle 与 typed FailureDisposition 决定。

## 15. Interface and Observability

| 操作 | HTTP | 语义 |
| --- | --- | --- |
| 创建 | `POST /api/investigation-projects` | 持久化 definition/UserRequirement 后返回 `202 + project_id + planning` |
| 查询 | `GET /api/investigation-projects/{id}` | scoped projection、Artifact refs、逐 SubGoal waiting reasons |
| steering | `POST .../{id}/steering` | 保存 SteeringCommand |
| 审批 | `POST .../{id}/commands/{command_id}/decision` | 绑定 Authorization/Command digest |
| 暂停/继续 | `POST .../{id}/pause`、`resume` | 合法状态迁移 |
| 取消 | `POST .../{id}/cancel` | cancel event + child orchestration |

CLI/UI 调用相同 Application use case。Trace 至少记录 scope、project/event sequence、plan 和
execution proposal revision、admission、subgoal/dependency、dispatch batch、provider、
lease、usage、command/authorization digest、receipt、artifact、evidence admission、
verification、completion 和 error taxonomy；敏感正文与 credential 不进入 trace。

错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、
Execution Failure、Transient Failure、Outcome Unknown、Verification Failure、Completion
Failure、Invariant Violation、Cancelled 和 Late Result。

## 16. Affected Modules and Dependency Direction

目标边界；路径不代表当前存在：

```text
Interface
  adapters/web/auth.py                         principal scope migration
  adapters/web/routes/investigation_projects.py
    -> Application
       application/investigation_project/
         create/query/steer/approve/cancel/schedule/verify/complete
       -> Domain
          domain/investigation_project/
       -> Ports
          model, project store, artifact, tool, agent, capability, policy, clock
    <- Infrastructure
       infra/storage/postgres_investigation_project.py
       infra/storage/postgres_agent_run_store.py
    <- Existing owners extended
       ToolGateway, AgentGateway, ArtifactService, CapabilityResolver, model adapter
```

跨模块非兼容变更：

- `AgentGatewayContext`、`ToolGatewayContext` 使用 canonical `ExecutionScope`；
- `ResourceRef` 增加 tenant scope，迁移全部调用方；
- AgentGateway store 改为 Port + PostgreSQL production Adapter；
- AgentArtifact 正文迁入 Artifact owner，AgentRun 只保存 ArtifactRef；
- ArtifactService 增加 generated write Port；
- API key identity 配置改为 typed principal；
- E2E catalog/release gate 增加 LT required evidence。

这些变更必须由 ADR 记录 baseline、迁移、回滚、净复杂度和删除日期。Domain 不依赖框架；
Application 只依赖 Port；worker 不补语义参数；Composition Root 不成为事实 owner。

## 17. Complexity Budget and Net Change

允许新增的复杂度只限 LT01–LT13 的生产消费者：

- 一个 `InvestigationProject` aggregate、journal/store 和 scheduler；
- Plan 与 SubGoal Execution 两级 typed Proposal/Admission；
- AgentGateway durable store/reconcile；
- 一个具体 external delegation Command/approval；
- typed scope 非兼容迁移、generated Artifact write、Project budget charge；
- Project Evidence Admission、Verifier 和 Completion Gate。

同步删除的复杂度：

- Conversation 强制 WorkingPlan 契约及其存在性测试；
- AgentGateway in-memory 生产 store、inline AgentArtifact 正文和请求内唯一 polling；
- raw scope 写入口和测试 capability registration hook；
- 任何由 Tool/Agent success 直接完成 Project 的临时分支。

不得增加第二套 ToolGateway、Artifact store、Capability Registry、模型 Adapter、通用 Task
framework 或 Project 内正文副本。若 Stage 5 不能证明恢复/完成收益，删除 Project 强制主链，
保留现有最简单 Conversation/Workflow，而不是继续增加 Planner 或 Agent。

## 18. Removed Legacy Path

实施时必须删除：

1. Conversation 强制 `WorkingPlanSnapshot` 输出/恢复规则及只证明其存在的 L01/L03 断言；
2. 任何 `WorkingPlanSnapshot -> AcceptedPlanVersion` converter、alias 或双写；
3. AgentGateway 的 in-memory 生产 run store 和同步请求内唯一 polling 路径；
4. raw `user_id/session_id` 代替 typed ExecutionScope 的 Gateway 写入口；
5. 让 Tool/Agent success 直接设置 Project completed 的临时分支；
6. 通过 Conversation Prompt 隐式创建同一 Project 的第二写入口；
7. 为测试注册不存在 Tool/Agent profile 或直接写 Project state 的 hook。

普通 Conversation 保持短 ReAct；只有显式创建 Project 才进入 durable lifecycle。

## 19. Non-compatible Delivery Order

### Stage 0：能力基线与失败 E2E

- 登记 LT01–LT13，创建测试文件和外部 Adapter contract tests；
- 记录每个 required capability 的代码 owner、Composition Root 装配和当前失败证据；
- 分别执行 Conversation durable baseline 与 fixed durable Workflow Plan baseline，冻结
  input、capability digest 与 scorer；
- Conversation 已满足 LT09 恢复目标则停止 Project durable lifecycle；fixed Workflow 已满足
  LT12 动态适应目标则停止引入强制 Plan；
- 为 scope、AgentGateway persistence、Project Aggregate、Command/Completion 创建 ADR。

### Stage 1：最小只读 Plan 纵切

- 非兼容迁移本阶段涉及的 typed principal、SecurityScope、ExecutionScope、Gateway context 和
  ResourceRef，并在同一变更迁移全部调用方；不建 compatibility adapter 或双写；
- 创建 async Project、UserRequirement/DerivedRequirement、Plan/Execution Proposal、
  Admission、journal/store、worker lease 和最小恢复；
- 仅接入现有 read-only Tool、synthesis、categorized budget、Evidence Admission、
  Verifier、Completion Gate 与幂等 generated Artifact write；
- Runtime 必须消费 Plan 计算 ready/progress/coverage，并支持 LT12 所需的 bounded replan；
- LT06、LT08、LT11、LT12、LT13 通过后删除 Conversation 强制 WorkingPlan 双轨。

### Stage 2：Steering 与 Plan revision 收敛

- 加入 Steering/waiver、logical subgoal identity、supersede、frozen boundary 和 revision limits；
- Golden Set 验证 UserRequirement 不被弱化、局部修订不重跑无关完成工作；
- LT03 通过；同 digest revision 和无结构影响 Observation 不得调用 Replanner。

### Stage 3：Governed Durable Agent

- 增加 durable AgentRun store、submission key、lookup/reconcile 和 callback admission；
- 把 AgentArtifact 正文迁入 Artifact owner，AgentRun 只保存 ArtifactRef；
- 加入 Command outbox/reconcile、pause/resume/cancel 和 late-result quarantine；
- 增加 disclosure manifest、external delegation Command 和 Project approval；
- LT02、LT05、LT07、LT10 通过。

### Stage 4：并行完整调查

- Project scheduler 接入 durable AgentGateway 和 bounded parallel child；
- 完成 child submit recovery、late Artifact、Evidence Admission 和 join verification；
- LT04 和完整 LT01 通过。

### Stage 5：发布证明与收敛

- LT09 paired baseline 达到硬门槛并记录质量、延迟、成本；
- 运行 unit/contract/integration、完整 release E2E、layer、lint/type；
- 删除旧 context/store、测试 hook、converter 和旧断言；不得以 feature flag 保留双主链；
- 更新 current-state、workflow、API、运维和 interview 文档；
- 删除本文，不追加“已落地”章节。

每个 Stage 只实现其 E2E 所需最小能力，不提前加入通用 Saga、Event Bus、DAG DSL、Agent
marketplace 或多级 Planner。

## 20. Risks

| 风险 | 约束/验证 |
| --- | --- |
| E2E 使用不存在的能力 | capability baseline、Composition Root 证据、LT11、禁止 Fake 注册能力 |
| Plan 无法产生实际调用 | typed Execution Proposal、Admission、LT01 execution refs |
| 仅因任务耗时长而误建 Project/Plan | 双条件入口矩阵、Conversation 与 fixed Workflow 两类 baseline |
| Planner 弱化用户原始要求 | UserRequirement/DerivedRequirement 分离、waiver 只归用户、LT03 |
| 分支等待阻塞整个 Project | Project lifecycle 与逐 SubGoal waiting reason 分离、LT05 |
| 重规划抖动或无限烧模型 | typed ReplanRequest、revision/digest limits、分类预算、LT12 |
| AgentGateway 重启后丢 run | PostgreSQL store、submission binding、LT10 |
| 外发审批只有 DTO 没有副作用链 | concrete external delegation Command、LT02/LT05 |
| Security ownership 与 execution association 混淆 | SecurityScope/ExecutionScope 分离、owner-scoped ResourceRef、LT08 |
| generated report 重试产生重复版本 | ArtifactWritePort 唯一 owner + producer key/digest、LT01/LT13 |
| 模型调用漏记或并发预算超支 | category + total atomic reservation、usage events、LT06 |
| child completed 提前完成父项目 | Evidence Admission、Verifier、Completion Gate、LT01/LT04 |
| Event/Projection 重复事实 | canonical table、projection rebuild test |
| durable 或动态 Plan 价值混为一谈 | LT09 单独证明恢复价值，LT12 单独证明动态修订价值 |
| 多 Agent 无质量收益 | LT09/LT12 对照；无收益则保留 Tool + 单 Agent 最简单路径 |
| 通用化过早 | Project 领域实现；第二业务前禁止抽取 |

## 21. Definition of Done

只有同时满足以下条件才完成：

1. LT01–LT13 从正式入口经过生产主路径通过，正向和关键反事实均自动断言；
2. 每个 required capability 有生产 owner、装配、contract test 和 Project 消费证据；
3. LT09 证明 durable lifecycle 的恢复收益，LT12 另行证明动态 Plan 相对 fixed Workflow 的用户
   结果收益；任一不成立则删除对应强制机制；
4. UserRequirement 只能由用户 Steering/waiver 改变，Planner 只拥有 DerivedRequirement；
5. Plan 与 Execution Proposal 被 Runtime 用于依赖、payload、调度、进度和 coverage；
6. create 在 Planner 前持久化并返回 project id；crash/replay 不重新生成 accepted
   Proposal/Command，不重复 Tool、child、Artifact 或外发；
7. replan 只有 typed trigger、bounded revision 和非空 changed set；同 digest 为 no-op；
8. 所有模型/Provider 调用按 category 与 total budget 预留和记账；
9. SecurityScope/ExecutionScope、Project lifecycle/waiting reason、failed/paused 语义明确分离；
10. steering、approval、cancel、late result、budget 和 tenant isolation 均有证据；
11. Execution、Evidence Admission、Verification、Completion 分离；
12. Project、AgentRun、Artifact、Command、Budget charge 各有唯一 owner/写入口；
13. WorkingPlan、in-memory Agent run production path、raw scope 和测试 capability hook 已删除；
14. unit、contract、integration、release E2E、layer、lint/type 实际执行并记录；
15. 当前事实迁入 canonical 文档，本文从 `docs/future` 删除。
