# Workspace 生命周期 Workflow

本文描述当前已经落地的 Workspace 知识生命周期。它不是一个薄 API 层；它负责把长期知识从原始证据推进到可回答、可复习、可审计、可投影的业务状态。

## 一句话结论

Workspace 的成功边界先落在 `Artifact / EvidenceBlock / EvidenceSpan`，然后再进入 `Claim / Grounding / Admission / Conflict` 增强链路。Ask 回答时引用的是可回溯的 `EvidenceRef`，并输出 `evidence_coverage` 与 `missing_sections`，让 e2e 质量能检查“有无证据、证据是否覆盖、缺口在哪里”。

## 生命周期分层

```text
raw input
  -> Artifact
  -> EvidenceBlock
  -> EvidenceSpan
  -> KnowledgeItem(primary_state=evidence_ready, flags=[claims_pending])
  -> ProjectionJob(project_evidence_indexes, project_ui_card)
  -> optional Claim lifecycle
       Claim
       GroundingRun
       ClaimAdmissionDecision
       KnowledgeRelation
       KnowledgeStateEvent
       DecisionCard / KnowledgeGap / ReviewItem
       KnowledgeItem(primary_state=ready | partial_failed)
       ProjectionJob(project_claim_indexes, project_review, project_graph)
```

这个分层把“资料已经可靠保存”与“资料中的长期 claim 已经准入”分开。证据入库成功不要求 Claim 抽取一定成功；Claim 失败、冲突或待确认时，Artifact/Evidence 仍然可以被 Ask 检索和引用。

## 入口能力

### ingest_knowledge

`WorkspaceService.ingest_knowledge()` 是 evidence-first 摄取入口。

```text
text/source
  -> Artifact
  -> ExtractionRun(status=completed | partial)
  -> EvidenceBlock
  -> EvidenceSpan
  -> minimal KnowledgeItem(primary_state=evidence_ready)
  -> ProjectionJob(evidence indexes / UI card)
```

它不抽取 Claim，也不做准入。适合文件、网页、研究事件、用户资料等场景先建立可追溯证据底座。

### enhance_claim_lifecycle

`WorkspaceService.enhance_claim_lifecycle()` 在已有 ingest 结果上继续增强 Claim 生命周期。

```text
EvidenceSpan
  -> extract candidate claims
  -> ground claim to evidence spans
  -> admission policy
  -> relation/conflict judge
  -> state events / decisions / gaps / review items
  -> projection jobs
```

这里的语义不确定性由 LLM/structured judge 处理，例如 potential conflict 的语义裁决；代码只控制状态迁移、副作用、持久化和投影任务。

### ingest_text

`ingest_text()` 当前保留为组合入口：先执行 evidence-first ingest，再执行 Claim 生命周期增强。它用于需要“一次写入并尽快可问答/复习”的路径，但语义上仍然由上面两个阶段组成。

## 状态边界

| 对象 | 职责 | 成功含义 |
| --- | --- | --- |
| `Artifact` | 原始资料锚点 | 来源、正文和元数据已持久化 |
| `EvidenceBlock` | 文档级/段落级证据上下文 | 可回到完整上下文 |
| `EvidenceSpan` | 可引用证据片段 | Ask / Grounding 可精确引用 |
| `Claim` | 可被准入的知识断言 | 仍需 grounding/admission 判断 |
| `KnowledgeItem` | 面向产品的知识卡片 | 可展示当前主状态和 flags |
| `ProjectionJob` | 后台投影任务 | 把知识同步到索引、Review、Graph、UI |

`KnowledgeItem.primary_state` 表达业务状态：

- `evidence_ready`：证据已入库，Claim 仍待增强。
- `ready`：Claim 已准入，可作为稳定知识。
- `partial_failed`：部分 Claim/投影失败，仍保留证据与诊断。

`flags` 用于承载可见诊断，例如 `claims_pending`。

## Ask 接入

