# Workflow 文档索引

本目录说明明确 Application 用例、固定事务和周期执行的信息流。普通目标由 [Conversation Runtime](../topics/runtime.md)处理；各业务服务维护自身状态与恢复事实。

## 当前链路

| 阅读目标 | 文档 |
| --- | --- |
| 采集、知识写入与统一对话回答 | [Capture 与 Conversation Grounded Answer](capture-ask-model-flow.md) |
| Artifact、Evidence、Claim、冲突与知识投影 | [Personal Knowledge 生命周期](personal-knowledge-lifecycle-workflow.md) |
| Research digest 的证据装配与 grounding 组件 | [Evidence Engine](evidence-engine.md) |
| 固定删除、恢复、确认与重放 | [知识删除与恢复](delete-knowledge-workflow.md) |
| 一次性及订阅研究的领域执行 | [research_once](research-once-workflow.md) |
| 外部研究智能体的提交、Artifact 与父级综合 | [GPT Researcher A2A](gpt-researcher-a2a-workflow.md) |

## 责任与证据

Conversation、知识生命周期和周期 Research 各自拥有合法写入口；Tool/Agent Gateway 产生执行事实。语义核验和最终完成由各自结果契约约束，不能从工具成功或子智能体终态推导。

系统级边界见[当前核心架构](../summary/core-architecture-current-state.md)，工具协议见[工具专题](../topics/tools.md)，产品和发布证据见[评测盘点](../evals/02-current-case-inventory.md)。旧 Task/GoalGraph/Executive 总图和依赖它的专题已清理，迁移决定及有效历史证据保留在 ADR 与评测归档中。
