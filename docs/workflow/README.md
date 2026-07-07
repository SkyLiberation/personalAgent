# Workflow 文档索引

> 顶层文档总入口见 [docs/README.md](../README.md)。

本目录只描述“请求如何被编排和执行”。数据模型、长期知识生命周期和未来规划分别放在 `docs/summary`、`docs/topics`、`docs/future`，避免同一概念在多处重复定义。

## 阅读顺序

1. [Workflow 框架总览](workflow-framework.md)：当前注册的 workflow、LangGraph step execution、HITL/checkpoint、ReAct 子图和运行时边界。
2. [Entry / Checkpoint / 输出整体流程](entry-router-plan-react-output-flow.md)：一次 `entry` 请求如何路由、投影、执行、暂停、恢复并输出。
3. [Workspace 生命周期 Workflow](workspace-lifecycle-workflow.md)：Artifact/Evidence 优先入库、Claim 增强、准入、冲突、ProjectionJob 和 e2e 质量口径。
4. [Capture / Ask 当前流程](capture-ask-model-flow.md)：Capture 入库、Ask 多源证据、WorkspaceRetriever、ContextPack、verify/repair 的真实链路。
5. [Evidence Engine](evidence-engine.md)：Ask 与 Research 共享的证据归一、装配、引用选择和 claim grounding。

## 单 Workflow 文档

- [delete_knowledge](delete-knowledge-workflow.md)：高风险删除的候选召回、目标解析、HITL 确认和幂等执行。
- [solidify_conversation](solidify-conversation-workflow.md)：从 checkpoint 对话生成可入库草稿，并复用 capture 主链路写入。
- [research_once](research-once-workflow.md)：ResearchService 的 evidence-driven loop、来源聚类、个人相关性排序、digest 和 claim verification。
- [github_repository_qa](github-mcp-workflow.md)：GitHub MCP 只读仓库能力的完整入口链路、ReAct 工具选择、ToolGateway 治理和 e2e golden set。

## 当前架构口径

- `WorkflowSpec / WorkflowRegistry` 是固定业务流程真源；LLM 不生成全局拓扑。
- `WorkflowStepProjector` 确定性生成 `ExecutionStep`；`StepProjectionValidator` 校验工具、schema、风险和确认要求。
- 常规业务 intent 进入 `StepExecutionGraph`；`unknown` 和校验失败走 fallback/clarification。
- Workspace 是长期知识生命周期服务边界：Artifact / EvidenceBlock / EvidenceSpan 是摄取成功边界，Claim / Grounding / Admission / Conflict 是后续增强链路，ProjectionJob 负责把知识投影到 UI、Review、Graph 和检索索引。
- Ask 的主链路仍是 `AskService` 四阶段管线；Workspace 作为 `WorkspaceRetriever` 进入统一证据池，并把 `EvidenceRef / evidence_coverage / missing_sections` 暴露给回答质量评估。
- Capture 仍保留 `IngestionPipeline` 的 note/chunk/review/graph sync 能力；Claim/Evidence 生命周期由 Workspace 作为业务状态真源承载。