Workspace 在 Ask 中有两层接入：

1. `WorkspaceService.answer_with_evidence()` 可以直接基于 Workspace 证据回答，返回 `EvidenceGroundedAnswer`。
2. `WorkspaceRetriever` 把 Workspace EvidenceSpan / Claim / conflict diagnostics 投影为统一 `EvidenceItem / Citation / KnowledgeNote`，进入 AskService 的 retrieve / compose / verify / repair 主链路。

回答侧关键输出：

```text
AnswerCitation
  artifact_id
  evidence_block_id
  evidence_span_id
  evidence_ref

EvidenceGroundedAnswer
  answer
  citations
  verification
    verdict: passed | needs_revision | insufficient_evidence
    conclusion_status: supported | conflicted | insufficient_evidence
    evidence_coverage: complete | partial | sparse | none
    conflicts -> evidence_span_ids
    unsupported_claims
    missing_sections
  answer_claim_count
```

`verification` 由独立 `WorkspaceAnswerVerifier` 写入；回答组装器不能按 selected 数量推导
supported。完整所有权与失败语义见
[Verification 与 Completion](../topics/verification-and-completion.md)。

其中 `evidence_coverage` 不是装饰字段，而是 verifier assessment 的组成部分：

- `complete`：入选证据覆盖当前 Workspace 可用证据。
- `partial`：有证据，但还有未覆盖 block/span。
- `sparse`：只有极少证据支撑，不能当作完整回答。
- `none`：没有匹配证据，必须保守回答。

`missing_sections` 可以指向缺失的 EvidenceBlock，也可以在同一 block 内指向未覆盖
EvidenceSpan，避免“只引用了一个句子却把整段都当覆盖”的问题。冲突 ref 必须属于本次
citations；assessment 不写回长期 Claim/Relation。

## ProjectionJob

ProjectionJob 把知识生命周期和下游读模型解耦。

```text
project_evidence_indexes
project_ui_card
project_claim_indexes
project_review
project_graph
```

Evidence-first ingest 至少产生 evidence indexes 和 UI card 投影。Claim 生命周期增强后再产生 claim indexes、review 和 graph 投影。这样失败可以被计数、重试和审计，而不是隐含在一次同步调用里。

## 与 Capture 的关系

Capture 仍负责原有笔记体系：

- fingerprint 去重
- parent/chunk `KnowledgeNote`
- Unstructured chunk
- review card
- graph sync / worker queue

Workspace 负责知识生命周期：

- Artifact / Evidence
- Claim / Grounding / Admission
- Conflict / Decision / StateEvent
- EvidenceRef / Coverage / MissingSections
- ProjectionJob

二者不是互斥替代关系。Capture 提供笔记与 chunk 资产，Workspace 提供证据和 Claim 生命周期。Ask 通过 EvidenceEngine 把 Workspace、local note、graph、web、episode 等来源统一到同一个 evidence pool。

## e2e_quality 约束

当前 e2e 不只检查“能不能回答”，还检查生命周期是否服务业务：

- evidence block/span 是否生成。
- Claim admission 是否产生。
- citation 是否能回到 artifact/block/span。
- projection job 是否没有失败。
- 无证据问题是否返回 `evidence_coverage=none`。
- 部分覆盖问题是否返回 `partial/sparse` 且产生 `missing_sections`。
- 回答生成不能悄悄新增 active claim。

这让 Workspace 设计不脱离现实业务：如果证据缺口无法被用户或评测看到，就不算真正落地。

## 边界

Workspace 不负责：

- 入口 intent 路由。
- LangGraph checkpoint 和 step 调度。
- Ask 的多源召回策略、最终生成、verify/repair 控制流。
- Research loop 的事件发现和停止条件。
- ToolGateway 的权限、HITL、幂等和审计。

Workspace 负责的是知识对象的生命周期、证据引用、Claim 准入、冲突诊断、状态事件和下游投影任务。
