# Evidence Engine

**EvidenceEngine 是证据机械组件，不是业务 Workflow、Router 或最终回答器。** 它被 Research/Investigation 的验证链消费；Conversation 的 Personal Knowledge read 直接使用 `KnowledgeService.select_evidence()`，最终回答仍由 Conversation 单一拥有。

## 代码边界

| 模块 | 职责 |
| --- | --- |
| `kernel/evidence.py` | `SourceDocument`、`EvidenceItem`、`ContextPack` 与纯转换/选择函数 |
| `application/evidence_engine.py` | source normalization、evidence assembly、compression、claim grounding |
| `application/candidate_fusion.py` | 多检索来源候选融合 |
| `application/rerankers.py` | 显式配置的 component reranker |
| `application/candidate_enrichers.py` | parent/child 候选补全机制 |

分层的判据是生产消费者与不变量，不是为了凑齐 facade。`EvidenceEngine` 不保存 canonical business facts；输入和输出都是可重建的运行投影。

## 核心流程

```text
SourceDocument / EvidenceItem
  -> SourceNormalizer
  -> EvidenceAssembler
       -> dedupe / candidate fusion
       -> optional enrichment / rerank
       -> budgeted ContextPack
  -> ClaimGrounder.verify_claims
  -> typed EvidenceClaimCheck
```

### Source normalization

不同 Provider 必须保留 `source_id/source_ref/canonical_url/title/snippet/provider`。只有 synthesized answer、没有 source/citation binding 的结果不能进入 evidence pool。

### Assembly

`EvidenceAssemblyRequest` 显式携带 question、候选、预算、policy 和 caller 提供的 reranker/enricher。结果包含 selected/dropped evidence、ContextPack 与 trace；非空 ContextPack 只说明材料被选择，不证明 Goal 完成。

### Claim grounding

`verify_claims()` 把候选文本拆为 claim，并返回 `supported/partially_supported/unsupported/contradicted`、supporting evidence ids 与 spans。模型 Judge 只能判断语义蕴含；evidence id、scope 与引用集合由确定性代码约束。

## 生产消费者

- Research digest verification：把 `ResearchSource` 投影为 `EvidenceItem`，验证每个 digest claim 与 source binding；
- Investigation/Conversation review verifier：对冻结的候选文本和 admitted evidence 做 claim-level grounding；
- 其他明确 Application：只有在 baseline 证明需要同一证据机械语义时才通过 Port 复用。

Personal Knowledge 的 Claim/Evidence/conflict/scope 仍由 `KnowledgeService` 拥有。Conversation 将其选择结果物化为 `personal_knowledge_context`，而不是先运行一个子 RAG answer service。

## Non-goals

- 不判断用户 intent、Application Capability 或是否需要 research；
- 不拥有 Artifact、Claim、ResearchEvent 或 Project 生命周期；
- 不生成 FinalMessage，不决定 Completion；
- 不根据 benchmark 名称硬编码策略；
- 不持久化 ContextPack 或可从 canonical facts 重建的候选状态。

## 验证

- Unit：normalization、fusion、budget、citation selection、claim grounding；
- Offline eval：retrieval/rerank/evidence selection 的分布性质量；
- Product E2E：由实际 Application 正式入口验证最终用户结果，不能由 component score 代替。
