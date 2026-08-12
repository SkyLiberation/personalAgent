# Retrieval 与证据推理

本文是当前 Ask retrieval、证据归一和回答边界的 canonical 文档。它描述 Ask Application 的一个
只读阶段，不定义顶层 Agent Router、Planner、Authorization 或 Completion。

## 生产路径

```text
User question
  -> query understanding
  -> personal knowledge / local / graph retrieval
  -> optional web retrieval under policy
  -> EvidenceItem normalization
  -> Evidence Engine fusion / rerank / budget
  -> ContextPack
  -> unified answer composition
  -> Ask verification
  -> bounded repair or fail closed
```

固定阶段由 Ask workflow 定义。模型只负责开放语义的 query understanding、证据重点、答案组织和
verification；确定性代码负责 visibility、scope、source ref、预算、状态迁移和重试上限。

## Retriever 契约

| Retriever | 输入 | 输出 | 禁止 |
| --- | --- | --- | --- |
| Personal Knowledge | question、scope、filters | EvidenceSpan、Citation、Claim support/conflict | 生成/验证 Personal Knowledge answer |
| Local | question、scope、filters | Note/chunk candidates | 把模型回答写回 Note |
| Graph | question、scope | fact/edge/episode/citation refs | 返回 provider candidate answer |
| Web | question、Policy/egress scope | SourceDocument / EvidenceItem | 绕过 Gateway 或权限 |

所有 source 最终进入同一个 `EvidenceItem` pool。`graph_result_to_evidence()` 是
`GraphRetrievalResult` 的唯一转换入口，Ask 与 `graph_search` Tool 共用；Tool 不再复制一套
fact/edge/hit 映射。

## Graph 边界

`GraphRetrievalResult` 只包含：

- `entity_names`、`relation_facts`；
- `node_refs`、`edge_refs`、`fact_refs`；
- `related_episode_uuids`、`citation_hits`、`citations`；
- `enabled/error` 环境事实。

模型或 Provider 生成的自然语言 answer 不属于该 contract，且 `extra="forbid"` 会拒绝注入。
`relation_facts` 必须是 provider 的 retrieval fact 输出，不能通过拆分 synthesized answer 构造。

生产 `graph_provider` 只接受：

- `graphiti`：在线 graph fact/ref retrieval；
- `structural`：本地 parent/section 结构检索；
- `hybrid`：组合 structural 与 Graphiti。

未知配置在 Settings 加载阶段失败，不会静默回退。Microsoft GraphRAG CLI 的旧 Adapter 已删除，
因为它只返回 synthesized answer，没有本项目要求的 source/citation binding；历史 benchmark
不能证明 grounded retrieval 能力。

## Evidence 与回答

Retriever/Evidence Engine 负责候选归一、去重、融合、rerank、压缩和预算，不负责生成最终答案或判断 Goal 完成。当前产品链只有一个回答 owner：

```text
Conversation
  -> KnowledgeService.select_evidence() -> personal_knowledge_context
  -> optional governed read-only Tool Observations
  -> one FinalMessage
```

`KnowledgeService` 保留 Claim/Evidence/conflict/scope 所有权；Tool success、retrieval hit 或非空 ContextPack 都不能直接完成用户目标。离线 retrieval strategy 只验证候选机制，不是产品入口。

## 失败语义

- Provider 未配置或不可达：返回 typed environment/capability failure；
- metadata filter 排除全部候选：返回空候选并记录过滤事实；
- evidence 不足：compose/verification 明确不足，不用历史回答或 fallback 文本制造结论；
- verifier 发现 unsupported/contradicted claim：在预算内 repair 或返回 limitation；
- source ref 不属于本次 visibility：Admission 拒绝，不能由模型补造。

## 执行证据

- Graph synthesized answer baseline 与删除路径见
  [ADR 0012](../adr/0012-graph-retrieval-evidence-only-boundary.md)；
- Personal Knowledge 内外层重复验证 baseline 与边界见
  [ADR 0011](../adr/0011-independent-personal-knowledge-answer-verification.md)；
- Verification 和 Completion owner 见
  [Verification 与 Completion](verification-and-completion.md)。
