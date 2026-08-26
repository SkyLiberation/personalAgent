# Durable Investigation Project 当前状态

> 本文只记录 2026-08-26 的生产路径、事实归属和证据边界。历史失败与机制对照由[当前端到端用例盘点](../evals/02-current-case-inventory.md)拥有，尚未闭环的候选由[设计优化队列](../future/design-optimization-backlog.md)拥有。

## 1. 当前判断

Investigation Project 已具备独立持久化生命周期，但尚未证明当前 MiMo + GPT Researcher 路径能交付最终调查报告。正式 Conversation 请求可以创建 Project，worker 也可以恢复并推进 journal；当前权威产品样本仍为 `20/20 project_selected`、`0/20 delivered`。

因此，Project 生命周期可达和最终报告交付必须分开陈述。accepted Plan、ExecutionRef、Artifact 或调度事件的增加都不能替代用户结果。

## 2. 事实归属

| 事实 | 唯一责任主体与写入口 |
| --- | --- |
| Project definition、accepted Plan、SubGoal、budget、Outcome 与 Completion | `InvestigationProject` Aggregate，由 `InvestigationProjectService` 追加 typed event |
| Project 持久化 | `PostgresInvestigationProjectStore` 保存 definition 和 append-only journal |
| worker lease、retry 与死信 | `PostgresWorkerQueueStore` |
| 子智能体 definition、submission binding 与终态 | `AgentGateway` 与 `PostgresAgentRunStore` |
| Artifact 正文和私有路径 | `ArtifactService`；Project 只保存带作用域的 `ArtifactRef` |
| Tool 权限、幂等与执行事实 | `ToolGateway` |
| 开放语义 Plan、Execution Proposal 与 Verification | 对应模型 Port 产生 Proposal，Application Admission 决定是否接受 |

API 查询只读 projection，不调用模型，也不借查询推进 Project。

## 3. 生产主链

```text
POST /api/investigation-projects
  -> 保存 immutable definition
  -> 向 investigation queue 入队
  -> 202 + project_id

worker lease
  -> 从 journal 恢复 Project
  -> Planner Proposal -> Plan Admission -> accepted Plan
  -> 确定性计算 ready set
  -> Execution Proposal -> Tool / Agent / synthesis
  -> Evidence Admission -> Verification -> SubGoalOutcome
  -> Completion -> final ArtifactRef / report
```

Project 恢复时只能继续已提交事实。相同 submission key 不得盲目重提外部智能体；无法确认提交结果时必须 fail closed。用户暂停、系统暂停、取消与运行超时各自保留 typed 原因，不共用模糊终态。

## 4. Plan 的内聚边界

初始 Plan 与修订 Plan 必须分离。初始 Plan 定义完整待执行图；修订 Plan 只能修改未冻结部分，并保护已发生的 Proposal、ExecutionRef、Artifact 和 Outcome。

普通修订与 verification repair 不是两个事实责任主体。当前实现使用单一 `_PlanRevisionDraft`、单一物化路径和单一 Admission 语义；动态 Schema 只在存在冻结 verification gap 时允许 `independent_repair_subgoals`。初始 Plan 不与修订 Plan 合并，因为两者的写权限不同。

Verifier 拒绝已执行 SubGoal 时，旧执行事实保持冻结。修订 Plan 必须新增可运行 repair work，并将需求映射指向新 Outcome。工程曾尝试把所有非 frozen 下游依赖自动改指向 repair；正式 target 虽真实消费该机制，仍因 repair 结果契约不满足而得到 0 Outcome，因此自动重绑定及专用测试已经撤回。

## 5. 外部智能体边界

GPT Researcher 本身拥有规划、检索、迭代和综合循环。Project 外层又拥有 Plan、SubGoal Verification、repair 和 final Completion，因此当前路径存在重复编排风险。只移除 Project 外层循环的旧单次委托曾在 240 秒超时；根因定位到 A2A 内部无独立消费者的动态角色调用，而不是主工程 `json_schema`。

A2A 构造边界现已绑定确定性通用研究角色，其他 GPT Researcher 入口仍保留原行为。同任务单变量诊断由 240.14 秒超时变为 96.26 秒完成，生成两个官方来源组且 `choose_agent=0`；完整内容 grader 和 usage 契约仍未通过。随后正式 Project 重审形成 3 个 Artifact 和 4 个来源，但 repair 报告被 Verifier 拒绝，planning budget 随后用尽，仍为 0 Outcome。当前没有准入中的生产优化条目。

## 6. Verification 与 Completion

Tool/Agent success 不能直接完成 SubGoal。Evidence Admission 先校验来源、作用域和契约，Verifier 再判断用户要求是否语义满足。Completion 只能消费 active requirement 的 verified Outcome、最终 Artifact 和 required report contract。

当前 `0/20 delivered` 表明这条产品纵切尚未闭环。局部调度优化、预算边界、目标绑定或 Plan Schema 修复只能按各自证据强度陈述，不能合并为最终报告能力。

## 7. 运维入口

Project worker 使用独立队列：

```powershell
uv run personal-agent worker --queue investigation
```

直接 Project API 和 Conversation 创建路径复用 `InvestigationProjectService`。身份必须物化为 `AuthenticatedPrincipal`，读取、steering、审批、暂停、恢复和取消都校验 tenant/user scope。

当前评测身份、失败阶段和归档坐标统一见[当前端到端用例盘点](../evals/02-current-case-inventory.md)中的“Research、Schedule 与 Investigation”。
