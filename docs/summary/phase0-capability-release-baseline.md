# Phase 0 能力与发布证据边界

> 本文是 Phase 0 历史文档的稳定入口，不再维护第二份用例状态表。当前产品和机制证据由[当前端到端用例盘点](../evals/02-current-case-inventory.md)拥有，发布执行契约由[评测执行与发布](../evals/04-running-and-release.md)拥有。

## 1. 当前判断

Phase 0 建立的核心架构边界仍然存在，但历史 E01–E23、L01–L06、IP01 和 Provider 样本不再共享同一代产品契约。旧 archive 只证明对应冻结代码和配置，不能建立当前发布资格。

当前工作树的定向回归和多项产品证据可以支撑有限机制结论；完整 clean-revision release gate 尚未建立。因此文档和面试表述必须按具体用例给出证据，不得使用“Phase 0 已通过”概括当前产品。

## 2. 仍成立的架构结果

Phase 0 完成的以下边界仍由生产代码维持：

- Web、CLI 和飞书共用 Conversation Application 入口；
- 模型产生 typed Proposal，Admission 与 Policy 负责确定性准入；
- Tool 和 Agent 经执行网关产生 `Observation`，不直接宣告父目标完成；
- Personal Knowledge 拥有知识写入、删除、恢复和版本事实；
- `InvestigationProject` 拥有独立持久化生命周期，不与前台工作项清单共用 Plan 事实；
- `StrictJsonSchemaAdapter` 与 `JsonObjectStructuredAdapter` 隔离服务提供方的结构化输出传输差异；
- Verification 和 Completion 与执行成功分离。

这些是当前架构事实，不是当前全部产品能力通过的证明。完整主链见[当前核心架构](core-architecture-current-state.md)。

## 3. 当前证据分类

| 证据类型 | 可以支撑 | 不能支撑 |
| --- | --- | --- |
| 产品 E2E | 指定用户输入、代码和配置下的用户结果 | 未执行场景、其他 Provider 或未冻结代码天然通过 |
| Runtime Conformance | 指定协议、状态迁移或故障语义成立 | 最终用户目标已交付 |
| Provider diagnostic | 外部服务的可达性、延迟或兼容失败阶段 | 产品能力或架构候选已有效 |
| Unit / contract test | 类型、单一不变量或组件契约 | 正式入口的用户结果 |

## 4. 发布资格

当前禁止根据旧 Phase 0 archive 、当前工作树单测或单个 Provider 冒烟宣称可发布。发布证据必须同时绑定：

1. 可还原的干净代码身份；
2. 模型、服务提供方、输出传输方式和预算等配置样本组；
3. 正式入口的产品 E2E 与关键反事实；
4. 评测器版本、Trace、report 和 checksum；
5. 全量回归、分层门禁与未解决限制。

当前用例的具体状态、数据和归档坐标只在[当前端到端用例盘点](../evals/02-current-case-inventory.md)维护。
