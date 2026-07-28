# 知识、领域 Workflow 与 Durable Project

## 1. 知识模型为什么不只是 Document + Embedding

系统需要回答三个问题：

1. 原始内容是什么、来自哪里；
2. 回答中的事实由哪段证据支持；
3. 事实被修正、冲突或删除后，生命周期如何演进。

因此当前事实链是：

```text
Source
  -> Artifact
  -> EvidenceBlock / EvidenceSpan
  -> Claim
  -> Relation / KnowledgeItem
  -> Retrieval Index / Graph Projection
```

### Artifact

保存原始或规范化资源，例如上传文件、网页正文、文本和会话。大文本由 Artifact Store 持有，运行状态优先保存引用。

### EvidenceBlock / EvidenceSpan

标识可以支持 Claim 或回答的具体证据范围，解决 citation 和 provenance 问题。

### Claim

结构化、可维护的知识陈述，具有 active、superseded、deleted 等生命周期。Claim 不是模型任意一句输出；必须经过唯一 ingestion/write path。

### KnowledgeItem / Relation

用于产品读取、维护和关联分析。Relation 可以表达冲突、支持或 supersede 等关系。

### Retrieval/Graph Projection

embedding index、Graphiti、MS GraphRAG 是检索投影，不是事实权威源。它们可以从 PostgreSQL canonical facts 重建，投影失败不能覆盖 Claim。

## 2. Fact Owner

| 事实 | Owner / 唯一写入口 |
| --- | --- |
| 原始 Artifact | ArtifactService + Artifact Store |
| Workspace Evidence/Claim | WorkspaceService ingestion transaction |
| Conversation Interaction | ConversationService + Interaction journal |
| Delete/Restore Command/Event/Receipt | KnowledgeLifecycleService + lifecycle store |
| ResearchRun/Digest/Delivery | ResearchService + research store |
| Investigation definition/Plan/SubGoal/Completion | InvestigationProject aggregate + InvestigationProjectService |
| Review feedback | Review feedback use case/store |
| Tool audit/idempotency | ToolGateway + governance store |
| Child Agent lifecycle/Artifact | AgentGateway |

Repository 只持久化 Application/Domain 认可的事实，不能隐式创建业务对象，也不能返回 UI View 作为新的 canonical fact。

## 3. Context 与长期知识的区别

### LLM Context

只表示当前模型调用实际看到的内容，可以被压缩或丢弃。

### Interaction Journal

保存恢复普通 Interaction 所需的 committed inputs、usage 和执行顺序。

### Artifact Store

保存上传、网页、研究产物等大内容。

### Long-term Knowledge

保存跨会话使用的 Artifact、Evidence、Claim 和 lifecycle facts。

### Retrieval Index

用于查找候选内容，不是事实真源。

把这些对象分开，可以避免把模型上下文、恢复快照和长期事实混在一个 God State 中。

## 4. Grounded Ask

典型路径：

```text
workspace_id + question
  -> Visibility filtering
  -> Requirement retrieval
  -> Evidence selection
  -> Answer generation
  -> coverage/grounding verification
  -> answer + citations
```

关键不变量：

- 先按 user/workspace scope 过滤，再做语义检索；
- Citation 必须回到实际 Evidence；
- Ask 是读取行为，不增加 Claim；
- 其他 workspace 的内容不能进入 Context；
- 检索结果为空时不能使用不可见数据补答案。

## 5. Ask 与 Save 为什么分离

模型回答可能包含：

- 对证据的解释；
- 临时推断；
- 不确定假设；
- 为表达完整而生成的背景知识。

如果每次 Ask 都自动写回，会形成“模型输出成为下一轮事实”的污染循环。

所以当前规则是：

```text
Ask
  -> read-only
  -> Claim count unchanged

Explicit Solidify
  -> 用户明确表达保存意图
  -> 只接受 user-authored claim
  -> reject assistant candidates
  -> ingestion transaction
```

这也是 E08 的核心反事实。

## 6. Knowledge correction

用户纠正旧事实时，不直接覆盖历史 Claim：

```text
old Claim(active)
  -> correction
  -> old Claim(superseded)
  -> new Claim(active)
  -> Relation(supersedes/conflicts)
```

这样可以保留：

- 旧事实曾经存在；
- 谁在何时修正；
- 新旧事实的关系；
- 检索时只选择 active 事实；
- 审计和恢复所需历史。

## 7. Delete/Restore Durable Workflow

### 7.1 Prepare

Application 根据明确的 user/scope/note identity 创建 immutable Command：

```text
DeleteCommand
  - command_id
  - user/workspace scope
  - target identity
  - reason
  - command digest
  - lifecycle status
```

prepare 只产生待确认事实，不删除知识。

### 7.2 Confirm/Reject

确认必须绑定正确 digest。错误 digest、错误用户或跨 scope 请求被拒绝。Reject 进入明确终态且零副作用。

