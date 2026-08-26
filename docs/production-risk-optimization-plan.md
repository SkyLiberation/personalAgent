# 生产风险与优化准入

> 本文只提供当前生产风险的摘要和准入边界。唯一开放开发队列是[设计优化队列](future/design-optimization-backlog.md)；本文不维护 P0–P5 第二份状态，也不保留已完成实施流水。

## 1. 当前判断

当前最高的产品风险是 Durable Investigation Project 能创建和推进，却不能在当前 MiMo + GPT Researcher 样本组交付最终报告。主工程的局部 Plan、预算、调度和权限机制有各自证据，但不能代替 `0/20 delivered` 的产品结果。

第二类风险是运行事实与外部服务证据不完整。预算超时已与用户取消分离，但 GPT Researcher 尚未返回可核验 usage，其角色选择调用也没有类型化输出契约。

第三类风险是发布证据与当前工作树未绑定。定向回归和历史 archive 可以支撑限定机制结论，但不能建立 clean-revision 发布资格。

## 2. 当前风险映射

| 风险 | 当前证据 | 唯一下一门禁 |
| --- | --- | --- |
| 调查报告不交付 | 正式样本为 `20/20 project_selected`、`0/20 delivered` | 先定位最早阻止用户结果的单一责任主体，再做同输入 target 与消融 |
| GPT Researcher 角色输出不可靠 | 单次委托约第 172 秒才因 JSON 形状错误回退，240 秒内未交付 | 只对照远端 typed `AgentRoleSelection` 与删除动态角色调用，不扩大资源 |
| Agent usage 证据缺失 | 远端结果没有可核验 usage，投影也没有 typed usage 字段 | 先建立真实返回缺口与消费者，禁止为形式完整新增空字段 |
| repair 依赖仍可能指向 frozen gap | 本地消融成立，真实 Outcome target 未消费该候选 | 只在它重新成为最早用户结果阻断时恢复 A1 |
| 当前版本发布资格未建立 | 全量回归在 dirty worktree 通过，没有干净目标版本的完整产品矩阵 | 绑定可还原代码身份、配置样本组、评测器、Trace、report 和 checksum |

## 3. 已有治理机制的表述边界

下列机制已有生产代码和指定范围证据，不再作为本文的未完成实施计划：

- 知识删除与恢复的 immutable Command、确认绑定、Receipt 和幂等重放；
- 工具风险、Policy、审计与作用域校验；
- Memory 的授权召回、检索投影与 canonical fact 分离；
- Conversation 工作项清单的审阅、修订、失效义务和 Completion 边界；
- Agent 委托的 scope、budget、submission binding、ArtifactRef 和 timeout 事实。

这些机制的具体证据强度与限制只在[当前端到端用例盘点](evals/02-current-case-inventory.md)维护。没有新的自然用户失败时，不为它们增加表、状态、Planner、Workflow 或第二写入口。

## 4. 准入与停止规则

1. 产品风险先通过正式入口的失败 baseline 复现用户结果缺口。
2. 一次优化只定位一个责任主体，只关闭一个生产消费变量。
3. target 与消融使用同一入口、输入、身份、初始事实、配置和评测器。
4. target 失败后只能撤回、冻结或转入架构评审；不在同一轮增加预算、超时、重试或 Provider 专用提示词。
5. 已完成、已撤回和未达到准入门槛的方案不继续留在开放队列。

当前开放编号、状态和下一门禁见[设计优化队列](future/design-optimization-backlog.md)。
