# 从真实请求理解当前架构

面试中不要从包名开始讲。先选一个用户请求，沿正式入口讲到用户结果，再说明每一层为什么存在。

## 1. 请求一：普通直接回答

用户输入：

> SLO 错误预算是什么？

生产路径：

```text
POST /api/conversation/turn
  -> AgentService.converse
  -> AgentRuntime.converse
  -> ConversationService.respond
  -> StructuredModelClient
  -> AgentTurnDecision(decision=FinalMessage)
  -> ConversationTurnView
```

如果模型已有足够信息，可以直接回答。系统不会为了形式统一创建 Task、GoalGraph、Command、Receipt 或 CompletionReport。

对应代码：

- [Web conversation route](../../src/personal_agent/adapters/web/routes/conversation.py)
- [AgentService facade](../../src/personal_agent/orchestration/service.py)
- [AgentRuntime composition root](../../src/personal_agent/orchestration/runtime.py)
- [ConversationService](../../src/personal_agent/application/conversation/service.py)
- [Conversation models](../../src/personal_agent/application/conversation/models.py)

面试表达：

> 直接回答也是一种合法 Agent 决策。Agentic 不等于每次都必须规划和调用工具，能用更短路径满足用户目标时就直接结束。

## 2. 请求二：基于个人知识回答

用户输入：

> 根据我最近保存的笔记总结缓存策略。

一种可能路径：

```text
ConversationService
  -> EffectiveCapabilities 包含 list_recent_notes/get_note/graph_search
  -> 模型提出 list_recent_notes ToolCallProposal
  -> Admission 校验 Tool 和 schema
  -> ToolGateway 执行
  -> ActionObservation(tool_result)
  -> 下一模型轮选择 get_note 或直接总结
  -> FinalMessage
```

这里的关键不是 Tool 名字，而是 Observation 驱动：模型只有收到真实 Tool result 后才能声称读到了笔记。

Runtime 不会根据“笔记”二字硬编码调用 `list_recent_notes`。模型根据 Tool description、schema、当前消息和已有 Observation 作语义选择。

## 3. 请求三：读取 GitHub 或 Notion

用户输入：

> 读取这个 GitHub 仓库 README，并告诉我核心设计。

生产路径：

```text
模型选择 github.get_file_contents
  -> ToolExecutor registry/schema validation
  -> ToolGateway policy/idempotency/audit
  -> MCP Host mapping
  -> GitHub MCP server
  -> typed Tool result
  -> ActionObservation
  -> 父模型组织 FinalMessage
```

MCP Tool 只有同时满足以下条件才进入可见 registry：

1. Host 接受了 Server 配置；
2. 实际 discovery 得到远端 Tool name/schema；
3. 本地 mapping 声明了 exposure、scope、risk、data egress 和 timeout；
4. 当前 Interaction 的 capability visibility 允许模型看到。

“配置存在”不等于“Provider 健康”，“discovery 成功”也不等于“调用成功”。E19 专门验证能力不可用时 `tool_calls=0`，系统返回 limitation，而不是换一个相似 Tool 或用常识编造远端内容。

## 4. 请求四：委托 GPT Researcher

用户输入：

> 深入研究最近 Agent 协议的变化，比较主要方案。

生产路径：

```text
AgentTurnDecision
  -> AgentDelegationProposal
  -> local profile/scope admission
  -> DelegationGrant
  -> AgentGateway.submit
  -> GPT Researcher A2A Adapter
  -> poll/stream/cancel
  -> ChildAgentRunRecord + AgentArtifact
  -> ActionObservation(agent_artifact)
  -> 父模型综合 FinalMessage
```

边界：

- 子 Agent 只接收 bounded sub-goal；
- `AgentGateway` 拥有 child lifecycle 和 Artifact index；
- A2A Adapter 只转换远端协议；
- 远端 `completed` 只是子执行事实，不能自动完成父请求；
- 父 Agent 必须评估 Artifact 并生成最终回答；
- 当前 Interaction 已有同一 Agent 的 Artifact 后，不允许无意义重复委托。

对应代码：[AgentGateway](../../src/personal_agent/agents/gateway.py)。

## 5. 请求五：保存刚才的结论

用户输入：

> 把刚才关于 SLO 的结论保存下来。

### 5.1 产品流程如何运行

当前已验证入口是：

```text
POST /api/workspace/solidify-conversation
  -> WorkspaceService.solidify_conversation
  -> 区分 user messages 与 assistant candidates
  -> 只把用户明确陈述写入 ingestion transaction
  -> assistant candidates 全部拒绝自动固化
  -> Artifact/Evidence/Claim/KnowledgeItem
```