### 7.3 Execute

执行产生：

- Workspace KnowledgeStateEvent；
- Receipt。

同一 digest 再次执行时返回已有 Receipt。

### 7.4 Restore

Restore 不是把 DeleteCommand 的 status 改回去，而是创建新的 RestoreCommand，执行后产生 Restore Receipt 与 Workspace 状态事件。原删除 Operation/Receipt 仍保留。

## 8. Review 与 Knowledge Maintenance

### Review

```text
Knowledge facts
  -> Review plan
  -> due ReviewCard
  -> user feedback(remembered/forgotten/...)
  -> feedback fact
  -> schedule projection update
```

Review content、feedback fact 和下一次 schedule projection 分开保存。重启后已经 answered 的卡片不会再次 due；forgotten 可以使其重新进入 due。

### Knowledge Maintenance

系统可以分析：

- 冲突 Claim；
- 缺少 Evidence 的 Claim；
- 孤立事实；
- 需要复核的 KnowledgeItem；
- Graph projection backlink。

维护结果不是新的知识事实写入口。每个 projection 必须能回到 source Claim。

## 9. ResearchRun

一次 ResearchRun 的状态和产物由 ResearchService 拥有：

```text
prepare run
  -> initialize
  -> search/explore/verify loop
  -> synthesize Digest
  -> verify terminal result
  -> completed / partial / limitation / failed
```

模型负责：

- 研究问题的语义分解；
- 查询内容；
- 对搜索 Observation 的判断；
- Digest 内容组织。

确定性代码负责：

- Run identity；
- 状态迁移；
- 搜索和模型预算；
- source URL 要求；
- Worker retry；
- terminal state；
- Delivery exactly-once。

`running` 只是中间状态，不能作为用户成功结果。

## 10. Scheduled Intelligence

事实对象分开：

```text
Subscription Definition
  != ResearchRun
  != Digest
  != Delivery
  != Feedback
```

Subscription 描述周期、主题、限制和投递目标；每次运行创建独立 ResearchRun；Digest 是该 Run 的内容产物；Delivery 是外发执行事实；Feedback 绑定具体 Run/Subscription。

Worker queue 负责：

- 入队；
- 领取；
- retry/dead；
- reconcile；
- 不重新生成已经冻结的业务参数。

## 11. MCP 与 A2A 为什么不成为事实 Owner

MCP、Web Search 和 GPT Researcher 返回的是外部 Observation 或 Artifact，不是 Workspace Claim。

如果用户明确保存，仍需经过 Workspace ingestion/write path。Adapter 不能因为远端结果“看起来可信”就直接写入长期知识。

同理，A2A Artifact 只能支撑父 Agent 综合；它不能替代父级 FinalMessage、Verification 或 Domain Completion。

## 12. ResearchRun 与 Investigation Project 为什么分开

ResearchRun 是固定产品 Workflow：Run identity、搜索阶段、预算、Digest、terminal state 和 Delivery 契约已由 Research 领域定义。模型可以决定查询和内容组织，但不能重写 ResearchRun 的生命周期。

Investigation Project 则用于“路径动态且必须 durable”的长任务。它的 accepted Plan 会驱动 ready set、并行 child join、coverage、steering、审批和 Completion Gate。两者不能合并成一个通用 DurableTask：

```text
ResearchRun
  = 固定领域生命周期 + 内部语义决策

Investigation Project
  = 动态 accepted Plan + durable completion obligation
```

Project 只保存 ArtifactRef；Artifact 正文仍由 ArtifactService 持有。Tool 执行事实仍属于 ToolGateway，child lifecycle 仍属于 AgentGateway，Project 不通过复制这些事实成为第二 owner。

## 13. 持久化边界

| 边界 | 当前实现 | 恢复语义 |
| --- | --- | --- |
| 普通 Interaction | FileInteractionJournal | 从 committed inputs 重建 transient context |
| Workspace/Knowledge | PostgresWorkspaceStore | 从 Artifact/Evidence/Claim 恢复 |
| Delete/Restore | PostgresKnowledgeLifecycleStore | Command/Event/Receipt digest replay |
| Research | PostgresResearchStore + worker queue | Run/Subscription/Delivery lifecycle |
| Investigation Project | PostgresInvestigationProjectStore + investigation queue | 从 definition/append-only journal 重建 Plan、ready set、verification 和 completion |
| Tool governance | PostgresToolGovernanceStore | Policy、idempotency、audit |
| Child Agent | AgentGateway store + trace | child lifecycle 与父结果分离 |
| 大型内容 | Artifact Store | 通过 artifact ref 读取 |

没有一个覆盖所有请求的通用 Task/GoalGraph/RunCheckpoint Aggregate。每种事实按自己的恢复、审计和生命周期需要持久化。
