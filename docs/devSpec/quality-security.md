# 测试、评估、观测与安全细则（QLT）

> 本细则在任务涉及测试、评测、Golden Set、真实环境、Trace、安全、权限、审计或发布证据时生效。产品变更的 baseline、消融与 target 设计见[变更证据与设计准入](change-evidence.md)。

## 1. 测试职责与覆盖

- Unit：验证领域不变量和纯函数；
- Contract：验证 Port 与 Adapter 契约；
- Integration / Runtime Conformance：验证数据库、Checkpoint、执行网关、指定工具或智能体、执行顺序和内部协议等白盒组合；
- Ablation：在独立可还原代码状态中，从同一正式入口只移除目标机制，证明收益来自该机制；Ablation 不得成为生产模式；
- Real E2E：目标用户以真实场景和自然表达，经生产 Composition Root、真实模型、持久化与服务提供方，获得可自动断言的用户结果；
- Offline Eval：评估模型、检索和语义质量；
- Online Evaluation：评估线上质量、成本、延迟和失败分布。

核心变更按适用性覆盖 Direct Message、只读 ToolCall、Governed Action、Durable Execution、Admission/Authorization Denied、Capability Missing、Execution/Verification Failure、replay 不重算且不重复副作用、tenant/context 隔离，以及新路径生效且旧路径不可达。每项变更至少包含一个成功场景和一个失败、拒绝、恢复或重放场景。

新增或改变语义决策、检索、回答、规划、验证及任何声称提升能力的 Runtime 机制时，必须先补 Golden Set。Golden Set 必须覆盖多种自然表达、真实目标、边界、失败、反事实和历史回归，禁止用内部名称或预期步骤提示模型。必须用同一评测契约对照 baseline、单变量消融和真实 target，预先定义门槛与样本量或重复次数，并报告完成率或正确性、错误副作用及适用的模型轮次、工具或智能体调用、token/cost、延迟、重复副作用和恢复结果。没有可观察净收益时，不得进入主链。

Framework Protocol 使用 Contract Test，Runtime Mechanism 使用 Runtime Conformance 或 Integration Test；二者都不能替代 Application Capability 的正式入口 Real E2E。抽取框架能力必须为每个独立生产消费者保留至少一个契约用例，并由原用户目标的 Real E2E 证明抽取后行为未退化。

## 2. Observability、安全与审计

Trace 按适用性记录 `trace_id`、tenant/user、thread/task、goal、proposal/version、policy/version、command/authorization digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和 error taxonomy。Trace 不得记录不必要的密钥、完整敏感内容或跨 scope 数据。

- Identity 和 scope 在入口解析并贯穿调用链；
- Policy 决定是否允许及是否需要审批；
- 执行网关统一执行授权、风险、预算和审计；
- Prompt 不能代替权限控制；
- 高风险操作必须绑定明确 target、payload、授权和确认；
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。

审批、授权、Command、Journal、Receipt、补偿和 Completion 必须关联到同一任务和 canonical digest 链路。审计记录不可被普通业务更新覆盖。
