# Workflow 文档索引

> 顶层文档总入口见 [docs/README.md](../README.md)。

本目录集中保存流程级文档。`topics/` 目录讲分层设计，`workflow/` 目录讲一次请求或一个业务 workflow 的实际执行链路。

## 总览流程

- [当前 Workflow 框架总览](workflow-framework.md)：说明 `WorkflowSpec / WorkflowRegistry / WorkflowStepProjector / StepExecutionGraph` 的职责边界，以及当前各 intent 的接入方式。
- [Entry / Checkpoint / 输出整体流程](entry-router-plan-react-output-flow.md)：从入口、router、planning、ReAct、checkpoint、HITL、工具、记忆到输出层的端到端链路。
- [Capture / Ask 的 RAG 架构设计](capture-ask-model-flow.md)：capture/index 与 ask/retrieval/generation 的 RAG 流水线。
- [Evidence Engine](evidence-engine.md)：说明 ask 和 research 如何共享 source normalization、context assembly、citation selection 和 claim grounding。

## Step Projection Workflow

这些 workflow 会由 `WorkflowRegistry` 选中，并由 `WorkflowStepProjector` 确定性投影成 `ExecutionStep`，进入 checkpoint-safe 的步骤执行、工具治理和前端步骤面板。

- [ask workflow](workflow-framework.md#ask-step-projection-workflow)：四段式 `ask-retrieve -> ask-compose -> ask-verify -> ask-repair`，把检索、生成、校验、补证修复拆成可观测步骤。
- capture workflow：`capture_text` 是单步 `capture_text` 写入；`capture_link / capture_file` 是“提取正文 -> capture_text 写入”的两步。
- summarize/direct workflow：`summarize_thread` 和 `direct_answer` 也通过 compose step 进入统一步骤执行。
- [delete_knowledge workflow](delete-knowledge-workflow.md)：检索候选、解析目标、HITL 确认、执行删除、生成结果摘要。
- [solidify_conversation workflow](solidify-conversation-workflow.md)：从 checkpoint 对话生成知识草稿，并复用 capture 链路写入长期记忆。
- [research_once workflow](research-once-workflow.md)：从 `ResearchService` 视角说明 evidence-driven research loop 如何收集来源、聚类事件、结合个人知识图谱排序并生成 digest。
- Workflow platform：definition/deployment/eval gate 已持久化到 Postgres，replay/fork/debug bundle 基于 `workflow_events / workflow_artifacts / workflow_replay_runs` 查询。
