# Future 设计索引

本目录只保存**尚未落地**、具有明确业务扩展和目标 E2E 的设计。当前生产事实归
[当前核心架构](../summary/core-architecture-current-state.md) 和对应 workflow 文档所有；历史
调试记录、已经完成的 phase、某次 archive 结果不属于 future。

## 当前设计

| 业务扩展 | 状态 | 文档 |
| --- | --- | --- |
| 统一自然语言受治理操作、live 长任务与能力规模化 | 目标路线图，尚未实施 | [现代 Agent 能力优化路线图](modern-agent-capability-optimization-plan.md) |
| 路径动态且需跨轮次恢复的架构调查项目 | 生产实现已装配，live 发布证据待闭环 | [Durable Investigation Project](durable-investigation-project-design.md) |
| 持续研究的来源验证与事件触发 | P1/P2，未实现 | [持续研究 P1/P2](scheduled-intelligence-research.md) |

## 进入与退出规则

新文档进入本目录前必须同时给出：

1. 当前最简单实现为何不能满足具体用户目标；
2. 用户可观察结果以及至少一个反事实；
3. 从正式入口进入生产主路径的目标 E2E；
4. 所需生产能力盘点，以及每个缺失能力的 owner、契约、入口、消费者、实施阶段、失败语义和测试；
5. Decision owner、Fact owner、唯一写入口和计划删除的旧路径；
6. 相对 baseline 的收益证据，不能只验证新增对象存在或把独立用例拼成组合能力证据。

能力落地后必须把当前事实迁入 summary、workflow、API 或运维文档，并删除对应 future 文档。
禁止在原设计后追加“已落地状态”“Phase 完成记录”或 Provider 调试流水账。
