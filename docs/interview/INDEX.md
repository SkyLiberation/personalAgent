# personalAgent 面试材料索引

本目录只描述截至 2026-07-30 已落地并有代码或 E2E 证据的当前架构，不把未来设计写成当前事实。

面试时先讲一句话：

> personalAgent 构建的是一套可信 Agent Runtime：模型负责开放语义 Proposal，确定性系统负责
> Admission、权限和执行，执行系统产生事实，Verifier 与 Completion Gate 关闭用户目标。短动态
> 请求、固定事务和 durable 动态长任务分别进入 Conversation、Application Workflow 和
> Investigation Project；三条主链共享权力边界，但不共享一个 God Task 或通用 Planner。

最重要的当前边界：Conversation 已能通过粗粒度 Application Capability 完成一条“明确 user
message、确认后保存”的受治理链路，E14 覆盖原文冻结、确认前零写入、恢复、scope 拒绝、
精确 Claim、保存/确认控制语义零写入、Receipt 和 replay。它不证明删除、订阅变更、冲突核对
后保存、跨实例协调或 commit/Receipt crash window。Investigation Project 已有生产
Domain/Application/PostgreSQL 路径、LT01-LT13 诊断证据和 IP01 live target 报告交付；完整
clean-revision release matrix、跨 Provider 组合矩阵和重复运行方差仍未闭合。

## 建议阅读顺序

1. [项目介绍与面试讲稿](01-project-story.md)
   - 项目解决什么问题；
   - Conversation、Application Workflow、Investigation Project 三条生产主链；
   - 30 秒、2 分钟和 5 分钟介绍；
   - 为什么它不是普通聊天机器人或 RAG Demo。

2. [从真实请求理解架构](02-request-walkthroughs.md)
   - 直接回答、查知识、MCP、A2A、保存、删除、周期研究和动态长调查分别怎么运行；
   - 什么是固定产品操作；
   - Agent 当前如何选择能力，以及哪些操作尚不能从 Conversation 进入。

3. [Agent 主循环、Tool 与治理](03-agent-loop-and-governance.md)
   - `AgentTurnDecision`、Observation 和 Feedback；
   - ToolGateway、AgentGateway、预算、并发、恢复和 Verifier；
   - 模型与确定性代码的决策所有权。

4. [知识、领域 Workflow 与 Durable Project](04-knowledge-and-workflows.md)
   - Artifact、Evidence、Claim、KnowledgeItem 的关系；
   - Ask/Save 分离；
   - Delete/Restore Command；
   - Research、Subscription、Worker、Digest 和 Delivery；
   - ResearchRun 与 Investigation Project 的生命周期边界。

5. [E2E 与工程可信度](05-e2e-and-reliability.md)
   - 23 个 Release E2E 如何映射架构；
   - LT01-LT13 为什么只是 durable runtime 诊断证据；
   - 为什么对象存在和数据库新增不能替代 E2E；
   - 当前 dirty revision 证据边界。

6. [高频追问、取舍与改进方向](06-interview-qa-and-tradeoffs.md)
   - 与 RAG Bot、Workflow、LangGraph 和现代 Agent Harness 的区别；
   - 当前架构优点、缺口和下一步设计；
   - 面试官常见追问参考回答。

7. [Agent 能力轴：理解深度与本项目落地](07-capability-axes.md)
   - 12 条现代 Agent 能力轴的自评矩阵；
   - 每轴的问题本质、常见做法失效点、本项目选择、E2E 证据与边界；
   - 按岗位选三轴深讲的建议与全程口径纪律。

## 权威事实源

- [当前核心架构](../summary/core-architecture-current-state.md)
- [Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md)
- [Durable Investigation Project 当前实现](../summary/durable-investigation-project-current-state.md)
- [未来设计索引](../future/README.md)
- [可信 Agent Runtime 演进与收敛](../future/trusted-agent-runtime-evolution.md)
- [E2E catalog](../../evals/e2e_quality/evidence_catalog.py)

若本目录与上述文档或生产代码冲突，应以生产代码、E2E catalog 和同 revision 的执行证据为准。
