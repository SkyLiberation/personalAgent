# 生产风险优化方案

## 结论

`docs/interview/06-qa-and-tradeoffs.md` 中列出的生产风险与改进方向是当前面试口径。当前项目已经具备 checkpoint、tool audit、Postgres 幂等账本、删除前确认、知识版本链等基础能力，但距离生产可控仍有几个关键缺口。

其中最大的生产风险曾是：**高风险知识删除缺少可恢复确认、幂等执行和精确恢复依据**。当前 P0 由固定的 `KnowledgeLifecycleService` 主链承担。

这个风险优先级最高的原因是：

- 删除属于不可逆副作用，影响用户长期记忆和信任。
- prepare 与 confirm 分离，prepare 不产生业务副作用并可跨进程恢复。
- 一个 canonical `command_digest` 把用户确认绑定到实际 Command payload。
- Operation、Personal Knowledge 状态迁移和 Receipt 在事务边界内保持一致。
- Delete Receipt 保存 Item/Claim previous states，Restore 以它作为唯一恢复依据。
- 相同 Command replay 返回同一 Receipt，不重复删除或恢复。

因此，后续优化应优先围绕“删除安全、审计可查、权限约束、事实固化、冲突治理、回放治理”逐层推进。

## 优先级总览

| 优先级 | 方向 | 目标 |
| --- | --- | --- |
| P0 | 删除安全与恢复 | 删除可撤销、可追踪、可补偿 |
| P1 | 工具审计产品化 | 高风险操作可查询、可脱敏、可告警 |
| P2 | 生产权限模型 | personal knowledge/tenant/RBAC/ABAC 可落地 |
| P3 | 固化质量候选假设 | 先用 baseline 验证长会话噪声是否造成错误知识 |
| P4 | 知识冲突治理 | 自动发现冲突，降低错误覆盖 |
| P5 | replay 治理 | 保留现网问题复现价值，同时约束副作用 |

## P0：删除安全与恢复

### 当前状态

当前工程已具备 durable prepare/confirm、scope 校验、单 digest、事务 Receipt、
exactly-once replay 和精确恢复。删除确认后，Personal Knowledge Knowledge Item/Claim
进入 deleted 状态；如果用户后悔，可以基于已执行 delete command 创建独立
restore command。

剩余风险是恢复冲突处理还比较基础：如果删除后同一知识已被新版本替代，当前恢复会按快照恢复原记录，尚未进入 `pending_restore_review` 或自动冲突合并流程。

### 优化方案

1. 删除和恢复只有一个 Application 写入口。**已落地**
2. prepare/decision 使用 `knowledge_lifecycle_operations`，执行结果使用
   `knowledge_lifecycle_receipts`。**已落地**
3. 双 digest、六张生命周期表、无消费者 Event、通用 Procedure/Tool 和 snapshot
   写路径已移除。**已落地**
4. 增加恢复冲突处理。**待落地**
   - 如果原 note 已被新 note 替代，恢复时不直接覆盖。
   - 进入 `conflicted` 或 `pending_restore_review` 状态，由人工确认是否恢复、合并或保持删除。

### 验收标准

- 已删除知识不会出现在普通检索结果中。**已验证**
- 删除 Command/Receipt 保存原因、执行人、确认引用和 affected facts。**已落地**
- 删除后的 Item/Claim 可以通过 delete receipt 精确恢复。**已验证**
- 重启与 replay 不重复副作用。**已验证**
- 恢复冲突进入人工 review。**待落地**

## P1：工具审计产品化

### 当前风险

工具审计事件已经落到 Postgres，但主要还是底层数据能力。生产上还需要查询、脱敏、告警、确认人记录和后台视图，否则问题发生后定位成本高，也难以满足高风险操作留痕要求。

### 优化方案

