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

## 2. E2E 阻塞按目标、阶段和单变量处理

**E2E 失败只是一条待归因事实，不能直接授权修改生产行为。** 处理顺序必须是“审查用例是否合理、定位用户结果链上的最早关键失败、只修复一个责任主体、先回跑原阻塞用例、再扩大受影响回归”。禁止从最终状态、预算耗尽或最后一条错误反向猜测根因。

每次阻塞分析必须依次完成：

1. 冻结并封存该次运行的用户输入、身份、初始事实、代码与配置身份、模型、服务提供方、评测器、预算、追踪记录和最终结果，避免后续重跑偷换比较条件。
2. 重新核对用例的唯一验收目的。每条断言必须直接对应用户可观察结果、必要反事实，或者全局权限、隔离、幂等和副作用不变量；内部工具、步骤、调用次数、固定预算和状态只有属于该用例声明的契约时才能阻塞通过。
3. 用例包含与设计初衷无关的附加要求时，先修正 canonical case contract、评测器或用例分类。该次失败只能证明评测设计错误，不能作为生产修复 baseline，也不得通过 Prompt、预算、状态或降级分支迎合。
4. 用例合理时，从正式入口沿 `Trace`、`Proposal`、Admission、执行事实、Verification 和 Completion 向前定位最早失败阶段。服务提供方不可用、输出契约违规、环境故障和评测脚手架错误必须与产品机制失败分开；后续连锁错误和预算耗尽不得冒充最早根因。
5. 只选择一个关键阻塞进入修复。关键阻塞必须同时满足：位于用户结果必经链上；比其他候选更早；有明确的决策或事实责任主体；修复后能够到达下一个可观察边界。日志最响、出现次数最多或离最终失败最近都不是选择理由。
6. 候选必须解释该责任主体为什么造成当前失败、最小修改如何切断因果链、什么反事实能够证明不是其他机制带来结果，以及失败时删除或撤回什么。无法回答任一问题时不得编码。
7. 完成一次有界修正后，首先只回跑原来的单个原子 E2E。该用例通过后，才运行直接受影响的 Contract 或 Runtime Conformance，再运行 impact map 选中的相邻 E2E，最后按发布需要运行完整样本组。
8. 同一阻塞经过一次定位和一次有界修正后仍复现时，停止追加局部补丁。保留失败证据，重新审查用例目的、最早失败阶段、责任主体和设计边界；不得靠扩大预算、增加重试或同时修改第二机制继续碰撞通过。

每次分析必须保存“用例目的与必要断言、合理性结论、最早失败阶段、选中的唯一阻塞、责任主体、因果说明、范围外失败、下一条最小验证及停止条件”。评测模块的登记和归档细则由[评测模块规范](../../evals/AGENTS.md)拥有。

## 3. Observability、安全与审计

Trace 按适用性记录 `trace_id`、tenant/user、thread/task、goal、proposal/version、policy/version、command/authorization digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和 error taxonomy。Trace 不得记录不必要的密钥、完整敏感内容或跨 scope 数据。

- Identity 和 scope 在入口解析并贯穿调用链；
- Policy 决定是否允许及是否需要审批；
- 执行网关统一执行授权、风险、预算和审计；
- Prompt 不能代替权限控制；
- 高风险操作必须绑定明确 target、payload、授权和确认；
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。

审批、授权、Command、Journal、Receipt、补偿和 Completion 必须关联到同一任务和 canonical digest 链路。审计记录不可被普通业务更新覆盖。
