# 测试、评估、观测与安全细则（QLT）

> 本细则适用于测试、评测、真实环境、追踪记录、安全与审计。准入证据设计见[变更证据与设计准入](change-evidence.md)；评测代码、比较身份和归档见[评测模块规范](../../evals/AGENTS.md)。

## 1. 测试职责与覆盖

测试按实际验证边界分类。中文用户输入、真实决策链、E2E 资格和结果声明必须遵守[根规范第 2.1 节](../../AGENTS.md#21-证据先于设计)。

| 类别 | 验证职责 |
| --- | --- |
| Unit | 领域不变量和纯函数 |
| Contract | Port 与 Adapter 契约 |
| Integration / Runtime Conformance | 数据库、Checkpoint、执行网关、指定工具或智能体、顺序与内部协议等白盒组合 |
| Ablation | 新设计在独立代码状态中只移除目标机制，验证收益归因；缺陷修复不强制采用，也不得成为生产模式 |
| Real E2E | 目标用户经正式生产链与真实边界取得可自动断言的用户结果 |
| Offline Eval | 固定输入分布下的模型、检索和语义质量 |
| Online Evaluation | 线上质量、成本、延迟和失败分布 |

Fake 或 Stub 仅用于不可控第三方的可重复消融、危险副作用故障注入，以及低层 Contract 或 Conformance。它们必须实现生产 Port 并有 Contract，不得创造生产中不存在的能力，或替模型、Policy、Admission、Verifier 决策。冻结 Provider 只能证明相应可重复测试边界，不能证明真实交付；用户结果依赖的真实边界不得在 target 中被替换。

核心变更按适用性覆盖 Direct Message、只读 ToolCall、Governed Action、Durable Execution、拒绝、缺失能力、执行或验证失败、replay 不重算且不重复副作用、tenant/context 隔离，以及新路径生效和旧路径不可达。每项适用的行为变更至少有一个成功场景及一个失败、拒绝、恢复或重放场景。

新增或扩展语义决策、检索、回答、规划、验证及声称提升能力的机制，必须先补 Golden Set。样本覆盖多种自然表达、真实目标、边界、失败、反事实与历史回归；禁止提示预期内部策略。按照 EVD 固定比较契约，并预声明门槛、样本量或重复次数。结果报告须包含完成率或正确性、错误副作用，以及适用的模型轮次、工具或智能体调用、token/cost、延迟、重复副作用和恢复；没有可观察净收益不得进入主链。

Framework Protocol 使用 Contract，Runtime Mechanism 使用 Conformance 或 Integration；这些证据不能替代 Application Capability 的 Real E2E。框架抽取须为每个独立生产消费者保留至少一个契约用例，并由原用户目标的 Real E2E 证明行为未退化。

新增测试须保护明确的能力或安全边界、复现历史问题并帮助定位，或锁定容易误合并、误路由的核心决策；不为每次小改动机械新增单测。纯重构、实现细节或已被上层 Golden Set 充分覆盖且定位明确的变化，无须重复堆叠测试。架构不变量优先进入 CI；Procedure Contract、Capability scope 与 trajectory eval 分别验证固定拓扑、授权边界与开放策略质量。

## 2. E2E 阻塞按目标、阶段和单变量处理

E2E 失败只是一条待归因事实，不能直接授权修改生产行为。不得从终态、预算耗尽或最后一条错误反向猜根因。遇阻时按以下顺序处理：

1. 按[归档规则](../../evals/AGENTS.md#5-比较身份与归档)封存原始运行，固定输入、运行与评测身份，保留完整追踪记录和结果。
2. 核对用例唯一验收目的。每条断言必须对应用户结果、必要反事实或全局权限、隔离、幂等和副作用不变量；内部工具、步骤、调用次数、预算和状态只有属于公开契约时才能成为 Product E2E 通过条件。
3. 发现附加要求时，先修正 canonical case contract、评测器或用例分类。该失败只证明评测设计错误，不能作为产品修复 baseline，也不得通过增加 Prompt、预算、状态或降级路径迎合。
4. 用例合理后，从正式入口沿 Trace、Proposal、Admission、执行事实、Verification 和 Completion 定位最早关键失败。区分服务不可用、输出契约违规、环境和脚手架错误；后续连锁错误不得冒充根因。
5. 只选择一个用户结果必经链上最早且责任明确的阻塞。必须说明最小改动如何切断因果链、到达下一可观察边界，哪个反事实可以证明归因，以及失败时撤回什么；否则不得编码。
6. 完成一次有界修正后，首先只回跑原来的单个原子 E2E。该用例通过后，才扩展到直接受影响的 Contract 或 Conformance、impact map 选中的相邻 E2E，最后按发布需要运行完整样本组。
7. 同一阻塞仍复现时，停止追加局部补丁，按[EVD 遇阻复核](change-evidence.md#7-强制开发与设计流程)重新审查。不得靠扩大预算、增加重试或同时修改第二机制反复尝试直至通过。

每次分析保存“用例目的与必要断言、合理性结论、最早失败阶段、唯一阻塞及责任主体、因果说明、范围外失败、下一条最小验证与停止条件”。评测代码另按[模块规则](../../evals/AGENTS.md#3-每条用例必须有唯一验收目的)登记用例和审查记录。

原始 E2E 与局部检查点的判断必须分开。合法 typed 终态不自动表示通过或候选失败；归因和候选取舍统一按[EVD 第 1 节](change-evidence.md#1-用户结果与工程约束的可执行基线)，不得以局部通过覆盖产品失败。

## 3. Observability、安全与审计

追踪记录只记录任务所需的运行事实，不得包含不必要的密钥、完整敏感内容或跨作用域数据。按适用性记录 `trace_id`、tenant/user、thread/task、goal、proposal/version、policy/version、command/authorization digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和错误分类。

- 入口解析身份与作用域，并贯穿调用链。
- Policy 决定是否允许及是否需要审批；执行网关统一执行授权、风险、预算与审计。
- Prompt 不能替代权限控制；高风险操作必须绑定明确的 target、payload、授权与确认。
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。
- 审批、授权、Command、Journal、Receipt、补偿和 Completion 必须关联同一任务及 canonical digest 链路；审计记录不可被普通业务更新覆盖。
