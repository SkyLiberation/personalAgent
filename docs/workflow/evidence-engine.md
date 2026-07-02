# Evidence Engine

本文总结当前工程里已经落地的 `EvidenceEngine`。它不是一个新的业务 workflow，而是 ask 和 research 共享的 evidence 应用服务边界。

## 定位

`ask` 和 `research` 的业务目标不同：

- `ask` 是明确问题的 grounded QA，追求低延迟、可恢复和可引用。
- `research` 是开放主题的事件发现、来源聚类、digest synthesis 和 claim verification。

所以二者不合并成一个 workflow。但它们不能各自维护一套证据归一、上下文选择和 claim grounding 逻辑。当前的架构选择是：

```text
AskWorkflow
ResearchWorkflow
  -> EvidenceEngine
       -> SourceDocument / EvidenceItem
       -> ContextPack / Citation
       -> evidence_text_spans / claim grounding
```

业务 workflow 保持分开，底层证据能力由 `EvidenceEngine` 复用。

## 代码边界

核心实现：

```text
src/personal_agent/application/evidence_engine.py
```

关键模型和接口：

```text
EvidenceEngine
EvidenceAssemblyPolicy
EvidenceAssemblyRequest
EvidenceAssemblyResult
EvidenceTrace
EvidenceSpan
EvidenceClaimCheck
ClaimGroundingTrace
```

底层证据模型仍在 kernel：

```text
src/personal_agent/kernel/evidence.py

SourceDocument
EvidenceItem
ContextPack
Citation derivation
evidence_text_spans
source_documents_to_evidence
research_sources_to_source_documents
```

分层原则是：`kernel` 放共享模型和纯转换，`application.evidence_engine` 负责跨 workflow 的证据装配和 claim grounding。这样不会让 ask/research 业务流程反向污染基础模型层。

## 内部结构

`EvidenceEngine` 是 facade，内部职责拆成几个组件：

```text
EvidenceEngine
  -> SourceNormalizer
  -> EvidenceAssembler
  -> ClaimGrounder
  -> CitationSelector
```

外部仍然只调用稳定入口：

```text
sources_to_evidence(...)
research_sources_to_evidence(...)
assemble_context(...)
verify_claims(...)
```

这样既保留了统一 Evidence Engine 边界，又避免把 normalize、assemble、grounding、citation selection 全部堆在一个大函数里。

## 当前职责

`EvidenceEngine` 当前负责四类事情。

### 1. Source Normalization

不同来源先投影到统一来源和证据模型：

```text
SourceDocument
  -> EvidenceItem
```

research 侧也通过同一条语义进入证据层：

```text
ResearchSource
  -> SourceDocument
  -> EvidenceItem
```

这样 web result、research source、note/chunk、graph fact、episode memory 最终都能进入同一套 `EvidenceItem` 语言。

### 2. Context Assembly

ask retrieve 阶段完成多源召回后，不再自己散落执行 dedupe / rerank / selected citation 选择，而是调用：

```text
EvidenceEngine.assemble_context(EvidenceAssemblyRequest)
```

`EvidenceAssemblyRequest` 会携带 `EvidenceAssemblyPolicy`。当前 policy 主要用于表达 task 类型、证据目标、上下文预算、压缩模式、引用模式和校验严格度：

```text
EvidenceAssemblyPolicy
  task_type
  source_preference
  evidence_requirement
  ranking_objective
  diversity_requirement
  freshness_requirement
  max_evidence_items
  max_context_chars
  compression_mode
  citation_mode
  verification_strictness
```

ask 和 research 可以共享同一个 engine，但通过不同 policy 表达不同选择目标。

内部流程是：

```text
evidence_pool
  -> dedupe
  -> RRF fusion
  -> candidate_enricher.enrich(...)
  -> optional sentence-level compression
  -> reranker.rerank(...)
  -> ContextPack
  -> selected_matches
  -> selected_citations
```

输出是 `EvidenceAssemblyResult`，包含更新后的 evidence、matches、citations、`ContextPack`、入选 matches/citations 和 trace。

`EvidenceAssemblyResult.assembly_trace` 是结构化 trace，记录输入证据数、dedupe/fusion/enrichment/compression 后的数量、最终 selected/dropped/citation/context chars 等信息，便于后续 debug 和 eval。

### 3. Claim Grounding

answer verifier 和 research digest verifier 现在都复用：

```text
EvidenceEngine.verify_claims(text, evidence)
```

内部逻辑是：

```text
text
  -> extract_claims
  -> evidence_text_spans
  -> best span alignment
  -> term coverage
  -> entailment judge
  -> EvidenceClaimCheck
```

`EvidenceClaimCheck` 会记录：

- `claim`
- `status`: `supported / partially_supported / unsupported / contradicted / not_found`
- `supporting_evidence_ids`
- `evidence_spans`
- `spans`
- `overlap`
- `coverage`
- `reason`
- `grounding_trace`

其中 `spans` 是一等 `EvidenceSpan` 对象，包含：

```text
EvidenceSpan
  span_id
  evidence_id
  source_id
  source_type
  text
  score
  page_number
  source_span
  metadata
```

这让 claim 可以回溯到具体 evidence span，而不是只知道“某条 citation 支持了它”。

ask 的 `VerificationResult.claim_checks` 和 research 的 `DigestClaim.support_level / source_ids / decision_ids / evidence_spans` 都从这套结果映射。

### 4. Citation / Match Selection

`EvidenceEngine` 根据最终 `ContextPack.evidence` 选择对外展示的 citations 和 matches：

