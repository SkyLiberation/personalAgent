# 普通对话研究交付与 Plan 边界优化方案

**当前候选让模型只在 Plan 边界选择 `in_progress` 步骤，由运行时关联执行事实；动作选择与最终交付也在顶层分成两个互斥阶段。** 工具成功不代表步骤完成；只有 Final 通过适用的 Verification 与 Completion 后，确定性代码才物化 Plan 状态。该候选已按 [ADR 0016](../adr/0016-separate-plan-control-from-action-execution.md)与 [ADR 0017](../adr/0017-separate-action-selection-from-final-delivery.md)完成核心协议迁移。最新 `HARNESS-003` 已从正式 HTTP 入口交付全部口令与新阈值，恢复同一 Plan 与执行事实，第二轮没有重复访问原始档案，最终 Plan 全部完成。当前 target 已通过，但历史消融与当前 dirty candidate 不是同一代码身份，尚不能声明完整单变量因果或发布完成。准入状态由[设计优化队列](design-optimization-backlog.md)维护，执行事实与归档坐标由[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)维护。

本文只对应 `CONVERSATION-RESEARCH-DELIVERY-001`。它不建立第二份状态队列，也不把未来设计写成当前生产事实。

## 1. 目标是恢复研究交付，不是强迫模型维护 Plan 账务

`tool-protocol-boundary` 的用户结果是：普通 Conversation 查阅 OpenAI 与 MCP 官方来源，比较工具选择、权限边界和结果契约，并返回带官方 URL 的中文结论。是否创建 Plan、是否调用某个具体工具、内部步骤何时切换都不是该 Product E2E 的用户结果。

当前证据包含两个必须分开的失败阶段：

1. 服务提供方曾在 HTTP `200` 的响应中返回不符合 strict Schema 的 working-plan payload，Application 以 `provider_action_payload_invalid` 失败关闭；
2. 同输入的另一份样本通过动作解码并成功执行多次 Web Search，随后因 `plan_step_binding_required` 与 `working_plan_no_change` 未交付答案。

第一类是 Provider 输出契约问题，第二类是本地 Plan 协议问题。二者不能互相证明，也不能用放宽 JSON 校验、增加 token 预算或扩大重试掩盖。

本项不处理搜索结果累积、token、延迟、外部研究智能体委托、后台继续工作或交互意图分类；这些问题仍由各自队列项负责。

## 2. 根因是一个 Working Plan 承担了两种不同契约

`ConversationWorkingPlan` 原本用于让用户审阅、纠偏并跨轮继续可验收工作项；当前动作协议又要求模型在每次 Tool Call 或 Agent Delegation 中重复填写 `plan_step_id`。这让同一个 Plan 同时成为用户协作清单和逐动作外键协议。

模型已经决定当前要推进哪个步骤后，重复填写步骤 ID 不会增加语义信息。相反，字段缺失、重复提交未变化 Plan 或最终答案未精确枚举全部步骤 ID 都会在用户结果判断之前被拒绝。工具 Receipt 仍不能证明步骤完成，因此这套逐动作协议增加了失败面，却没有消除真正的语义判断。

优化后的责任边界如下：

| 决策或事实 | 唯一责任主体 | 约束 |
| --- | --- | --- |
| 是否需要 Plan、当前推进哪个步骤、何时切换步骤 | 模型 | 只在创建或改变 Plan 时决策，不在每个工具调用中重复 |
| 当前 Plan 与唯一活动步骤 | `ConversationWorkingPlan` | 用唯一 `in_progress` 状态保存；不得存在第二份镜像状态 |
| Proposal 是否引用合法 Plan 状态 | Admission | 只接受或拒绝，不猜测步骤、不改写 Proposal |
| Tool 或 Agent 的执行事实 | 执行网关与 `Trace` | 执行时读取 canonical 活动步骤并写入 Observation 或 Artifact |
| 用户结果是否满足目标 | 模型或 Verifier | 进行开放世界语义判断；工具成功和 Plan 状态不能替代 |
| required result contract 是否齐全 | Completion Gate | 只在语义接受后检查确定性证据，不自行补业务语义 |

## 3. 外部实现支持“计划更新与工具执行分离”