1. 增加审计查询 API。**已落地**
   - 按 `user_id`、`run_id`、`thread_id`、`tool_name`、`risk_level`、`execution_mode`、`side_effect_id`、`artifact_ok`、时间范围查询：`GET /api/audit/events`。
   - 按 idempotency key 追踪一次工具调用生命周期（账本 + 审计事件）：`GET /api/audit/events/by-idempotency/{key}`。
   - 策略决策查询：`GET /api/audit/policy-decisions`（gateway 与 facade 两条路径的决策都经 `set_policy_decision_sink` 落到 `tool_policy_decisions` 表）。

2. 增加审计脱敏策略。**已落地**
   - `storage/audit_redaction.py` 按字段脱敏：`input` 内容字段（text/content/title/url/note_id 等）、`output.data`、`evidence` 默认掩码为 `<redacted:N chars>`，治理结构字段（tool_name/risk_level/side_effects/artifact_ok 等）保留。
   - 仅管理员 API key 可传 `reveal=true` 查看原始 payload；普通用户查询强制限定到自身 `user_id` 且恒定脱敏。

3. 增加高风险确认记录。**已落地**
   - `tool_audit_events` 提升一等列：`run_id`、`confirmed`、`requires_confirmation`、`risk_level`、`side_effect_id`、`error`、`latency_ms`、`attempts`。
   - 配合幂等账本（confirmer=user_id、committed_at）与删除快照（deleted_by/delete_reason/run_id），可回答“谁在什么时候确认了什么”。

4. 增加指标和告警。**已落地**
   - `GET /api/audit/metrics` 聚合：删除失败率、失败率、高风险调用数、重复 idempotency（幂等拦截特征）、策略拒绝数。
   - 超阈值产生 `alerts` 并打点 `audit.alert` 指标。

### 验收标准

- 能通过 API 查询某次高风险工具调用的完整链路。**已满足**
- 审计查询默认脱敏。**已满足**
- 高风险操作能明确回答“谁在什么时候确认了什么”。**已满足**
- 异常删除或重复调用能触发指标或告警。**已满足**

## P2：生产权限模型

### 当前风险

PolicyEngine 已有基础策略拦截，但还缺 personal knowledge、tenant、RBAC、ABAC、API key 生命周期等生产级权限模型。多用户、多空间或管理后台接入后，权限边界容易变成隐性约定。

### 优化方案

1. 引入 personal knowledge/tenant 上下文。
   - 所有 run、thread、note、tool audit、checkpoint 关联 personal knowledge。
   - API 层强制传递并校验 personal knowledge scope。

2. 增加 RBAC。
   - 普通用户：只能管理自己的记忆。
   - 管理员：可查询审计、执行受控恢复。
   - 运维/调试角色：可 replay，但默认 dry-run。

3. 增加 ABAC。
   - 根据工具风险等级、数据敏感级别、来源、用户状态、时间窗口做动态策略。

4. 完善 API key 和服务身份。
   - key 绑定 personal knowledge、角色、过期时间和允许工具集合。
   - 所有后台操作写入 actor 类型：user、admin、service、system。

### 验收标准

- 跨 personal knowledge 访问被拒绝。
- replay、restore、delete 等高风险接口需要明确角色授权。
- 审计记录能区分用户、管理员、服务账号和系统任务。

## P3：固化事实收敛

### 当前风险

Conversation governed save 已只冻结模型从 user message 中逐字选择、由 Admission 机械校验
来源的知识 span，确认后复用 Personal Knowledge `solidify_conversation`；assistant message 和保存/确认
控制语义不会成为写入内容。B02 -> E14 已闭合单个明确结论场景；长 user message 中的临时假设、
否定或修正仍未由正式入口 baseline 证明，因此以下内容只是待验证假设，不是实现授权。

### 优化方案

先执行同一自然输入的 baseline E2E，自动断言错误 Claim 内容；baseline 未失败或失败来自测试/
环境时停止。只有产品错误成立后才选择最小方案：

1. 将 solidify 输入约束为确认事实。
   - 只消费 `confirmed_user_facts`、明确用户声明、明确用户修正。
   - 禁止消费助手推断、未确认总结、临时上下文。

2. 增加事实来源证据。
   - 每条候选知识绑定原始消息 ID、摘要字段、置信度和确认状态。

