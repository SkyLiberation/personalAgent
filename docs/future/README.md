# Future 设计索引

本目录只保存尚未落地的目标，或明确分隔“已落地前提”和“未准入候选”的路线图。当前生产事实归
[当前核心架构](../summary/core-architecture-current-state.md) 和对应 workflow 文档所有；历史
调试记录、已经完成的 phase、某次 archive 结果不属于 future。

## 当前设计

| 业务扩展 | 状态 | 文档 |
| --- | --- | --- |
| 当前框架、文档事实源、架构门禁与 clean release 证据收敛 | G0 已完成；R0 待完成；M0 部分完成 | [可信 Agent Runtime 演进与收敛](trusted-agent-runtime-evolution.md) |
| 持续研究的来源验证与事件触发 | P1/P2，未实现 | [持续研究 P1/P2](scheduled-intelligence-research.md) |
| Context 物化的度量、逐出与两阶段能力加载 | P0 已落地（纯观测）；P2 已测量后不准入；P1 未准入且决定性测量待执行（重跑 E21） | [Context 物化度量与逐出](context-materialization-measurement-and-eviction.md) |

## 进入与退出规则

新文档进入本目录前必须同时给出：

1. 已实际执行的最简单生产 baseline、失败结果、trace 和产品根因；
2. 用户可观察结果以及至少一个反事实；
3. baseline 失败后定义的、从正式入口进入生产主路径的目标 E2E；
4. 所需生产能力盘点，以及每个缺失能力的 owner、契约、入口、消费者、实施阶段、失败语义和测试；
5. Decision owner、Fact owner、唯一写入口和计划删除的旧路径；
6. 相对 baseline 的收益证据，不能只验证新增对象存在或把独立用例拼成组合能力证据。

能力落地后必须把当前事实迁入 summary、workflow、API 或运维文档，并删除对应 future 文档。
禁止在原设计后追加“已落地状态”“Phase 完成记录”或 Provider 调试流水账。
