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

### 2.1 Plan 控制与具体工具不得混装

**新增或修改 Plan 与 ToolCall 协议时，模型只在工作状态发生变化时更新 Plan，具体工具只接收完成业务动作所需的参数。** 禁止要求模型在每次搜索、读取、写入或智能体调用中重复提交 canonical Plan 已经拥有的步骤标识；这种镜像字段不能增加语义信息，只会扩大服务提供方 Schema、Admission 和恢复失败面。

Plan 协议必须遵守以下责任边界：

1. 模型通过独立 Plan 控制 Proposal 创建、修订或终止工作项，并在执行前把一个工作项标记为 `in_progress`；等待用户审阅或 Plan 已终止时不得存在活动工作项。
2. `ConversationWorkingPlan` 或对应 Product Aggregate 唯一拥有 canonical 工作状态。Admission 只校验版本、引用、唯一活动项和合法迁移，不根据工具名、步骤顺序或自然语言猜测活动项。
3. ToolCall 和 Agent Delegation 只表达具体业务动作。执行网关在 Admission 后读取 canonical `in_progress` 工作项，并把其标识写入内部 `Observation`、`AgentArtifact` 或等价执行事实；没有 Plan 时关联为空，存在非终止 Plan 却没有唯一活动项时失败关闭。
4. 同一活动项下可以连续执行多个动作，不要求逐动作更新 Plan。模型只有在验收条件满足、用户改变目标、新事实要求修订，或需要切换工作项时才提交 Plan 变更。
5. 与 canonical Plan 完全一致的 Proposal 是幂等 no-op，不创建新版本，也不得阻塞同一 Proposal 中其他合法动作；幂等接受不能替模型完成、切换或改写工作项。

工具或 Command 的成功只产生 Execution Fact。模型可以根据执行事实提出中间工作项完成，但 Admission 只能校验状态迁移；它不能用 Receipt 自动生成语义完成事实。

### 2.2 FinalMessage 才触发整体结果验收

**整体结果只在模型提交 FinalMessage 后进入 Semantic Verification，不能由“所有 Plan 步骤已完成”或预算耗尽触发。** Plan 表达工作状态，FinalMessage 才表达模型准备交付给用户的整体结果；即使所有工作项已经完成，运行系统也必须等待模型提交实际答案。

最终交付顺序必须是：

1. Admission 校验 FinalMessage 的 Schema、身份、作用域和确定性不变量；
2. 适用时由 Verifier 判断答案是否满足 Goal 与 review criteria；
3. Completion Gate 检查 required result contract 和所需证据是否齐全；
4. 任一语义判断或结果契约失败时返回 typed feedback，Plan 保持未完成并继续模型决策；
5. 两道门禁通过后，运行系统才把剩余 `pending` 或 `in_progress` 工作项物化为已完成，并提交最终答案。

FinalMessage 不得通过重复枚举全部 Plan Step ID 来替代 Verifier。工具成功、Plan 状态、模型自述和固定预算也都不能替代 Semantic Verification 或 Completion Gate。

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