Codex 的 [`update_plan`](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/handlers/plan_spec.rs) 单独更新步骤状态，普通执行工具不要求携带 Plan Step ID。Claude Code 把 [`TaskUpdate`](https://code.claude.com/docs/en/tools-reference) 与 Bash、Edit、WebSearch 等工具分开；Gemini CLI 也把 [`write_todos`](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/tools.md) 与 Shell、Web 工具分开。

这些 A 级实现共同支持的机制是：模型在计划边界维护工作状态，执行工具只表达本次动作。它们不能直接证明本工程应采用相同 Schema，但足以否定“优秀 Agent 必须让每个工具调用重复携带步骤 ID”这一前提。

本工程仍需保留步骤与执行事实的内部关联。[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)中的 `HARNESS-003` 已证明，跨轮恢复并消费与步骤关联的成功事实，可以在冻结服务提供方场景中把重复原始读取从 `2` 降为 `0`。因此候选删除模型侧逐动作外键，同时保留运行时内部关联；不能直接删除 Observation 与 Plan 的关联能力。

## 4. 已实施候选采用唯一活动步骤

**本项只有三步因果决定，必须按顺序取得证据，不能把它们合并成一次补丁。** 服务提供方输出不稳定时无法判断本地 Plan 机制；逐动作绑定未移除时无法判断 FinalMessage 是否仍被 Plan 账务阻塞；用户结果尚未通过时也不能扩大回归。

| 决策步骤 | 已证明依据与必要性 | 为什么能够解决当前阶段 | 证伪与撤回条件 |
| --- | --- | --- | --- |
| 先稳定 Provider Conformance | 同输入曾分别停在违规 working-plan payload 和本地 Plan 协议；扁平 `control_working_plan` Schema 的固定三样本 Conformance 已通过 | 固定服务提供方输出契约后，本地 target 的失败才具有可比较责任主体 | 后续同身份 Conformance 再次不稳定时，不把 Provider 失败归因给 Plan |
| 再用唯一 `in_progress` 步骤替代逐动作 ID | 动作解码通过后出现 `plan_step_binding_required` 和 `working_plan_no_change`；模型侧外键现已删除 | 模型只在 Plan 边界表达语义归属，执行网关仍能机械保存内部步骤关联 | 原阻塞用例再次最早停在 Plan 绑定，或跨轮事实仍无法恢复时撤回候选 |
| 最后把 FinalMessage 放到 Plan 账务之前验收 | 旧 `admit_final_plan_resolution` 早于 Verifier，精确步骤 ID 会先拦截答案；现已删除该模型字段和专用 answer-only 路径 | FinalMessage 直接触发用户结果判断，Plan 只在 Verification 与 Completion 通过后物化 | 被拒答案导致 Plan 完成、或合法答案仍先被 Plan 状态拦截时撤回候选 |

每一步只解决表中对应阶段。Provider、Plan 绑定和最终交付之外的成本、搜索策略与委托失败继续留在各自队列项，不得混入同一 target。

### 4.1 Plan 能力保持可用，是否使用由模型决定

系统不使用任务长度、工具数量或关键词启发式判断“是否给模型 Plan”。Plan 能力保持在正式决策边界内可用，模型只有在它能避免遗漏、支持用户审阅、跨预算或跨轮恢复时才创建 Plan。用户明确要求先审阅计划时，现有 `review_plan` 边界仍要求先返回可审阅 Plan，审批前不得执行非 planning-safe 动作。

无 Plan 时，工具和智能体动作直接经过 Admission 与执行，不合成步骤 ID。存在 Plan 时，模型只在创建 Plan 或切换步骤时把一个步骤标成 `in_progress`；正常执行同一工作项期间不再更新 Plan。

### 4.2 活动步骤是 Plan 事实，不是每个动作的模型参数

`WorkingPlanStepProposal.status` 与 `ConversationWorkingPlanStep.status` 增加 `in_progress`，并建立一条唯一不变量：

- 无 Plan、等待用户审阅或 Plan 已终止时，不存在 `in_progress` 步骤；
- 准备执行 Plan 时必须且只能有一个 `in_progress` 步骤；
- 其余未完成步骤保持 `pending`；
- 只有模型提交合法 Plan 变更时才能把 `pending` 切换为 `in_progress`，运行时不得根据工具名或步骤顺序猜测。

`ToolCallProposal`、`AgentDelegationProposal` 及其服务提供方动作 Schema 删除 `plan_step_id`。Admission 接受动作后，执行网关在开始执行时读取 canonical Plan 中唯一的 `in_progress` 步骤，把其 `step_id` 写入内部 `ActionObservation` 或 `AgentArtifact`。没有 Plan 时内部关联为空；存在非终止 Plan 但没有唯一活动步骤时，非 planning-safe 动作以 typed reason 拒绝，要求模型先更新 Plan。

这意味着模型清楚“当前在推进哪一步”，但只表达一次。执行事实仍可按步骤恢复、审计和消费，工具协议不再反复要求模型复制同一个外键。

### 4.3 Plan 只在语义边界变化时更新

模型只在以下事件提交 Plan 变更：

1. 创建或根据用户反馈修订 Plan；
2. 当前步骤的验收条件已经满足，需要标记完成并激活下一步骤；
3. 新事实使步骤需要替换或终止；
4. 用户改变目标或要求重新规划。

每次 Tool Call 成功后不强制更新步骤。工具 Receipt 只形成执行事实，不能自动把步骤标成 `completed`。模型提交与当前 Plan 完全一致的 Proposal 时，Admission 将其视为幂等 no-op：不创建 revision、不产生 `working_plan_no_change` 阻塞，同行的合法动作仍可执行。该规则只消除无状态变化的重复写入，不替模型完成、切换或改写步骤。

## 5. 先判断用户结果，再物化 Plan 完成事实

当前 `FinalMessage.resolved_plan_step_ids` 要求模型在答案中再次精确枚举所有待完成步骤，并且 `admit_final_plan_resolution` 早于 Verifier 运行。结果是答案可能已经满足用户目标，却先因 Plan 账务不完整被拒绝。

条件候选删除 `FinalMessage.resolved_plan_step_ids`，并采用以下顺序：

1. 模型提交 `FinalMessage`，表达它对当前用户目标已经全部满足的语义判断；
2. 需要独立复核时，Verifier 判断答案是否满足目标与 review criteria；
3. Completion Gate 检查用户要求的结果与证据是否齐全；
4. Verifier 或 Completion Gate 拒绝时继续决策，Plan 保持未完成；
5. 语义判断与结果契约都通过后，确定性代码把全部 `pending` 与 `in_progress` 步骤物化为 `completed`，并关联已记录的成功执行事实。

这里的确定性代码不判断“答案是否足够好”，只落实已经通过语义判断和结果契约的完成决定。如果答案没有覆盖全部 Plan 义务，模型必须继续执行，Verifier 或 Completion Gate 也必须拒绝该答案；Plan ID 不能替代这项语义检查。工具成功仍不会触发完成；`limitation`、`failed` 或任一门禁拒绝的答案也不会完成 Plan。这样既不让固定预算替代 Agent 决策，也不让内部 Plan 账务先于用户结果阻塞交付。

## 6. Action 与 Final 采用两个互斥阶段

旧协议把携带完整答案的 `control_final_message` 与 Tool、Agent、Plan control 放在同一组 Provider actions。普通工具可以合理并行，但 Final 表示终止；Provider 一旦把两者同时返回，Application 只能拒绝全部意图。把 strict `FinalMessage` Schema 与工具列表放到同一个 `auto` 请求也不可行：两次真实诊断样本都在零工具时直接选择 Final，其中一次编造了并不存在的本地证据。

当前协议采用两个阶段：

1. action phase 只暴露具体 Tool、Agent、`control_working_plan` 与无参数 `prepare_final`；可以返回多个彼此兼容的普通动作；
2. `prepare_final` 不携带答案，只要求兼容动作执行完成后进入下一相位；
3. finalization phase 不暴露任何 actions，只按 strict Schema 生成 typed `FinalMessage`；
4. `StructuredModelResponse` 在 Port 边界禁止 typed value 与 action invocations 同时存在；
5. Verifier 返回 `needs_revision` 时直接留在 finalization phase 修订文字；返回 `insufficient_evidence` 时才回到 action phase 补证据。

这让具体工具仍只做具体事，也避免模型为了改一版 Final 先提交没有业务意义的工具调用。相位状态只存在于当前 Application loop，不持久化、不复制 Plan、Receipt 或 Completion 事实。

Provider Conformance 仍是独立边界。隔离三样本已证明扁平 `control_working_plan` strict Schema 可用；若 required action phase 偶发返回纯文本，Adapter 只允许一次使用相同 action definitions 的协议修复，明确要求 action calls 且不接收纯文本。第二次仍缺 action 继续以 `provider_action_missing` 失败关闭。未知 action、非法参数或 Application payload 违规不由 Adapter 删除字段、猜测意图或降级 strict 校验。

## 7. 验收同时保护用户交付与 Plan 反事实

Product E2E 继续从正式 Conversation HTTP 入口使用用户自然表达，只断言多来源中文结论、官方 URL 和既有安全反事实；不得要求“必须建 Plan”“不得建 Plan”或指定工具调用次数。

运行契约必须另外证明：

1. 无 Plan 时，动作 Schema 不含 `plan_step_id`，合法动作可以执行；
2. 有 Plan 时，模型只把一个步骤标成 `in_progress`，连续多个动作都由运行时关联到该步骤；
3. 活动步骤缺失或非法时失败关闭，Admission 不按动作内容猜测；
4. 相同 Plan Proposal 是无 revision 的幂等 no-op，不阻塞同行合法动作；
5. Tool 或 Agent 成功不会自动完成步骤；
6. Verifier 或 Completion Gate 拒绝的答案不完成 Plan，两者通过后才物化全部剩余步骤的完成事实；
7. 用户要求计划审阅时，审批前仍无非 planning-safe 执行；
8. `HARNESS-003` 显式 Plan 场景恢复同一 Plan 及其 `pending|in_progress` Step 的成功执行事实，跨轮 steering 后不重复读取按次计费的原始档案；自发建 Plan 与简单问答反事实继续由 `CONV-002` 等各自 owner 验收。

当前定向 Product E2E 已在 dirty candidate 上交付，证明该工作树不再由旧 Plan 外键协议阻塞；历史 clean target-minus-mechanism 仍失败，但它不能与不同代码身份的 dirty target 拼成当前实现的完整单变量因果证明。

最新 `HARNESS-003` v4 归档为 `data/e2e_traces/product_baselines/harness-003/target/20260831T053359.624686Z-9232-a8b902dd`，checksum 有效，结果 `1/1 passed`。两轮共 11 个模型回合、14 次工具或 workflow 调用、97,363 tokens，pytest call 阶段 159.105 秒。该样本证明：

- 同一 Plan、`pending|in_progress` Step 与成功执行事实可以跨进程恢复；
- 第二轮没有重复访问三份按次计费原始档案，immutable offload 可以继续读取；
- Plan 版本变化隔离同类反馈；
- `needs_revision` 在 finalization phase 直接重写答案，`insufficient_evidence` 才恢复动作；
- 最终结果只包含新阈值和三份正确口令，Plan 全部完成。

相较最近一次失败样本的 13 个模型回合和 143,161 tokens，本次为 11 回合和 97,363 tokens；这是同一用例的观测值，不构成通用成本或延迟收益声明。该 target 绑定 dirty candidate 且只有一个样本，不外推跨 Provider 稳定性，也不替代独立代码身份的单变量证据。

## 8. 复杂度预算、ADR 与退出条件

本候选只增加一个 `in_progress` Step 状态，其生产消费者是执行网关与跨轮 Journal；同时已删除 Tool/Agent Proposal 的 `plan_step_id`、动作 Schema 投影、逐动作绑定 Admission、`FinalMessage.resolved_plan_step_ids` 以及答案前的 Plan 完成阻塞。为保持既有长结果事实可消费，还明确了两个原有不变量：读取一个窗口不消费 immutable offload，精确重跑其生产工具会被拒绝；同一 Proposal 中完全相同且可并发安全的读取只执行一次。没有新增 Planner、Workflow、Router、Repository、持久状态机、运行模式、fallback 或双轨协议。

该变更修改 Plan、执行事实与 Completion 的协议顺序，ADR 已记录事实 owner、迁移范围、旧字段删除、回滚方式和退出条件。所有调用方、Provider Schema、Trace 读取者、测试与当前事实文档必须在同一变更迁移，不保留兼容字段。

Provider Conformance、历史 clean failure、ADR、Complexity Justification 与原子 target 已满足当前实现阶段，因此本项仍处于 `A2`，但不再把模型最终整理失败登记为当前阻塞。受影响的 `tool_calling_protocol` 套件已取得 `4/4 capability passed`；其中 `E16` 因外部 GitHub `401` 保持 Product E2E 失败，不归因给本候选。下一步只允许在独立可还原代码身份执行 target-minus-mechanism 单变量验证；不得重新修改 Prompt、预算或另一个责任主体来扩大候选。全部门禁通过后，当前事实迁入 Conversation 固定流程与 Verification/Completion 专题，随后从[设计优化队列](design-optimization-backlog.md)移除 `CONVERSATION-RESEARCH-DELIVERY-001` 并删除本文。
