# Workflow 文档索引

> 顶层文档总入口见 [docs/README.md](../README.md)，当前架构与三条生产主链以
> [personalAgent 当前核心架构](../summary/core-architecture-current-state.md) 为准。

本目录只描述请求如何进入明确 Application Use Case、领域状态机、Tool/Agent Gateway 或后台
worker。它不再维护一个覆盖所有请求的 Entry/Executive/LangGraph 总图。

## 当前运行形态

```text
短动态请求
  -> ConversationService Interaction loop

固定事务
  -> explicit Application Use Case / Domain state machine

动态且必须跨进程、用户轮次或审批恢复
  -> InvestigationProject aggregate + worker
```

三条路径共享“Proposal 不是权限、执行事实不是完成证明”的框架不变量，但各自拥有独立
生命周期和恢复事实。

## 当前链路文档

1. [Capture / Ask 当前流程](capture-ask-model-flow.md)：Capture ingestion、Workspace
   Artifact/Evidence/Claim 与 Ask 多源证据、ContextPack、verify/repair；
2. [Workspace 生命周期](workspace-lifecycle-workflow.md)：Artifact/Evidence 优先入库、
   Claim/Grounding/Admission/Conflict 与 ProjectionJob；
3. [Evidence Engine](evidence-engine.md)：Ask 与 Research 共享的证据归一、装配、引用选择和
   claim grounding；
4. [知识删除/恢复](delete-knowledge-workflow.md)：明确 Application Use Case、确认、单 digest、
   Receipt 和 replay；
5. [一次性研究](research-once-workflow.md)：`ResearchService` 的来源、事件、digest 与领域终态；
6. [GPT Researcher A2A](gpt-researcher-a2a-workflow.md)：child lifecycle、Artifact 与父级综合边界。

Conversation Interaction loop 不在本目录复制，统一见
[Agent 能力轴](../interview/03-capability-axes.md)（轴 1 决策所有权、轴 4 Tool 治理）。Durable Investigation
当前事实见
[Durable Investigation Project 当前实现](../summary/durable-investigation-project-current-state.md)。

## 历史迁移资料

以下文件仍保留旧 `TaskAnalyzer -> GoalGraph -> Executive -> LangGraph` 设计推导，已在文件顶部
标明历史状态，不得作为当前生产事实：

- [Entry 到 Executive Agent Loop](entry-executive-agent-loop.md)；
- [Governed Procedure 与 Step Projection](workflow-framework.md)；
- [MCP Codebase Capability](github-mcp-workflow.md)。

保留它们的唯一用途是解释旧结构为何被删除或迁移。完成调用方和引用清理后，应移动到明确的
历史归档或删除，不能长期与 current 文档并列。

## 当前事实所有权

- Conversation：`ConversationService` / Interaction journal；
- Capture/Ask/Knowledge：对应 Application Service 与 Workspace canonical store；
- Delete/Restore：`KnowledgeLifecycleService` 与 immutable Command/Receipt；
- Research/Subscription/Delivery：`ResearchService`、worker queue 与各自 Store；
- Investigation：`InvestigationProject` aggregate、append-only journal 与 Completion Gate；
- Tool/Agent execution：`ToolGateway` / `AgentGateway`；
- 产品与发布证据：`evidence_catalog.py`、trace archive 与 `release_gate.py`。

Workflow 文档只能引用这些 owner，不能再创建第二套 Task、Plan、Event 或状态表。
