# 它解决了什么问题

### 1. 这个 Agent 面向什么场景？

这是一个面向个人知识管理的 Agent。它帮助用户把零散文本、网页、上传文件和对话结论沉淀为长期知识，并在后续提问时基于这些知识进行检索、推理和回答。

它不是只做一次性聊天，而是围绕“知识从哪里来、怎么存、怎么找、怎么引用、怎么安全删除”形成闭环。

### 2. 用户为什么不用普通 ChatGPT，而要用这个 personal agent？

普通 ChatGPT 更擅长一次性对话，但默认不会稳定维护用户自己的长期知识库，也不一定能把回答依据和本地知识来源清楚绑定。

这个 Agent 的价值在于：

- 用户可以显式 capture 文本、链接、文件和对话结论。
- 知识会进入长期 note/chunk 存储，而不是只留在聊天窗口里。
- 回答时会从长期记忆、图谱和工具结果中组织 evidence。
- 删除等高风险动作有目标解析、确认、幂等和审计边界。
- 同一 thread 的复杂任务可以通过 checkpoint 暂停和恢复。

所以它解决的是“个人知识如何长期沉淀并被可靠使用”的问题，而不只是“让模型回答一句话”。

### 3. 它具体解决了哪些用户痛点？

第一是知识沉淀问题。用户平时输入的文本、网页、文件和多轮对话结论很容易散落在不同聊天里，事后很难找回。这个项目通过 `capture_text / capture_url / capture_upload / solidify_conversation` 把这些内容写入长期知识库。

第二是知识检索和回答问题。用户后续提问时，Agent 不只依赖模型参数记忆，而是从 Postgres note/chunk、Graphiti 语义关系和工具结果中取 evidence，再组织回答，降低凭空回答的风险。

第三是长会话连续性问题。LangGraph checkpoint 保存当前 thread 的 `messages`、计划状态、工具归属、pending confirmation 和事件，使多轮任务、确认暂停和恢复执行有稳定现场。

第四是高风险操作安全问题。删除知识不是用户一句话就直接删，而是经过 planning、retrieve、resolve、HITL confirmation、idempotency key 和工具审计，降低误删和重复执行风险。

第五是 Agent 工程边界问题。项目把模型决策和系统执行拆开：模型可以理解意图、生成草稿和做局部语义判断，但固定流程拓扑来自 `WorkflowSpec`，真正触碰长期存储、外部网络或删除动作前，必须经过 `PolicyEngine`、`StepProjectionValidator`、`ToolGateway`、`ToolGovernance` 和 evidence 边界。

### 4. 它和普通 RAG Bot 的区别是什么？

普通 RAG Bot 通常重点是“上传文档后检索回答”。这个项目更像一个个人知识 Agent，除了 RAG 检索，还包含：

- 长期记忆写入：文本、链接、文件和对话固化都能进入知识库。
- 情景记忆沉淀：每次 entry run 自动记录意图、结果、决策和待办，支持"上次那个任务怎么样了"这类基于历史行为的检索。
- 结构化预处理：Unstructured 会在 capture 中把正文/文档 partition 成 Title、NarrativeText、ListItem、Table 等 typed elements，再通过 `chunk_by_title` 生成 child chunks；chunk 可携带 `title_path / page_number / element_ids / element metadata`。
- 短期执行现场：checkpoint 保存多轮任务和暂停恢复状态。
- 图谱语义索引：Graphiti 提供实体、关系和 episode 检索，但不替代 Postgres 真源。
- 工具治理：工具调用有 schema、gateway、timeout、retry、rate limit、HITL、幂等和审计。
- Workflow / step planning：ask、capture、delete、solidify 本质上都是 workflow；固定拓扑已下沉为 `WorkflowSpec / WorkflowStepSpec / WorkflowRegistry`，其中删除和固化会额外确定性投影成 `ExecutionStep`，用于步骤展示、HITL、checkpoint 和前端步骤面板。
- 高风险恢复：删除知识支持确认、拒绝、resume 和依赖步骤跳过。
- 评测闭环：`evals/` 和 `docs/rag-eval-results.md` 用 Open RAGBench、MultiHopRAG、ask quality、plan/replan 等评测证明策略变化是否真的提升效果。

所以它不是单纯“检索文档回答”，而是围绕个人知识生命周期构建的 Agent。

### 5. 这是一个合格的 Agent 吗？

如果按“个人知识 Agent 原型 / 工程型 Agent”来看，它是合格的。因为它已经具备 Agent 的核心闭环：

- 能识别用户意图。
- 能调用工具完成真实动作。
- 能沉淀和检索长期知识。
- 能基于 evidence 回答。
- 能规划复杂流程。
- 能对高风险操作确认和恢复。
- 能把短期现场和长期事实分开。

但如果按完整生产级 SaaS Agent 来看，它还不能说完全成熟。当前 PolicyEngine 已落地基础规则和可配置覆盖，结构化 ThreadSummary 也已落地并随 checkpoint 持久化，但仍需补齐 workspace/tenant 级权限、审计落库、持久化幂等账本、知识冲突自动检测和专项 eval。

更稳的面试表述是：

> 它已经是一个具备核心闭环的个人知识 Agent：能采集、沉淀、检索、回答、固化和删除知识，并且对工具调用和高风险操作建立了工程边界。它目前更像一个生产化方向明确的 Agent 系统骨架，核心链路、Workflow 规划和基础 PolicyEngine 已经打通，但多租户权限、审计落库、知识冲突治理和专项 eval 还需要继续补齐。

---

[← 返回索引 INDEX.md](INDEX.md)
