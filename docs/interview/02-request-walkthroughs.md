# 从真实请求理解当前架构

面试中不要从包名开始讲。先选一个用户请求，沿正式入口讲到用户结果，再说明每一层**阻止了什么故障**。
写法遵守 [面试文档规范](00-writing-spec.md)；每条路径的深层理念见 [能力轴](03-capability-axes.md)。

八条路径与能力轴的对应关系：

| 路径 | 主要能力轴 |
| --- | --- |
| 1 直接回答 | 轴 1 决策所有权 |
| 2 读个人知识 | 轴 1、轴 3 context |
| 3 MCP 读取 | 轴 4 capability 治理 |
| 4 A2A 委托 | 轴 6 specialist 协作 |
| 5 确认后保存 | 轴 5 HITL、轴 9 记忆污染 |
| 6 删除与恢复 | 轴 5、轴 8 durable state |
| 7 周期研究投递 | 轴 8、轴 10 完成判定 |
| 8 动态长调查 | 轴 8、轴 10 |

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

## 5. 请求五：确认后保存我明确写出的结论

用户输入：

> 请保存结论：SLO 预算需要每周复核。保存前先让我确认。

### 5.1 产品流程如何运行

当前 E14 已验证 Conversation 入口：

```text
POST /api/conversation/turn
  -> 模型选择 prepare_conversation_knowledge_save
  -> 模型逐字选择 user-authored knowledge text_span + source index
  -> Admission 机械证明 span 存在于对应 user message
  -> Runtime 只冻结 exact span 为 immutable Command
  -> awaiting_confirmation + command_digest
  -> Interaction journal

POST /api/conversation/runs/{run}/knowledge-save-decision
  -> principal/workspace/digest 校验
  -> WorkspaceService.solidify_conversation
  -> Artifact/Evidence/Claim/KnowledgeItem
  -> Receipt
```

E14 自动断言确认前 Claim 零增长、重启后 Command 不变、跨 scope 404、confirm 后只新增精确
结论 Claim 且没有“请求保存/先确认”控制语义，Receipt 精确引用该 Claim，replay 返回同一
Receipt 且 Claim 不再增长。E08
继续证明专用 solidify API 不自动保存 assistant candidate。

### 5.2 当前边界

已贯通的是“模型从 user message 逐字选择知识 span、Admission 机械校验、确认后保存精确
结论”。B02 archive `20260729T031804.415533Z-15972-214cb81c` 证明旧整消息冻结会污染 Claim；
E14 archive `20260729T033339.065714Z-22692-16415241` 已闭合该缺口。系统仍不把 assistant
answer 当用户事实自动保存；assistant candidate、冲突核对和其他 governed action 需要各自
baseline，不能从 E14 外推。`capture_text` 仍未向 Conversation 暴露。

## 6. 请求六：删除知识并支持恢复

用户通过产品入口选择一条知识并请求删除。

生产路径：

```text
POST /api/notes/{note_id}/delete-commands
  -> KnowledgeLifecycleService.prepare_delete
  -> immutable DeleteCommand
  -> awaiting_confirmation
  -> command_digest

POST /api/knowledge-delete-commands/{id}/decision
  -> 校验用户/scope/digest/decision
  -> execute once
  -> Workspace state event + DeleteReceipt
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

## 8. 请求八：创建动态长调查

用户通过 Investigation Project 产品入口提交目标、required result contract、scope 和预算。它不是普通 Conversation 自动升级出来的隐藏 Task。

```text
POST /api/investigation-projects
  -> persist immutable Project definition
  -> enqueue investigation worker task
  -> 202 + project_id

investigation worker
  -> rehydrate append-only journal
  -> Planner Proposal
  -> Plan Admission
  -> accepted Plan
  -> deterministic ready set
  -> ToolGateway / durable AgentGateway / synthesis
  -> Evidence Admission
  -> semantic Verification
  -> Completion Gate
  -> final ArtifactRef + CompletionReport
```

这条路径同时满足两个条件：

1. 下一步依赖新 Observation，无法完全预定义；
2. 任务跨越进程、用户轮次、审批或长时间运行边界，需要 durable completion obligation。

`GET /api/investigation-projects/{id}` 只读取 projection，不调用模型或推进状态。steering 只修订未冻结 SubGoal；恢复复用 accepted Plan、稳定 submission key 和已提交执行事实，不重新生成冻结 Command。

当前 LT01-LT13 已覆盖生产 Domain/Application/PostgreSQL/Worker 路径，但 semantic model 和外部 Provider 使用 scripted/frozen Port，因此属于诊断证据，不是 live model/provider release evidence。

对应入口：[Investigation project routes](../../src/personal_agent/adapters/web/routes/investigation_projects.py)。

## 9. 什么是“Agent 选择固定产品操作”

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

例如当前已向 Conversation 暴露：

```text
prepare_conversation_knowledge_save
```

不应该暴露：

```text
research_initialize_state
research_run_loop
research_synthesize_digest
research_verify_digest
```

前者表达用户级能力，后者是内部事务 Activity。模型可以决定“做什么”，不能随意改写“事务如何保证一致性”。

## 10. 当前能力进入方式总表

| 用户目标 | 谁选择路径 | 当前入口 | Conversation 是否已贯通 |
| --- | --- | --- | --- |
| 直接回答 | 模型 | `/api/conversation/turn` | 是 |
| 读取笔记 | 模型选择 public Tool | Conversation | 是 |
| Web Search | 模型选择 public Tool | Conversation | 是 |
| GitHub/Notion MCP | 模型选择 discovered Tool | Conversation | 是 |
| GPT Researcher | 模型选择 Agent profile | Conversation | 是 |
| Workspace Ask | 产品 UI/API | Workspace API | 不是统一 Conversation 路径 |
| 明确 user message 的确认后保存 | 模型选择 Application Capability + 用户确认 | Conversation + Workspace solidify | 是（E14 定向通过） |
| 保存 assistant candidate / 冲突核对后保存 | 未准入 | 无 | 否 |
| 删除/恢复 | 产品 UI/API + 用户确认 | lifecycle API | 否 |
| 创建/修改订阅 | 产品 UI/API | Research API | 否 |
| 定时运行 | Scheduler/Worker | Queue | 不应由每轮对话决定 |
| 动态 durable 调查 | 用户显式创建 Project；模型在 Project 内规划 | Investigation API + Worker | 不会从 Conversation 隐式创建 |

## 11. 为什么不加关键词 Router

禁止写成：

```python
if "保存" in message:
    save()
elif "删除" in message:
    delete()
```

每一行都对应一个真实误触发：「不要保存」包含「保存」；「解释如何删除」不是执行删除；
「研究删除机制」更不该删除数据。目标和 payload 属于开放世界语义，确定性字符串规则不可能证明。

合理做法是模型产生 typed Application Capability Proposal，再由 Admission、Policy 和领域 Command
决定是否允许执行。这一取舍在 [能力轴 1](03-capability-axes.md#1-agent-loop-与决策所有权) 有完整
所有权链说明。
