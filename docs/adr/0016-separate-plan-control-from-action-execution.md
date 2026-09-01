# ADR 0016：分离 Plan 控制与具体动作执行

- 状态：Accepted，核心迁移与跨轮 target 已通过，当前单变量证据待完成
- 日期：2026-08-30
- 影响范围：Conversation working plan、模型动作协议、Admission、执行事实关联、Verification 与 Completion 顺序
- 详细设计：[普通对话研究交付与 Plan 边界优化方案](../future/conversation-research-delivery.md)

## 1. 背景与目标

普通 Conversation 已能执行真实 Web Search，却可能在交付答案前持续失败于
`plan_step_binding_required`、`working_plan_no_change` 和最终步骤枚举。用户目标是得到满足来源与
结论要求的研究结果，不是让每次 Tool Call 重复维护 Plan 外键。

本决策只调整 Conversation 的 Plan 控制协议：模型在 Plan 边界选择唯一活动步骤，具体 ToolCall
与 Agent Delegation 只携带业务参数，运行时把执行事实关联到 canonical 活动步骤；FinalMessage
先经过适用的 Verification 与既有 Completion 检查，门禁通过后才物化 Plan 完成。研究搜索策略、
Provider 重试、通用语义 Verifier、后台持续运行和固定预算均不在本决策范围内。

## 2. 已执行准入证据

clean baseline 来自代码身份 `c66fe9455d723e47ca3956e7a85980bb559c4eb7`，工作树
`dirty=false`，密封归档为
`data/e2e_traces/product_ablations/conversation-research-plan-binding-ablation-20260829/conversation-research-delivery-001/baseline/20260829T134532.983717Z-22796-e4dc8084`。
该单样本从正式入口运行 79.66 秒，四次 Tool 执行成功后仍未交付，最早本地拒绝为
`working_plan_no_change`，并出现 `completed_plan_step_immutable`；总用量为 83,922 tokens、六个
模型决策回合。checksum 已核对有效。

Provider Conformance 使用生产 `control_working_plan` Schema，固定三次相同请求，不暴露 Web、
数据库或业务工具。归档
`data/e2e_traces/provider_diagnostics/working-plan-tool-schema-conformance-001/20260830-v1/report.json`
记录为 3/3 payload 通过、0 次 Provider failure、0 次 Schema failure、总计 2,986 tokens、14.6 秒。
这只证明当前样本可以进入本地协议，不把历史 Provider 方差改写为已经消失。

阻塞 Product E2E `tool-protocol-boundary-run-1` 只验收三项比较维度、OpenAI 与 MCP 官方来源和
中文用户结果，不要求创建 Plan、指定工具、固定动作次数或内部步骤顺序，因此保留为 target。

核心迁移后的 dirty candidate 已通过该定向 Product E2E；它证明当前工作树可以交付该用户结果，
不与历史 clean 消融拼接为当前实现的因果证明。最新 `HARNESS-003` v4 已证明同一 Plan、唯一
`in_progress` Step 及其成功执行事实可以跨进程恢复。第二轮没有访问原始档案，并从 immutable
offload 取得正确口令；`DecisionFeedback` 按产生它的 Plan 版本隔离。Final 与 Action 顶层协议按
[ADR 0017](0017-separate-action-selection-from-final-delivery.md)分离后，完整用例已交付，Plan 最终全部
完成。结果与归档坐标由[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)维护。

## 3. 决定与责任主体

| 决策或事实 | 唯一 owner | 写入口与约束 |
| --- | --- | --- |
| 是否创建 Plan、当前推进哪个步骤、何时切换 | 模型 | `control_working_plan`；只在工作状态变化时提交 |
| 当前 Plan 与唯一活动步骤 | `ConversationWorkingPlan` | 非终止可执行 Plan 恰有一个 `in_progress`；等待审阅或终止 Plan 没有活动步骤 |
| 状态迁移与活动步骤唯一性 | Admission | 接受或返回 typed feedback；不得根据动作内容或步骤顺序猜测 |
| Tool/Agent 执行了什么 | 执行网关 | 执行时读取 canonical 活动步骤，并把内部 `step_id` 写入 `ActionObservation` 或 Artifact 执行事实 |
| 最终结果是否语义满足 | 模型或适用的领域 Verifier | FinalMessage 是交付提议；Receipt 和 Plan 状态不能替代 |
| required result contract 是否齐全 | Conversation 既有 Completion 出口 | 检查未读卸载结果等确定性证据；本次不创建通用 Completion 服务 |
| Plan 完成物化 | Conversation Application | 仅在 answer 通过 Verification 与 Completion 后完成剩余步骤并关联成功执行事实 |

