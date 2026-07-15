# Prompt Engineering 面试口径

### Prompt 如何治理？

高频 prompt 通过 `kernel/prompt_templates/` 注册为 `PromptSpec(name, version, template, output_contract)`，调用方使用 `get_prompt()`。Task Analyzer、Ask、ReAct、Protocol 辅助解析、thread compression 和 Graphiti extraction 都有明确版本与输出契约。

### 结构化模型用在哪里？

Task Analyzer、Executive、Goal Verifier、query planner、evidence rerank 和 workspace 语义裁决使用 `StructuredModelRequest` + Pydantic schema。模型负责语义判断，Runtime 再校验关系图、控制决策、Ledger Patch、scope、副作用和完成条件。

### 为什么不是所有 Prompt 都写进 Registry？

稳定、复用的文案进入 Registry。Executive 和 Goal Verifier 的 prompt 需要动态包含完整 ControlState、Ledger revision、Observation provenance、候选 capability 和预算，因此在领域模块组装，但仍使用 strict schema 并记录 operation/model/latency。

### 如何防止模型越权？

- Task Analyzer 不选择 tool、MCP、A2A、Skill、Macro 或 workflow；
- Executive 只输出强类型 ControlDecision；
- 计划修订只能输出受限 LedgerPatchOperation；
- ReAct 只能调用当前动作 allowlist；
- tool/agent 调用必须通过 Gateway；
- Goal 和 Task 完成由 verifier 独占。

### 模型失败如何处理？

Task Analyzer 失败返回 `analyzer_unavailable` 澄清，不使用关键词 Router。Executive 无模型时使用同一 ControlDecision 契约下的保守 fallback；它不会恢复 intent-to-tool map，也不会遍历工具碰运气。Query planner/reranker 可在各自局部边界降级，不改变顶层控制语义。

### Prompt 改动如何验收？

Task Analyzer 跑 `task_analysis_quality`，Executive/Goal Graph 跑 agentic planning 场景，Ask 跑 RAG/evidence suite，Protocol 辅助 prompt 跑 Protocol 和 E2E case。真实模型 gate 与 deterministic contract gate 分开报告。

### 已删除哪些旧 Prompt？

Router、GoalInterpreter、完整 step planner、Execution Pattern selector 和自由 Replanner prompt 已删除。计划适应现在来自 Observation 驱动的 Executive 决策和受验证 Ledger Patch。
