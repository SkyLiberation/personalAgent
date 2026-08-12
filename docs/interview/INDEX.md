# personalAgent 面试材料

> **主线只有一条：模型提出开放语义动作，确定性边界治理权力，Application/Domain 保存事实，Verifier 与 Completion Gate 判断目标是否完成。** 本目录是当前实现的讲述投影，不是开发日志、未来设计或第二份状态账本。

## 阅读地图

| 要回答的问题 | 文档 | 只在这里完整展开 |
| --- | --- | --- |
| 项目为什么存在、总体架构是什么 | [项目故事](01-project-story.md) | 定位、责任链、两分钟讲稿 |
| 自然请求如何经过真实生产路径 | [请求路径](02-request-walkthroughs.md) | Conversation、受治理事务、ResearchRun、InvestigationProject |
| 通用 Agent 机制如何划分 owner | [能力设计](03-capability-axes.md) | Context、Tool、Admission、预算、恢复、验证 |
| 长期业务事实如何建模 | [领域设计](04-knowledge-and-domain-workflows.md) | Knowledge、Research、Project 生命周期 |
| 哪些结论有何种证据 | [证据与发布](05-evidence-and-release.md) | catalog、paired evidence、指标、发布边界 |
| 如何回答高频追问 | [高频问答](06-qa-and-tradeoffs.md) | 一句话结论和跳转坐标 |
| 如何维护本目录 | [写作规范](00-writing-spec.md) | 事实源、去重和证据措辞 |

## 先记住五个判断

1. **Proposal 不是权限，ToolResult 不是完成，Trace 不是业务事实。**
2. **Application Capability 表达用户可验收的业务动作；Tool、MCP、Agent 是执行资源。**
3. **Conversation 是自然语言交互 owner，可以调用固定事务或创建 Project，但不接管它们的长期事实。**
4. **Artifact → Evidence → Claim 是知识事实链；向量和图是可重建检索投影。**
5. **当前有范围明确的产品 E2E 和机制诊断，但版本发布资格必须由 clean matching revision 的完整 gate 单独派生。**

## 推荐顺序

- 十分钟建立主线：`01 → 02 → 05`。
- Runtime 深挖：`03 → 06`。
- Knowledge/RAG 深挖：`04 → 05`。

## 权威事实入口

- 当前架构：[core-architecture-current-state.md](../summary/core-architecture-current-state.md)
- E2E 分类：[evidence_catalog.py](../../evals/e2e_quality/evidence_catalog.py)
- 发布派生：[release_gate.py](../../evals/e2e_quality/release_gate.py)
- 未落地候选：[design-optimization-backlog.md](../future/design-optimization-backlog.md)
- 强制工程规范：[AGENTS.md](../../AGENTS.md)

代码、catalog 或当前执行证据与本目录冲突时，修正文档，不为讲稿维护兼容解释。
