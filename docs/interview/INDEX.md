# personalAgent 面试材料索引

本目录只描述截至 2026-07-26 已落地并有代码或 E2E 证据的当前架构，不把未来设计写成当前事实。

面试时先讲一句话：

> personalAgent 是一个面向个人知识管理和持续研究的 Agent 系统。它有两条生产主链：开放式请求进入模型驱动的 Interaction loop，保存、删除、订阅、投递等事务进入确定性 Application Workflow。模型负责理解目标和选择能力，Runtime 负责权限、预算和 Admission，Tool/Agent 产生执行事实，Verifier 与领域状态机分别负责语义验证和完成判断。

最重要的当前边界：普通 Conversation 只加载 `public_agent` 能力；保存、删除、订阅变更等多数写操作仍主要通过专用 API/UI 进入。现有 E2E 分别证明 Conversation loop 和固定产品 Workflow 可执行，但尚未证明所有写流程都能由自然语言对话统一触发。

## 建议阅读顺序

1. [项目介绍与面试讲稿](01-project-story.md)
   - 项目解决什么问题；
   - 30 秒、2 分钟和 5 分钟介绍；
   - 为什么它不是普通聊天机器人或 RAG Demo。

2. [从真实请求理解架构](02-request-walkthroughs.md)
   - 直接回答、查知识、MCP、A2A、保存、删除和周期研究分别怎么运行；
   - 什么是固定产品操作；
   - Agent 当前如何选择能力，以及哪些操作尚不能从 Conversation 进入。

3. [Agent 主循环、Tool 与治理](03-agent-loop-and-governance.md)
   - `AgentTurnDecision`、WorkingPlan、Observation 和 Feedback；
   - ToolGateway、AgentGateway、预算、并发、恢复和 Verifier；
   - 模型与确定性代码的决策所有权。

4. [知识、Research 与 Durable Workflow](04-knowledge-and-workflows.md)
   - Artifact、Evidence、Claim、KnowledgeItem 的关系；
   - Ask/Save 分离；
   - Delete/Restore Command；
   - Research、Subscription、Worker、Digest 和 Delivery。

5. [E2E 与工程可信度](05-e2e-and-reliability.md)
   - 23 个 Release E2E 如何映射架构；
   - 为什么对象存在和数据库新增不能替代 E2E；
   - 当前 dirty revision 证据边界。

6. [高频追问、取舍与改进方向](06-interview-qa-and-tradeoffs.md)
   - 与 RAG Bot、Workflow、LangGraph 和现代 Agent Harness 的区别；
   - 当前架构优点、缺口和下一步设计；
   - 面试官常见追问参考回答。

## 权威事实源

- [当前核心架构](../summary/core-architecture-current-state.md)
- [Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md)
- [未来设计索引](../future/README.md)
- [动态长任务目标设计](../future/durable-investigation-project-design.md)
- [E2E catalog](../../evals/e2e_quality/evidence_catalog.py)

若本目录与上述文档或生产代码冲突，应以生产代码、E2E catalog 和同 revision 的执行证据为准。
