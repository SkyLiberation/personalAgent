# Workflow 文档索引

本目录集中保存流程级文档。`topics/` 目录讲分层设计，`workflow/` 目录讲一次请求或一个业务 workflow 的实际执行链路。

## 总览流程

- [Entry / Checkpoint / 输出整体流程](entry-router-plan-react-output-flow.md)：从入口、router、planning、ReAct、checkpoint、HITL、工具、记忆到输出层的端到端链路。
- [Capture / Ask 的 RAG 架构设计](capture-ask-model-flow.md)：capture/index 与 ask/retrieval/generation 的 RAG 流水线。

## Step Projection Workflow

这些 workflow 会由 `WorkflowRegistry` 选中，并由 `DefaultTaskPlanner` 确定性投影成 `PlanStep`，进入 checkpoint-safe 的步骤执行、工具治理和前端计划面板。

- [delete_knowledge workflow](delete-knowledge-workflow.md)：检索候选、解析目标、HITL 确认、执行删除、生成结果摘要。
- [solidify_conversation workflow](solidify-conversation-workflow.md)：从 checkpoint 对话生成知识草稿，并复用 capture 链路写入长期记忆。

## 普通 Branch Workflow

`ask / capture_text / capture_link / capture_file / summarize_thread / direct_answer` 也是 workflow，但当前不投影成 `PlanStep`，而是在 orchestration graph 内走普通分支，通过 `execution_trace` 和事件返回执行路径。
