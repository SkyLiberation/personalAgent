# Personal Knowledge 生命周期 Workflow

本文描述当前已经落地的 Personal Knowledge 知识生命周期。它不是一个薄 API 层；它负责把长期知识从原始证据推进到可回答、可复习、可审计、可投影的业务状态。

## 一句话结论

Personal Knowledge 的成功边界先落在 `Artifact / EvidenceBlock / EvidenceSpan`，然后再进入 `Claim / Grounding / Admission / Conflict` 增强链路。Ask 回答时引用的是可回溯的 `EvidenceRef`，并输出 `evidence_coverage` 与 `missing_sections`，让 e2e 质量能检查“有无证据、证据是否覆盖、缺口在哪里”。

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

`KnowledgeService.ingest_knowledge()` 是 evidence-first 摄取入口。

结构化模型返回的 semantic span 只是提取 Proposal。Application 在保存 `EvidenceSpan` 前会按
`EvidenceBlock.full_context` 校验原文位置；如果模型只返回完整原文句子中的局部片段，则确定性扩展到
包含该片段的最小完整句子，并据此重算 offset、locator 与 quote hash。这样项目名、颜色代号等不透明值不会因
模型只抽出局部主语而从可引用证据中丢失。该规则不改变 Ask 的 Claim-first 门禁：没有可回答 Claim 的 raw
EvidenceSpan 仍不能单独进入答案。

Claim 提取结果同样只是 Proposal。`created_by` 与 `source_type` 是摄取边界产生的 provenance 事实，模型返回的
`source_role` 和 `assistant_inference` 必须与它们一致；`uncertain_claim` 必须携带非空、可审计的
`uncertainty_reason`。任一不变量失败时，本次 semantic claim enhancement 标记为 `partial` 并记录具体错误，
然后使用既有 deterministic source extractor 重建候选；Admission 不接收静默改写过的模型 Proposal。

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

`KnowledgeService.enhance_claim_lifecycle()` 在已有 ingest 结果上继续增强 Claim 生命周期。

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

## Conversation Grounded Answer 接入

**Personal Knowledge 只提供 canonical evidence selection，不再拥有独立最终回答。**

1. 模型在当前目标需要已保存事实时选择只读 `search_personal_knowledge`；
2. `ConversationKnowledgeReadPort.select_personal_evidence()` 按认证 principal 和问题返回 EvidenceSpan、AnswerCitation、selected Claim 与 conflict facts；
3. Conversation 将结果物化为有界 `tool_result`；
4. 模型可结合其他已准入只读工具的 `Observation` 生成唯一 FinalMessage；
5. Ask 前后 Claim/Artifact 写入 delta 必须为零，只有显式 save/solidify 才进入写路径。

产品不存在独立 `/api/knowledge/ask` 或第二个 answer DTO/verifier；Knowledge 与 Conversation 不会同时拥有 answer/citation/completion 语义。Claim support、conflict 与 scope 仍由 Knowledge owner 决定，融合层不能覆盖。

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

Personal Knowledge 负责知识生命周期：

- Artifact / Evidence
- Claim / Grounding / Admission
- Conflict / Decision / StateEvent
- EvidenceRef / Coverage / MissingSections
- ProjectionJob

二者不是互斥替代关系。Capture 提供笔记与 chunk 资产，Personal Knowledge 提供证据和 Claim 生命周期。Ask 通过 EvidenceEngine 把 Personal Knowledge、local note、graph、web、episode 等来源统一到同一个 evidence pool。

## e2e_quality 约束

当前 e2e 不只检查“能不能回答”，还检查生命周期是否服务业务：

- evidence block/span 是否生成。
- Claim admission 是否产生。
- citation 是否能回到 artifact/block/span。
- projection job 是否没有失败。
- 无证据问题是否返回 `evidence_coverage=none`。
- 部分覆盖问题是否返回 `partial/sparse` 且产生 `missing_sections`。
- 回答生成不能悄悄新增 active claim。

这让 Personal Knowledge 设计不脱离现实业务：如果证据缺口无法被用户或评测看到，就不算真正落地。

## 边界

Personal Knowledge 不负责：

- 入口 intent 路由。
- LangGraph checkpoint 和 step 调度。
- Ask 的多源召回策略、最终生成、verify/repair 控制流。
- Research loop 的事件发现和停止条件。
- ToolGateway 的权限、HITL、幂等和审计。

Personal Knowledge 负责的是知识对象的生命周期、证据引用、Claim 准入、冲突诊断、状态事件和下游投影任务。
