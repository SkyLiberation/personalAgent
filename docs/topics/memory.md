# Memory 与知识事实边界

本文是当前 Memory 事实、生命周期和读写边界的 canonical 文档。Conversation、Personal Knowledge、
Investigation Project、Artifact 和 Retrieval Index 不共享一个 God Memory；它们按事实 owner
分别持久化，只在 Application Use Case 中通过 typed ref 协作。

## 事实分类

| 事实 | Canonical owner | 生命周期 | 是否可作为回答证据 |
| --- | --- | --- | --- |
| Conversation message / committed observation | Interaction journal | 单次或连续 Conversation | 只能理解指代，不直接证明外部事实 |
| Personal Knowledge Artifact / EvidenceSpan / Claim / Relation | Personal Knowledge Store | 长期知识生命周期 | 经过 visibility 和 retrieval 后可以 |
| 大文本、文件和生成产物 | Artifact Store | 由 ArtifactRef 生命周期管理 | 只有可见且有 source binding 时可以 |
| Investigation definition / plan / journal / artifact | Investigation Project aggregate | durable project | admitted evidence 或 verified artifact 可以 |
| Graphiti node / edge / episode | Graph retrieval projection | 可从 Personal Knowledge/Note 重建 | 只作为 retrieval fact/ref，不是权威写源 |
| Embedding / search index | Retrieval projection | 可失效并重建 | 只能定位 canonical source |
| 当前 LLM Context | Model invocation input | 单次调用 | 不是持久化事实 |

历史 LangGraph checkpoint 表可能仍存在于数据库或运维清理范围，但不再是当前 Conversation、
Personal Knowledge 或 Investigation 的共同事实 owner。

## 唯一写入口

长期知识只能通过明确的 Capture、Personal Knowledge ingest 或 governed Conversation save 进入：

```text
User-authored source
  -> visibility / scope validation
  -> Artifact and EvidenceSpan
  -> semantic extraction proposal
  -> deterministic admission
  -> Claim / Relation transaction
  -> optional graph and embedding projection
```

Conversation save 只允许模型选择用户消息中的逐字 `text_span`。Application 机械校验来源并冻结
Command；用户确认后复用 `KnowledgeService.solidify_conversation()`。模型回答、assistant message、
保存控制语义和检索结果都不能直接写成 Claim。

Knowledge delete/restore 由 `KnowledgeLifecycleService` 的 immutable Command、单一
`command_digest`、Operation 和 Receipt 管理。Graph/index 的删除只是随 canonical 状态变化更新
投影，不能反向删除或覆盖 Personal Knowledge facts。

## 读取与上下文

读取严格按以下阶段执行：

```text
Visibility
  -> Requirement Retrieval
  -> Semantic Selection
  -> Budget Materialization
  -> LLM Context
```

权限和 tenant/personal knowledge/user scope 必须先过滤。检索只产生候选 source/evidence；模型可以在可见
候选中做开放语义选择，但不能扩大 visibility。最终注入 Prompt 的 ContextPack 是临时只读视图，
不写回 Memory。

Conversation 历史只帮助解析追问、用户选择和当前义务。历史 assistant answer 不是事实证据；
如果它与本轮 canonical evidence 冲突，以本轮证据和领域状态为准。

## Graph 与 RAG 的位置

Graphiti 和 embedding search 是 Personal Knowledge/Note 的检索投影：

- Graph capture 返回 `GraphCaptureResult`，记录 episode、entity、edge 和 fact ref；
- Graph retrieve 返回严格的 `GraphRetrievalResult`，不包含 provider candidate answer；
- `graph_result_to_evidence()` 是 Graph retrieval fact 到 `EvidenceItem` 的唯一转换入口；
- provider 只有 synthesized answer、没有 source/citation binding 时，不能进入证据池；
- 当前生产 Graph Provider 只有 `graphiti`、`structural` 和 `hybrid`。

RAG 不拥有隐藏的 Router、Planner 或 Completion：

```text
Ask Application
  -> Retrieval Stage
       -> personal knowledge / local / graph / web candidates
       -> canonical EvidenceItem pool
  -> Compose Stage
  -> Ask Verifier
  -> bounded repair
  -> Ask result
```

Retriever 只返回候选、证据和环境错误。它不生成最终回答、不判断 Goal 完成，也不在内部运行一个
与主 Agent 同构的循环。Personal Knowledge 的独立 `/api/knowledge/ask` 才拥有自己的回答组装和
`KnowledgeAnswerVerifier`；当 Personal Knowledge 作为 Ask 的子能力时，只调用
`KnowledgeService.select_evidence()`，不会生成或验证一个随后被丢弃的内部答案。

## 恢复边界

| 运行形态 | 恢复 owner | 恢复依据 |
| --- | --- | --- |
| Conversation | Interaction journal | committed messages、Observation、Feedback、usage、action order |
| Governed save | Interaction journal + Personal Knowledge | frozen Command、confirmation、Receipt |
| Knowledge lifecycle | Knowledge lifecycle store | Command、Operation、Receipt、Personal Knowledge state events |
| Investigation Project | Project aggregate/journal | definition、accepted plan、step journal、artifact refs |
| Research | Research store + worker queue | ResearchRun、event、delivery/limitation |

恢复只能重放已冻结事实或继续合法状态迁移，不能重新调用模型生成 Command，也不能重复外部副作用。

## 不变量

- 同一业务事实只有一个 owner、canonical model 和写入口；
- State 优先保存 ArtifactRef，不复制大型 Artifact；
- Retrieval Index 可重建，不是事实权威源；
- Conversation context、model output 和 trace 不自动升级为长期知识；
- Graph fact、Receipt、Verifier verdict 和 Completion 各自只证明自己的事实；
- 没有 source binding 的 provider answer 不进入 Evidence；
- 没有实际 E2E 缺口时，不新增统一 Memory Agent、Summary Store 或通用 checkpoint。

Verification 和 Completion 的决策边界见
[Verification 与 Completion](verification-and-completion.md)，当前顶层运行形态见
[核心架构当前状态](../summary/core-architecture-current-state.md)。