3. 增加固化前校验。
   - 缺少证据、来源为 assistant-only、置信度不足时进入 review，不直接写入。

4. 增加回归评测。
   - 长会话噪声、用户纠正、否定事实、临时假设、角色扮演等用例。

### 验收标准

- assistant 推断不会被直接固化为用户知识。
- 用户明确否定或修正后，旧事实不会继续被固化。
- 固化候选可追溯到具体消息或 summary 字段。

## P4：知识冲突治理

### 当前风险

知识版本链和 `conflicted` 状态已经存在，但冲突发现主要依赖显式流程。生产上，用户偏好、身份信息、长期事实会随时间变化，需要自动冲突检测和置信度模型辅助决策。

### 优化方案

1. 增加冲突检测。
   - 对同一 subject、predicate、scope 的知识进行语义相似和矛盾判断。
   - 检测到冲突后进入 `conflicted` 或 `pending_review`。

2. 增加置信度模型。
   - 用户直接声明 > 用户修正 > 多轮一致出现 > 助手推断。
   - 越新的明确修正优先级越高。

3. 增加冲突处理视图。
   - 展示旧事实、新事实、证据消息、影响范围。
   - 支持保留旧事实、接受新事实、合并、标记已过期。

### 验收标准

- 明显互斥知识不会静默覆盖。
- 冲突知识不会直接进入默认检索结果。
- 人工处理后版本链保持可追踪。

## P5：replay 治理

### 当前价值

`replay_from_checkpoint` 的关键价值不是用户级删除恢复，而是现网问题复现。它可以定位某个用户、某个 run、某个 checkpoint 的失败状态，并从该状态 fork 回放，从而复现当时的候选知识、确认状态、工具输入和编排路径。

### 当前风险

如果 replay 不加治理，可能重复触发外部副作用，或者让调试能力变成绕过正常权限与确认流程的入口。

### 优化方案

1. replay 默认 dry-run。
   - 默认禁用真实外部写入和真实删除。
   - 工具调用进入 shadow mode，记录将要执行的工具与参数。

2. replay 需要独立权限。
   - 只允许管理员、运维或调试角色使用。
   - 必须绑定 incident、run_id、thread_id 和操作原因。

3. replay 写入审计。
   - 记录 replay 发起人、源 checkpoint、fork 后 checkpoint、输入覆盖、工具策略。

4. replay 与幂等账本配合。
   - 默认使用新的 replay namespace，避免污染原始执行账本。
   - 允许只读重放、工具 mock 重放、受控真实重放三种模式。

### 验收标准

- replay 可以复现线上失败路径。
- 默认不会重复执行真实删除或外部写入。
- 所有 replay 行为可审计、可追踪、可按 incident 查询。

## 推荐实施顺序

1. **P1 工具审计产品化**：P0 数据恢复闭环已落地，下一步要让删除、恢复、replay 和外部副作用都能被查、被解释、被告警。
2. **P2 生产权限模型**：在管理后台和多用户场景扩展前，先建立明确授权边界。
3. **P5 replay 治理**：已有 replay 能力应尽快约束默认行为，避免调试接口变成副作用入口。
4. **P3 固化事实收敛**：降低错误知识进入长期记忆的概率。
5. **P4 知识冲突治理**：在长期记忆规模增长后，提升质量和人工处理效率。
6. **P0 恢复冲突补强**：为 restore 增加冲突检测、人工 review 和合并策略。

## 第一阶段落地建议

第一阶段建议只做 P0 与 P1 的最小闭环：

- 删除改软删除。
- 增加删除前快照。
- 增加 restore API。
- 恢复操作接入 ToolGateway、PolicyEngine、幂等账本和审计。
- 增加最小审计查询 API，支持按 run、thread、tool、risk 查询。
- 给删除和恢复补充单元测试与集成测试。

完成后，系统至少能回答三个生产问题：

- 这条知识是谁、什么时候、因为什么删掉的？
- 删除前它的完整内容是什么？
- 如果误删，能否在业务层恢复？