```text
ContextPack.evidence
  -> selected_matches
  -> selected_citations
```

这样模型实际看到的证据和用户最终看到的引用是一致的，避免“prompt 里用了 A，页面上引用 B”的错位。

## Ask 如何接入

ask 的业务 workflow 仍是：

```text
ask-retrieve
  -> ask-compose
  -> ask-verify
  -> ask-repair
```

接入点：

```text
AskService.evidence_engine = EvidenceEngine()
RetrievalStage._assemble_context(...)
  -> EvidenceEngine.assemble_context(...)
AnswerVerifier._grounding_checks(...)
  -> EvidenceEngine.verify_claims(...)
WebRetriever
  -> SourceDocument
  -> EvidenceEngine.sources_to_evidence(...)
```

职责边界：

- `RetrievalCoordinator` 负责问答侧的多源召回控制流。
- `EvidenceEngine` 负责召回之后的证据装配和选择。
- `GenerationStage` 只基于 `ContextPack` 生成答案。
- `VerificationStage` 通过 verifier 间接复用 `EvidenceEngine.verify_claims()`。
- `RepairStage` 负责反证补充或 web fallback，再复用同一个 evidence assembly。

## Research 如何接入

research 的业务 workflow 仍是：

```text
research_prepare_run
  -> research_initialize_state
  -> research_run_loop
  -> research_synthesize_digest
  -> research_verify_digest
  -> research-compose
```

接入点：

```text
ResearchSource
  -> EvidenceEngine.research_sources_to_evidence(...)
  -> EvidenceEngine.verify_claims(...)
  -> DigestClaim support mapping
```

`research_verify_digest` 不再只检查 digest item 是否有 URL，也不单独维护一套 evidence span 匹配逻辑。它读取 item 对应的 `ResearchEvent.sources`，把来源投影成共享 `EvidenceItem`，再用 `EvidenceEngine.verify_claims()` 做 claim-level grounding。

research 仍保留自己的业务状态机：

- `ResearchDecision`
- `ResearchSource`
- `ResearchEvent`
- `EvidenceGap`
- `ResearchSatisfaction`
- `DigestClaim`

这些对象不和 `AskRunContext` 合并，因为 research 的核心是事件发现和 digest synthesis，不是直接回答一个明确问题。

## Non-goals

为了防止 `EvidenceEngine` 变成新的大 workflow，它明确不负责这些事情：

- 不负责判断用户意图是 ask 还是 research。
- 不负责决定 research loop 是否继续。
- 不负责 event clustering。
- 不负责 `ResearchDecision / EvidenceGap / ResearchSatisfaction` 的业务状态推进。
- 不负责工具权限、HITL、幂等和审计。
- 不负责直接生成最终 answer 或 digest 文风。
- 不负责决定什么时候触发 web fallback 或 contrastive repair。

这些仍属于对应 workflow、ToolGateway 或 orchestration 层。

## Eval 维度

EvidenceEngine 抽出来后，可以独立评估两类能力。

### Context Assembly Eval

关注：

- 是否选中 gold evidence。
- `ContextPack` 是否覆盖关键事实。
- citation 是否来自实际进入 prompt 的 evidence。
- 是否引入无关证据。
- 压缩是否丢失关键信息。

可用指标：

```text
Recall@K
MRR
NDCG
citation precision
context relevance
context faithfulness
```

### Claim Grounding Eval

关注：

- `supported / partially_supported / unsupported / contradicted / not_found` 是否判对。
- evidence span alignment 是否准确。
- contradiction recall 是否足够。
- false supported rate 是否可控。

可用指标：

```text
claim support accuracy
contradiction recall
unsupported precision
span F1
false supported rate
```

### Cross-workflow Consistency Eval

同一批 source 同时进入 ask verifier 和 research digest verifier 时，support 判断应该一致。这是抽出 `EvidenceEngine` 的核心收益之一。

## 为什么这样设计

这个设计解决的是“底层证据能力复用”，不是“业务 workflow 合并”。

如果 ask 和 research 各自实现一套证据逻辑，会出现几个问题：

- 相同来源在两边有不同的 canonical 语义。
- ask verifier 和 digest verifier 对 supported / contradicted 的判断不一致。
- rerank / compression / citation selection 难以统一评测。
- debug 时无法判断模型看到的 evidence、verifier 使用的 span、用户看到的 citation 是否一致。

抽出 `EvidenceEngine` 后，边界变成：

```text
Workflow owns control flow.
EvidenceEngine owns evidence mechanics.
```

ask/research 只决定什么时候检索、什么时候生成、什么时候修复、什么时候停止；证据如何归一、选择、压缩、grounding 和对外引用，由 `EvidenceEngine` 负责。

## 面试表述

可以这样说：

> 我没有把 ask 和 research 合并成一个 workflow，因为 ask 是明确问题的 grounded QA，research 是开放主题的事件发现和 digest synthesis，二者状态机不同。但我把底层 Evidence Engine 抽出来了。不同来源会先统一成 SourceDocument / EvidenceItem，再由 EvidenceEngine 做 dedupe、RRF、candidate enrichment、compression、rerank、ContextPack、selected citation/match 和 claim grounding。EvidenceEngine 是 facade，内部拆成 SourceNormalizer、EvidenceAssembler、ClaimGrounder 和 CitationSelector。ask 的 answer verification 和 research 的 digest claim verification 都复用 EvidenceEngine.verify_claims，所以业务 workflow 分开，但证据语义和校验逻辑是一套。
