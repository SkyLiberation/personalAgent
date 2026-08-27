# 智能体决策与受治理执行细则（EXE）

> 本细则在任务涉及 Proposal、Admission、ToolCall、Command、Approval、digest、Receipt、Execution、Verification、Completion、replay 或 durable execution 时生效。

## 1. Proposal、Admission 与降级边界

模型可以提出 Goal、Plan、ToolCall、业务参数、恢复建议或最终回答，但 Proposal 不是权限、Command、执行事实或完成证明。直接回答不得为形式统一伪造 Task、Command、Receipt 或 CompletionReport。

Admission 只能接受或拒绝 Proposal，禁止补业务字段、拼接约束、修改 payload、替换 Goal、生成或重排 Plan，或静默降级。拒绝必须返回 typed `DecisionFeedback`，说明原因、mutable/immutable fields、required repair、revision scope 和 disposition。

模型不可用或 Proposal 连续不合法时，只允许 fail closed、暂停、请求用户或外部权威输入、请求缺失能力、等待环境变化、执行已冻结 Command，或对同一 digest 做幂等技术重试。禁止生成替代 Goal、Plan、查询、写入内容或业务回答。

Procedure 只封装 prepare、confirm、commit、receipt、compensate 和 reconcile 等稳定事务不变量；不得选择目标、决定 payload 或猜测失败后的替代路径。

确定性检查只能证明机械关系。禁止用模型自述、字符串包含、相似度、排名或自然语言断言冒充语义保持、授权或唯一性证明。

## 2. Execution、Verification 与 Completion

必须分离：

1. **Execution Fact**：工具或 Command 是否执行；
2. **Semantic Verification**：Goal 是否达到；
3. **Completion**：required result contract 是否全部满足。

Receipt 不能直接代表 Goal 完成；模型 Verifier 也不能推翻确定性执行事实。

## 3. Tool、Command、digest 与 Receipt

只读、低风险、可安全重试的 ToolCall 在 Admission 后直接执行，禁止为形式统一持久化 Command。

需要审批、具有外部副作用、不可安全重试、需要 durable execution，或跨授权或恢复边界的调用，必须形成 immutable Command。Command 只能缩权、不可覆盖；参数变化必须创建 superseding command。

digest 是冻结 canonical payload 的一致性指纹，不是身份、授权或执行证明。默认使用一个 canonical `CommandDigest` 绑定 Confirmation、Journal 和 Receipt。

框架只允许统一 Confirmation 的认证、授权、digest 绑定、审计和 outcome contract。具体 Application 或 Aggregate 拥有待确认 Command、pending/rejected/executed 状态、合法 decision、确认后的事务或恢复，以及 Receipt 业务含义。通用确认入口只能分发到 canonical Application 写入口，禁止直接改写业务状态。

只有同时满足以下条件时，才允许拆分 `AuthorizationDigest` 与 `ExecutionCommandDigest`：

- 用户授权后仍存在独立的 Command 编译、Provider binding 或 Grant 阶段；
- 两个 digest 有不同 owner、输入字段和信任边界；
- 系统可机械证明最终执行命令未超出授权；
- ADR 和 E2E 覆盖重绑定、参数变化、越权拒绝与 replay。

若授权内容与最终执行内容相同，禁止使用双 digest。客户端回传服务端生成的 digest 不能替代认证、Policy 或 Confirmation。

Command、Event、Receipt 不得机械成套创建：

- 仅当操作需跨请求、审批、重试或恢复时创建 Command；
- 仅当已发生事实有独立审计、订阅或重放消费者时创建 Event；
- 仅当需要 exactly-once 证明、外部结果关联或恢复依据时创建 Receipt；
- Projection 或 View 必须可从 canonical facts 重建，且禁止成为第二写入口。

## 4. 持久执行契约（Durable execution contract）

具体 Application Capability 或 Product Aggregate 只有确需跨请求、进程、审批或恢复边界时才使用 durable execution，并至少支持：

- 明确生命周期和合法状态迁移；
- checkpoint 与恢复；
- 相同 digest 的幂等执行；
- replay 不重新调用模型生成 Command；
- typed 失败、retry policy、补偿或 reconcile；
- required report 缺失时 fail closed。