破坏式迁移内容如下：

1. `WorkingPlanStepProposal` 与 canonical step 增加 `in_progress`；
2. 删除 `ToolCallProposal.plan_step_id`、`AgentDelegationProposal.plan_step_id` 及 Provider Schema 投影；
3. 保留 `ActionObservation.plan_step_id` 作为运行时执行事实，不向模型暴露；
4. 相同 Plan Proposal 成为无 revision 的幂等 no-op，同行合法动作继续；
5. 删除 `FinalMessage.resolved_plan_step_ids` 和答案前的 Plan 枚举门禁；
6. 删除“Plan 全部完成即进入专用 answer-only 调用”的控制流；模型必须先明确请求交付，再由独占
   finalization phase 生成 `FinalMessage`，具体协议由 ADR 0017 拥有；
7. limitation、failed、Verifier 拒绝或 Completion 拒绝均不完成 Plan。

## 4. Complexity Justification

新增的生产状态只有 `in_progress`，由 `ConversationWorkingPlan` 单一拥有，生产消费者是 Admission、
执行网关和跨轮 Journal。没有新增 Planner、Workflow、Router、Repository、表、配置、兼容分支或
第二份活动步骤投影。

同时删除两个模型侧逐动作外键、两份动作 Schema 拼装、逐动作绑定 Admission、FinalMessage 的
步骤枚举和专用 answer-only 控制流。净结果是模型字段与拒绝分支减少，内部执行事实关联能力保留。

## 5. 未采用方案

- 把 `plan_step_id` 改成可选：模型仍不清楚何时应填写，Admission 只能猜测，双重语义继续存在。
- 按工具名、调用顺序或第一个 pending 步骤自动关联：确定性代码会创造模型没有作出的开放语义决策。
- Tool success 自动完成步骤：Receipt 只能证明动作执行，不能证明步骤验收条件或用户 Goal 满足。
- 提高 token 或动作预算：baseline 的最早失败是协议拒绝，扩大预算只会放大重复循环。
- 新增通用 Plan Verifier 或 Completion 服务：当前 baseline 没有证明第二套语义责任主体必要。
- 保留旧字段或 feature flag：项目尚未进入兼容期，双轨协议会制造第二事实入口。

## 6. 迁移、验证与退出条件

所有生产调用方、Provider Schema、Prompt、Trace 读取者、Contract Test、Product E2E 与当前事实文档
在同一变更迁移，不保留旧字段、alias 或 fallback。回滚依赖版本控制和密封 baseline，不依赖旧
生产链。

模型动作 Contract、Plan 状态与执行关联、FinalMessage 拒绝/通过反事实，以及单个
`tool-protocol-boundary-run-1` target 已通过。`HARNESS-003` 的 Plan 与执行事实恢复、不重复原始读取、
offload 消费、跨 Plan 版本反馈作用域和最终用户交付均已通过。机制收益还需在独立可还原代码身份
执行只恢复逐动作绑定的 target-minus-mechanism 消融；在此之前不得把当前 dirty target 与历史 clean
消融拼成完整因果证明，也不得扩大到不受影响的昂贵 E2E。

若原阻塞用例仍最早失败于 Plan 协议、活动步骤关联无法跨轮恢复、拒绝答案完成了 Plan，或为通过
target 必须新增预算、重试、启发式路由或兼容双轨，则撤回本决策并删除候选实现。全部门禁通过后，
当前事实迁入 Conversation 架构与 Verification/Completion 专题，随后从 future 队列删除本候选。
