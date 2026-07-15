# Workflow 文档索引

> 顶层文档总入口见 [docs/README.md](../README.md)。

本目录只描述“请求如何被编排和执行”。数据模型、长期知识生命周期和未来规划分别放在 `docs/summary`、`docs/topics`、`docs/future`，避免同一概念在多处重复定义。

## 阅读顺序

1. [Entry 到 Executive Agent Loop](entry-executive-agent-loop.md)：一次 `entry` 请求如何分析、决策、执行、观察、验证、暂停、恢复并输出。
2. [Procedure 框架总览](workflow-framework.md)：Governed Procedure、LangGraph action execution、HITL/checkpoint、ReAct 子图和运行时边界。
3. [Workspace 生命周期 Workflow](workspace-lifecycle-workflow.md)：Artifact/Evidence 优先入库、Claim 增强、准入、冲突、ProjectionJob 和 e2e 质量口径。
4. [Capture / Ask 当前流程](capture-ask-model-flow.md)：Capture 入库、Ask 多源证据、WorkspaceRetriever、ContextPack、verify/repair 的真实链路。
5. [Evidence Engine](evidence-engine.md)：Ask 与 Research 共享的证据归一、装配、引用选择和 claim grounding。

## 单 Procedure / 能力链路文档

- [delete_knowledge](delete-knowledge-workflow.md)：高风险删除的候选召回、目标解析、HITL 确认和幂等执行。
- [solidify_conversation](solidify-conversation-workflow.md)：从 checkpoint 对话生成可入库草稿，并复用 capture 主链路写入。
- [research_once](research-once-workflow.md)：ResearchService 的 evidence-driven loop、来源聚类、个人相关性排序、digest 和 claim verification。
- [MCP task-domain workflow](github-mcp-workflow.md)：GitHub / Notion MCP 的 capability-first task-domain workflow、Resolver、ToolGateway 治理和 e2e golden set。
- [GPT Researcher A2A](gpt-researcher-a2a-workflow.md)：以动态 Agent capability 委派外部研究，并由主 Agent 验证结果。

## 当前架构口径

- `TaskAnalysis + GoalRelation` 是入口语义事实，`GoalGraphCompiler` 确定性生成 TaskSpec 与初始 Ledger。
- `ExecutiveGraph` 是唯一顶层控制器；它按 Observation 每轮选择一个动作，并可受约束修订推断关系。
- `ProcedureSpec / ProcedureCatalog` 只承载稳定事务，不负责顶层意图路由。
- `ActionExecutionGraph` 执行当前 `BoundedAction` 或 Procedure；局部 ReAct 不能修改任务计划。
- Workspace 是长期知识生命周期服务边界：Artifact / EvidenceBlock / EvidenceSpan 是摄取成功边界，Claim / Grounding / Admission / Conflict 是后续增强链路，ProjectionJob 负责把知识投影到 UI、Review、Graph 和检索索引。
- Ask 的主链路仍是 `AskService` 四阶段管线；Workspace 作为 `WorkspaceRetriever` 进入统一证据池，并把 `EvidenceRef / evidence_coverage / missing_sections` 暴露给回答质量评估。
- Capture 仍保留 `IngestionPipeline` 的 note/chunk/review/graph sync 能力；Claim/Evidence 生命周期由 Workspace 作为业务状态真源承载。