E08 自动断言 Ask 前后 Claim 数不变，显式 solidify 后才写入用户 Claim，assistant candidate 不成为长期事实。

### 5.2 普通 Conversation 当前能否自动进入

不能完整进入。

普通 Conversation 的能力列表来自：

```python
list_tools(exposures={"public_agent"})
```

而 `capture_text` 是 `workflow_activity`。所以保存 Workflow 本身已经实现，但尚未通过 scoped capability、Command preparation 和对话内确认机制接入普通 Conversation。

面试时要主动说明这个边界，不能把“产品 API 可执行”描述成“自然语言 Agent 已能保存”。

## 6. 请求六：删除知识并支持恢复

用户通过产品入口选择一条知识并请求删除。

生产路径：

```text
POST /api/knowledge-delete-commands
  -> KnowledgeLifecycleService.prepare_delete
  -> immutable DeleteCommand
  -> awaiting_confirmation
  -> AuthorizationDigest

POST /api/knowledge-delete-commands/{id}/decision
  -> 校验用户/scope/digest/decision
  -> ExecutionCommandDigest
  -> execute once
  -> DeleteEvent + Receipt
```

关键反事实：

- 跨 scope 查不到目标；
- prepare 后没有执行副作用；
- 错误 digest 返回冲突；
- reject 零副作用；
- 重启后 Command 可恢复；
- replay 返回同一 Receipt，不重复删除；
- restore 创建新的 immutable RestoreCommand，不覆盖原 DeleteCommand。

对应入口：[Knowledge lifecycle routes](../../src/personal_agent/adapters/web/routes/notes.py)。

## 7. 请求七：每天九点研究并投递

用户在订阅页面配置主题、时间和投递目标。

```text
POST /api/research/subscriptions
  -> ResearchService.create_subscription
  -> Subscription definition

POST /api/research/subscriptions/{id}/run-now
  -> ResearchRun
  -> Worker queue

personal-agent worker --queue research
  -> execute ResearchRun
  -> Digest
  -> enqueue Delivery
  -> Delivery sent exactly once

POST /api/research/feedback
  -> Feedback 绑定同一 Run/Subscription
```

ResearchRun 可以在内部调用模型和 Web Search，但状态机是确定性的。`running` 不是成功；必须进入 completed、partial、limitation 或 failure 等明确终态。

对应入口：[Research routes](../../src/personal_agent/adapters/web/routes/research.py)。

## 8. 什么是“Agent 选择固定产品操作”

正确含义是：

```text
模型选择一个粗粒度 Application Capability
  -> Admission 判断是否允许
  -> 固定 Workflow 执行内部步骤
```

而不是：

```text
模型自己选择并重排 Workflow 内部所有 Activity
```

例如未来可以向 Conversation 暴露：

```text
prepare_knowledge_delete
prepare_conversation_solidify
prepare_research_subscription
```

不应该暴露：

```text
research_initialize_state
research_run_loop
research_synthesize_digest
research_verify_digest
```

前者表达用户级能力，后者是内部事务 Activity。模型可以决定“做什么”，不能随意改写“事务如何保证一致性”。

## 9. 当前能力进入方式总表

| 用户目标 | 谁选择路径 | 当前入口 | Conversation 是否已贯通 |
| --- | --- | --- | --- |
| 直接回答 | 模型 | `/api/conversation/turn` | 是 |
| 读取笔记 | 模型选择 public Tool | Conversation | 是 |
| Web Search | 模型选择 public Tool | Conversation | 是 |
| GitHub/Notion MCP | 模型选择 discovered Tool | Conversation | 是 |
| GPT Researcher | 模型选择 Agent profile | Conversation | 是 |
| Workspace Ask | 产品 UI/API | Workspace API | 不是统一 Conversation 路径 |
| 显式保存 | 产品 UI/API | solidify API | 否 |
| 删除/恢复 | 产品 UI/API + 用户确认 | lifecycle API | 否 |
| 创建/修改订阅 | 产品 UI/API | Research API | 否 |
| 定时运行 | Scheduler/Worker | Queue | 不应由每轮对话决定 |

## 10. 为什么不加关键词 Router

禁止写成：

```python
if "保存" in message:
    save()
elif "删除" in message:
    delete()
```

原因：

- “不要保存”包含“保存”；
- “解释如何删除”不是执行删除；
- “研究删除机制”不应该删除数据；
- 目标和 payload 属于开放语义，确定性字符串规则无法证明。

合理做法是由模型产生 typed Application Capability Proposal，再由 Admission、Policy 和领域 Command 决定是否允许执行。
