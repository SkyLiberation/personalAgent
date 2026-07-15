# 语义生命周期抽取非兼容改造设计

本文设计 Capture / Workspace 生命周期中“业务证据源如何抽取”的目标态。设计采用 **不考虑兼容性** 的口径：不保留当前规则 Claim 抽取、term-overlap grounding、启发式 coverage 作为主路径；它们只允许作为降级诊断或 fixture baseline。目标是让 LLM / structured judge 处理语义不确定性，代码继续控制流程、状态机、副作用和审计。

## 当前问题

当前 Workspace 生命周期已经形成 Artifact / Evidence / Claim / Admission / ProjectionJob 主链路，但抽取方式仍偏工程启发式：

| 环节 | 当前方式 | 问题 |
| --- | --- | --- |
| EvidenceBlock | 按空行和长度切段 | 对 PDF、网页、表格、标题层级、图片说明的结构理解不足 |
| EvidenceSpan | 按标点切句 | 无法识别同一句中的多个事实、条件、适用范围和例外 |
| Claim 抽取 | `extract_claims()` 按句子切分和过滤 | 把句子当 Claim，缺少主体、谓词、对象、条件、时间、来源角色 |
| Claim 类型 | 关键词规则 | 用户事实、计划、偏好、外部事实、推断的边界容易错 |
| Grounding | Claim 与 span 的词项重叠 | 同义、否定、范围、数量、条件、跨句支撑都容易误判 |
| Coverage | 入选 span/block 数量覆盖 | 不能判断问题的子问题是否被证据完整覆盖 |
| 冲突候选 | 词项重叠 + 极性词 | 只能做候选，不能表达 scope/time/context 下的真实矛盾 |

这些问题的共同点是：它们把开放语义问题压成词项匹配。对 e2e 来说，短 fixture 能过，但真实业务会在复杂资料、长文、表格、隐含条件和跨来源冲突上退化。

## Claim 的价值边界

Claim 的主要来源仍然是 Capture、Solidify、Research 和 Correction。也就是说，Ask 使用的 Claim 不是凭空新增知识，绝大多数都来自已经被 capture 老链路吸收过的文本、chunk、graph 或 evidence。

因此必须承认一个边界：

> 如果 Claim 只是从 capture 文本里再切出一句 `statement + evidence_span_ids`，它对 Ask 召回没有本质增量，只会重复老链路已经吸收的信息。

Claim 不能被设计成“另一种 chunk”。它对 Ask 的价值必须来自老链路没有显式表达的业务状态和语义约束：

| Claim 增量 | 老链路通常没有稳定表达什么 | Ask 如何受益 |
| --- | --- | --- |
| `lifecycle_state` | active / candidate / rejected / superseded / conflicted | 使用前过滤过期、不确定和冲突知识 |
| `support_status` | Claim 是否真的被证据支持 | 避免把弱证据或 unsupported 句子当事实 |
| `scope / condition / valid_time` | 事实适用范围、条件和时间 | 区分“规范 A 开启”和“规范 B 关闭”，不误判冲突 |
| `source_role` | 用户确认、助手推测、外部资料、研究来源 | assistant inference 不自动进入长期事实 |
| `relation` | duplicate / supplement / supersede / conflict | 纠错、更新、冲突提示和多来源归并 |
| `evidence_refs[]` | 多来源证据聚合到同一事实 | 用高密度事实索引反查证据，减少重复上下文 |

所以 Claim 对 Ask 的目标定位不是“新增召回信息”，而是 **语义状态层 / 使用约束层 / 事实归并层**。Evidence 仍然是 Ask 的回答边界；Claim 只有在结构化质量足够高时，才参与排序、过滤、scope disambiguation、多跳扩展和 answer verification。

工程验收也必须遵守这个边界：

- Evidence/EvidenceRef/Coverage 是 Ask 的 P0 提升，Claim 不得成为 evidence-grounded Ask 的同步阻塞条件。
- Capture 不能只保存 note/chunk/evidence 后随便生成 Claim；如果无法生成结构化 Claim，应显式 `claims_pending / semantic_claim_failed`，而不是让低质量 Claim 参与 Ask 决策。
- Ask 不能因为存在 Claim 就绕过 EvidenceEngine，也不能把 Claim statement 当最终证据。
- Claim 必须证明它带来的增量，例如更准确的 scope 判断、冲突处理、supersede 过滤、answer-claim consistency，而不是只证明“多了一条证据链”。

## 目标原则

1. **Evidence 结构由解析器和 LLM 共同形成**：代码负责可定位 block/span，LLM 负责语义单元、标题层级、事实边界和 coverage map。
2. **Claim 是结构化语义对象，不是句子字符串**：Claim 必须包含主体、断言、scope、condition、valid_time、source_role、confidence_reason 和 evidence refs。
3. **Grounding 是语义蕴含判断，不是 overlap 分数**：支持、部分支持、反驳、找不到证据必须由 structured grounding judge 输出。
4. **Admission 永远由代码策略执行**：LLM 可以给建议和理由，但不能直接 active、reject、改状态或写关系。
5. **所有 LLM 输出必须可追溯**：每个 Claim、coverage gap、冲突裁决都必须回链 EvidenceRef、prompt version、model、input hash 和 judge trace。
6. **Claim 不阻塞 Evidence-first Ask**：Artifact / Evidence 可引用就是 capture 的最低成功边界；Claim 只作为增强层参与 Ask。
7. **e2e_quality 是准入门**：新抽取链路必须用 fixture/replay/live 三层 eval 证明优于旧链路，不能只靠对象更漂亮。

## 目标链路

```text
capture text/url/file/research/thread
  -> Artifact
  -> Deterministic Parse
       page / section / paragraph / table / image-caption / code block
  -> EvidenceBlock
  -> Semantic Evidence Segmentation
       LLM structured output
       semantic_span / locator / topic / claim_candidates / omitted_regions
  -> EvidenceSpan
  -> Claim Extraction
       LLM structured CandidateClaim[]
  -> Claim Grounding
       LLM/NLI structured GroundingRun[]
  -> AdmissionPolicy
       deterministic code
  -> Relation Judge
       deterministic candidate retrieval + LLM semantic adjudication
  -> KnowledgeStateEvent / DecisionCard / KnowledgeGap
  -> ProjectionJob
```

最低成功边界仍然是 Artifact / Evidence 可引用。Claim 抽取、grounding、relation judge 可以 partial failed，但不能回滚 Artifact / Evidence。

## 非兼容模型调整

### ExtractionRun

`ExtractionRun` 不再只是记录 evidence block/span id，而要成为抽取任务的审计根。

```text
ExtractionRun
  extraction_run_id
  artifact_id
  extractor_version
  parser_version
  semantic_extractor_version
  model_name
  prompt_version
  input_hash
  status: completed | partial | failed
  coverage_status: complete | partial | sparse | none
  parsed_region_count
  semantic_region_count
  omitted_regions[]
  diagnostics[]
  started_at / completed_at
```

`omitted_regions` 必须能表达“第几页未解析、表格未理解、图片 OCR 缺失、模型跳过某段”等现实缺口。

### CoverageManifest

Coverage 判断不能只依赖 selected EvidenceSpan，也不能只交给 LLM 主观判断。Artifact 解析阶段必须产出 `CoverageManifest`，作为 CoverageJudge 的确定性输入。

```text
CoverageManifest
  artifact_id
  extraction_run_id
  expected_regions[]
    locator
    region_type: page | section | table | image | transcript_turn | attachment
    parse_status: parsed | omitted | partial | failed
    semantic_status: extracted | omitted | partial | failed
    reason
  parsed_region_count
  semantic_region_count
  omitted_region_count
  coverage_status: complete | partial | sparse | none
```

硬规则：

- CoverageJudge 不能隐藏 `omitted_regions`。
- `missing_sections` 必须来自 `CoverageManifest + 问题语义判断`，而不是模型自由编造。
- 如果用户问题命中 omitted/failed region，Ask 必须暴露覆盖不足或请求补充解析。
- `EvidenceSpan` 即使语义上支持答案，也不能覆盖 Artifact 中未解析的相关区域。

### EvidenceBlock

EvidenceBlock 要从段落文本升级为“可定位上下文块”。

```text
EvidenceBlock
  evidence_block_id
  artifact_id
  block_type: section | paragraph | table | list | image_caption | code | transcript_turn
  locator
  title_path[]
  page_number
  char_range
  full_context
  parse_confidence
  extraction_run_id
```

### EvidenceSpan

EvidenceSpan 要表达语义片段，不再等同句子。

```text
EvidenceSpan
  evidence_span_id
  evidence_block_id
  span_type: factual_statement | definition | procedure | constraint | example | table_cell | quote
  text_span
  normalized_meaning
  locator
  quote_hash
  semantic_tags[]
  confidence
  claim_ids[]
```

`normalized_meaning` 是 LLM 对 span 语义的短结构化归纳，只作为检索和 grounding 辅助，不替代原文证据。

### Claim

Claim 改成结构化断言。

```text
Claim
  claim_id
  statement
  subject
  predicate
  object
  qualifiers[]
  scope
  condition
  valid_time
  claim_type
  source_role: user_assertion | source_document | assistant_inference | research_source
  created_from_artifact_id
  evidence_refs[]
  support_status
  lifecycle_state
  confidence
  uncertainty_reason
  canonical_key
```

`statement` 是展示文本；去重、冲突和 grounding 不能只依赖 statement。

### ClaimQualityGate

Claim 进入任何消费方前必须先通过质量门。Admission 只决定 Claim 的知识状态，ProjectionEligibility 决定它能投影到哪里；二者不能混在一起。

```text
ClaimQualityGate
  schema_valid
  has_valid_evidence_ref
  evidence_ref_health
  grounding_confidence
  support_status
  lifecycle_state
  source_role
  critical_missing_scope
  critical_missing_valid_time
  judge_version
  passed: true | false
  blocked_reasons[]
```

最低门槛：

- `schema_valid=true`。
- 至少一个 `EvidenceRef` 可解析，除非是用户当前 turn 的 `user_asserted` 且 thread message 被建模为 EvidenceRef。
- `support_status` 不能是 `unsupported / not_found / contradicted`。
- `critical_missing_scope=false`，除非消费方只需要保守诊断。
- assistant inference 默认不能进入 Ask active context、Review 或 GraphProjection。

质量门失败时，Claim 仍可保留为 candidate/diagnostic，但不能投影给 Ask、Review、Graph、Research impact。

### EvidenceRef Health

EvidenceRef 需要显式健康状态，支持 Delete、Privacy、Correction 和 replay 后的级联治理。

```text
EvidenceRefHealth
  evidence_ref_id
  status: valid | broken | stale | redacted | permission_denied
  reason
  checked_at
```

消费方规则：

- `valid`：可用于 Ask citation、grounding、review、graph backlink。
- `stale`：只能用于历史解释和 supersede 说明，不能作为 active 事实支撑。
- `redacted / permission_denied`：不能进入 prompt、Review 或 GraphProjection。
- `broken`：触发 re-grounding 或 projection invalidation。

## Structured LLM 节点

### 1. Semantic Evidence Segmentation

输入：Artifact parse 后的 block 文本、locator、title path、source metadata。

输出：

```text
SemanticEvidenceExtraction
  spans[]
    text
    span_type
    normalized_meaning
    locator_hint
    semantic_tags[]
    confidence
  omitted_regions[]
  quality_warnings[]
```

职责：

- 判断一个长段里哪些片段可作为证据。
- 保留条件、例外、时间、范围。
- 标记表格、列表、代码、引用中的事实片段。
- 不生成 active Claim。

代码职责：

- 校验 span 必须能定位回 EvidenceBlock。
- 校验 text 必须来自原文或可通过 quote_hash 对齐。
- 失败时保留 deterministic spans，但标记 `semantic_extraction_failed`。

### 2. Candidate Claim Extraction

输入：EvidenceSpan 列表和 Artifact metadata。

输出：

```text
CandidateClaimExtraction
  claims[]
    statement
    subject
    predicate
    object
    qualifiers[]
    scope
    condition
    valid_time
    claim_type
    source_role
    evidence_ref_ids[]
    confidence
    uncertainty_reason
  ignored_spans[]
  warnings[]
```

规则：

- 一个 EvidenceSpan 可以产生 0..N 个 Claim。
- 一个 Claim 可以由多个 EvidenceSpan 支撑。
- assistant inference 默认只能进入 candidate，不能 active。
- user assertion 可以进入 `user_asserted` 支撑状态，但仍要经过 sensitivity/admission。

### 3. Claim Grounding Judge

输入：CandidateClaim + EvidenceRef[]。

输出：

```text
ClaimGroundingJudgment
  support_status: supported | partially_supported | contradicted | unsupported | not_found | user_asserted
  supporting_evidence_refs[]
  contradicting_evidence_refs[]
  missing_evidence_description
  rationale
  confidence
```

判断标准：

- `supported`：证据直接支持 Claim 的主体、关系、范围和条件。
- `partially_supported`：只支持部分范围、缺少条件、缺少时间或数量。
- `contradicted`：证据与 Claim 在同一 scope 下不能同时为真。
- `unsupported`：证据存在但不支持 Claim。
- `not_found`：没有可用证据。

代码职责：

- 只接受 EvidenceRef 指向当前 workspace 可访问证据。
- 低置信结果降级为 `partially_supported` 或 `not_found`，不能强行 active。
- 记录 GroundingRun、ClaimSupportEvent 和 judge trace。

### Judge Calibration

所有 judge 输出都必须带校准信息，不能只用一个通用 confidence。

```text
JudgeResult
  confidence
  calibrated_confidence
  judge_version
  threshold_profile
  rationale
```

不同消费场景使用不同阈值：

| 场景 | 阈值策略 |
| --- | --- |
| Ask hint | 可接受中等置信，但必须保守措辞 |
| Ask final answer | 需要 EvidenceRef + coverage 支持 |
| active admission | 高阈值，且受 AdmissionPolicy 控制 |
| conflict relation | 高阈值，scope/time/condition 必须重叠 |
| supersede relation | 高阈值或用户确认 |
| Review projection | 高阈值，避免强化错误事实 |
| GraphProjection | 结构完整 + EvidenceRef valid |

低校准置信结果只能产生 candidate、gap、decision 或 conservative answer，不能产生不可见副作用。

### 4. Coverage Judge

输入：用户问题、selected EvidenceSpan、available EvidenceSpan、Artifact parse coverage。

输出：

```text
AnswerCoverageJudgment
  evidence_coverage: complete | partial | sparse | none
  covered_questions[]
  missing_questions[]
  missing_sections[]
  confidence
  rationale
```

它解决当前 coverage 只看 span/block 数量的问题。目标是判断“用户问题需要的语义子问题是否被证据覆盖”。

代码职责：

- `none` 和 `sparse` 必须触发保守回答。
- `partial` 必须把 `missing_sections` 暴露给 Answer 和 e2e。
- LLM 不能隐藏 parse omitted regions。

### 5. Relation Judge

保留当前“确定性召回候选 + LLM 裁决”的方向，但扩大结构化输入。

输入：

- 新旧 Claim 的 subject/predicate/object/scope/condition/valid_time。
- 各自 supporting EvidenceRef。
- 当前 relation candidate。

输出：

```text
ClaimRelationAdjudication
  relation_type: duplicate | supplement | supersede | conflict | unrelated | uncertain
  confidence
  rationale
  scope_difference
  requires_decision
```

只有高置信 `conflict / supersede / duplicate` 才允许代码写入最终 relation；其他情况保持 potential relation + DecisionCard。

最终 relation 写入前必须满足：

1. subject/predicate 对齐。
2. scope/condition/valid_time 足够重叠，或 judge 明确说明差异不影响关系。
3. 双方都有有效 EvidenceRef 或明确的 user_asserted thread EvidenceRef。
4. 双方 grounding 不是 `unsupported / not_found`。
5. calibrated confidence 超过 relation 类型阈值。
6. `conflict / supersede` 低于高阈值时只能生成 potential relation + DecisionCard。

## Admission 仍然确定性

LLM 不参与最终准入决策。AdmissionPolicy 的输入可以更丰富，但输出仍由代码策略产生。

```text
Claim + GroundingJudgment + sensitivity + source_role + user_policy
  -> ClaimAdmissionDecision
       allow_active
       keep_candidate
       require_decision
       reject
```

硬规则：

- `unsupported / not_found / contradicted` 不能 active。
- `assistant_inference` 不能无确认 active。
- 高敏感信息必须 `require_decision`。
- `partial_supported` 默认 `keep_candidate`，除非用户明确确认。
- Research 来源不能因为模型自信直接覆盖用户已有 active Claim，必须通过 relation/admission。

## 执行机制变化

### ingest_knowledge

```text
ingest_knowledge
  -> create Artifact
  -> deterministic parse
  -> semantic evidence extraction
  -> save EvidenceBlock / EvidenceSpan
  -> save ExtractionRun
  -> enqueue project_evidence_indexes / project_ui_card
```

如果 semantic extraction 失败：

- 保存 deterministic EvidenceSpan。
- `ExtractionRun.status=partial`。
- `KnowledgeItem.flags += semantic_extraction_failed`。
- 不阻塞 evidence-grounded Ask。

### enhance_claim_lifecycle

```text
enhance_claim_lifecycle
  -> candidate claim extraction
  -> claim grounding judge
  -> admission policy
  -> relation candidate retrieval
  -> relation judge
  -> state events / decisions / gaps
  -> enqueue claim/review/graph projections
```

每个子阶段必须可重试，并以 `ExtractionRun` 或独立 `LifecycleRun` 记录版本。

### answer_with_evidence

```text
answer_with_evidence
  -> retrieve Evidence/Claim candidates
  -> EvidenceEngine assembly
  -> claim state filtering / scope disambiguation if structured claims are available
  -> coverage judge
  -> answer generation
  -> answer claim extraction
  -> answer grounding judge
  -> conservative annotation if needed
```

回答中临时 answer_claim 默认不保存为长期 Claim。用户明确“保存这个结论”时，才转为 CandidateClaim 并重新走 grounding/admission。

Ask 的硬边界：

- 没有结构化 Claim 时，Ask 必须仍能基于 Evidence 回答。
- Claim 只能增强 ContextPack 的排序、过滤、解释和验证，不能替代 EvidenceSpan 原文。
- Claim 检索结果必须带 EvidenceRef；无法回链 Evidence 的 Claim 只能作为诊断或待修复对象。
- 当 Claim 与 Evidence 结论不一致时，以 Evidence + GroundingJudge + AdmissionPolicy 的组合结果为准，不能让旧 Claim statement 压过新证据。

### Ask Claim-aware 使用设计

Ask 侧必须单独设计，不能假设 Capture 产出结构化 Claim 后 Ask 自然变强。

```text
ask-retrieve
  -> QueryUnderstanding
       identify subject / scope / condition / valid_time
       decide claim_sensitive = true/false
  -> RetrievalMode
       evidence_only | claim_aware | hybrid
  -> Evidence retrieval
       Artifact / EvidenceBlock / EvidenceSpan
  -> Claim retrieval
       active / conflicted / superseded / candidate
       only if Claim has valid EvidenceRef
  -> Claim-aware fusion
       filter superseded/rejected
       preserve conflicted/uncertain diagnostics
       expand related evidence via claim.evidence_refs
       scope/time disambiguation
  -> ContextPack
       evidence_context
       claim_state_context
       conflict_context
       coverage_context

ask-compose
  -> answer from EvidenceSpan text
  -> use Claim state as guidance
  -> explicitly mention conflict / missing scope / stale knowledge

ask-verify
  -> extract answer_claim
  -> compare answer_claim with selected Evidence
  -> compare answer_claim with active/conflicted/superseded Claim
  -> mark unsupported / stale / contradicted / scope_missing

ask-repair
  -> retrieve missing Evidence
  -> retrieve related Claim
  -> ask clarification if required scope/time is missing
  -> conservative answer if unresolved
```

Claim 在 Ask 中的允许用途：

- 过滤 `rejected / superseded` 的旧知识。
- 提示 `conflicted / uncertain / require_decision` 状态。
- 将高密度结构化 Claim 反查到 EvidenceRef，减少重复 chunk 上下文。
- 做 scope/time/condition disambiguation。
- 做 answer_claim 与长期知识状态的一致性检查。

Claim 在 Ask 中的禁止用途：

- 不能把 Claim statement 当作唯一证据直接生成最终回答。
- 不能绕过 EvidenceEngine 的 dedupe、rerank、ContextPack 和 citation 选择。
- 不能用低质量或无 EvidenceRef 的 Claim 压过原文 Evidence。
- 不能因为 Claim active 就跳过 coverage judge。
- 不能把 answer_claim 自动保存为长期 active Claim。

### Solidify Conversation

Solidify 不是简单把聊天记录写入 Capture。它要把短期对话转成候选 Claim，但必须区分用户事实、用户意图、助手推断和未确认建议。

目标链路：

```text
solidify_conversation
  -> LLM selects relevant turns
  -> semantic claim extraction
       user_assertion
       user_preference
       user_plan
       assistant_inference
       unresolved_question
  -> grounding to thread_message EvidenceRef
  -> AdmissionPolicy
  -> DecisionCard if confirmation is needed
```

硬边界：

- 用户明确说出的事实可以成为 CandidateClaim，并按 policy 进入 active。
- assistant inference 默认不能 active，即使它语义上合理。
- “我猜 / 可能 / 这意味着”类助手内容必须保留为 candidate/ignored/rejected。
- 如果用户要求“记住这个结论”，也只是允许 answer_claim 转为 candidate，不代表绕过 grounding/admission。

### Research

Research 不能只生成 digest，还要把外部事件映射到用户已有 Claim 的影响。

目标链路：

```text
research_event
  -> Artifact / Evidence
  -> CandidateClaim(source_role=research_source)
  -> GroundingJudge
  -> relation to existing Claim
       supplement
       supersede
       conflict
       irrelevant
  -> AdmissionPolicy / DecisionCard
  -> Ask can see external update impact
```

硬边界：

- Research Claim 默认不能直接覆盖用户 active Claim。
- 外部来源与个人知识冲突时，先形成 relation / gap / decision，而不是静默替换。
- DigestClaim 的支持状态必须能回链 EvidenceRef。
- Ask 使用 Research Claim 时要说明来源角色和置信状态。

### Review / Gap / Maintenance

Review 和 Gap 不应该只按 note 或时间生成，而应按 Claim 状态生成。

```text
review_digest
  -> active high-value Claim
  -> spaced repetition / review card

inspect_knowledge_gaps
  -> partial_supported Claim
  -> potential_conflict / conflicted Claim
  -> stale valid_time
  -> missing EvidenceRef
  -> require_decision Claim

maintain_knowledge
  -> resolve user correction
  -> mark stale / supersede / merge duplicate
  -> trigger re-grounding or re-extraction
```

这类能力消费的是 Claim 的状态和关系，不是 Claim 的文本本身。低质量 Claim 不应进入 Review，以免把错误事实反复强化给用户。

### GraphProjection

GraphProjection 的目标是服务检索、解释和多跳，而不是成为另一个事实真源。

```text
Claim / EvidenceRef
  -> GraphProjection
       entity
       relation
       fact node
       backlink to Claim
       backlink to EvidenceRef
```

硬边界：

- Graph fact 必须回链 Claim 和 EvidenceRef。
- Graph 抽取失败不改变 Claim lifecycle_state。
- Ask 从 graph 命中的事实必须能回到 EvidenceRef，否则只能作为探索线索。
- GraphProjection 可以帮助找 related Claim，但不能单独决定 active/conflict/supersede。

### Correction / Feedback

用户纠错必须回写 Claim/Evidence 状态，而不是只改一条 note 或一段回答。

```text
user correction
  -> identify affected Claim / EvidenceRef
  -> create corrected CandidateClaim
  -> Grounding / user_asserted support
  -> AdmissionPolicy
  -> supersede old Claim
  -> KnowledgeStateEvent
  -> regression/eval candidate
```

反馈类型与动作：

| 用户反馈 | 目标对象 | 动作 |
| --- | --- | --- |
| “不是这个意思” | Claim / EvidenceSpan | mark ambiguous, request clarification, re-extract |
| “这条过期了” | Claim | mark stale / superseded |
| “新说法是...” | Claim | create corrected CandidateClaim, supersede old |
| “引用错了” | EvidenceRef | mark citation quality issue, add eval regression |
| “保存这个结论” | answer_claim | convert to CandidateClaim, run admission |

### Delete / Privacy

Delete 和隐私治理也必须理解 Evidence/Claim 关系。

```text
delete artifact
  -> delete or tombstone EvidenceBlock / EvidenceSpan
  -> affected Claim becomes unsupported / stale / deleted
  -> projections invalidated

delete claim
  -> tombstone Claim
  -> keep Evidence unless user deletes source
  -> graph/review projections invalidated

privacy redaction
  -> redact EvidenceSpan
  -> re-ground affected Claim
  -> block high-sensitivity active state without confirmation
```

硬边界：

- 删除 Claim 不等于删除原始 Evidence。
- 删除 Artifact 会影响所有 EvidenceRef 和依赖 Claim。
- 高敏感 Claim 必须可被查出并撤销投影。

### Procedure / Eval / Replay

语义抽取引入模型漂移后，execution event、artifact 与 Procedure 平台必须能重放和比较。

```text
ExtractionRun / LifecycleRun
  -> prompt_version
  -> model_name
  -> input_hash
  -> output_schema_version
  -> trace artifact
  -> e2e_quality run
```

要求：

- 同一 Artifact 的重抽取必须能比较 Claim semantic diff。
- Prompt/model 升级必须跑 fixture/replay gate。
- e2e report 要能定位退化来自 Evidence segmentation、Claim extraction、Grounding、Relation、Admission 还是 Ask usage。

### Projection Eligibility

不同消费方不能共用同一个“Claim 已准入即可投影”的规则。每种投影必须有独立 eligibility。

| 投影 | 最低准入 |
| --- | --- |
| Ask projection | `valid EvidenceRef`，`lifecycle_state in active/conflicted/uncertain`，通过 ClaimQualityGate；conflicted/uncertain 只能作为诊断或保守上下文 |
| Review projection | `active + supported/user_asserted + valid EvidenceRef + not conflicted + not assistant_inference` |
| GraphProjection | 结构化 subject/predicate/object 完整，EvidenceRef valid，通过 Graph projection quality gate |
| Research impact | 目标 Claim 有 valid_time/source_role，Research Claim grounded，relation judge 达阈值 |
| Correction projection | 新旧 Claim 有 relation/supersede 事件，旧 Claim 不再投影为 active |
| Delete/Privacy invalidation | EvidenceRef health 非 valid 时，相关 Ask/Review/Graph/Search 投影必须失效 |

这能避免一个 Claim 通过 Admission 后自动进入所有能力，造成低质量 Claim 的系统性扩散。

## 分阶段落地

目标态不能一次上线所有 LLM judge。落地顺序必须先证明 Evidence 语义化，再逐步放大 Claim 的消费范围。

### P0：Evidence 语义化，不强推 Claim

```text
Deterministic Parse
CoverageManifest
Semantic Evidence Segmentation
EvidenceSpan quote_hash 对齐
CoverageJudge for Ask
Evidence-only Ask fallback
```

验收目标：

- Artifact / Evidence 可引用。
- semantic span 能对齐原文。
- coverage 能暴露 omitted_regions。
- Ask 可以 Evidence-only 回答，不等待 Claim。

### P1：Claim extraction + grounding，只进入 candidate

```text
CandidateClaimExtraction
ClaimGroundingJudge
ClaimQualityGate
AdmissionPolicy
candidate only by default
```

验收目标：

- 结构化 Claim schema 稳定。
- Claim 均有 EvidenceRef。
- unsupported/partial/assistant inference 不 active。
- Claim 不进入默认 Ask 决策面。

### P2：Claim-aware Ask 小范围启用

只在以下问题类型启用 Claim 增强：

- scope/time/condition 明显的问题。
- 冲突、过期、替代相关问题。
- 用户明确问“这两条是否冲突”。
- Research update 影响旧 Claim。

验收目标：

- `claim_ask_incremental_gain` 达标。
- Evidence citation 仍回链 EvidenceRef。
- Claim 只增强过滤、解释、验证，不替代 Evidence。

### P3：多消费方使用 Claim

Research、Review、GraphProjection、Correction、Delete/Privacy 和 Replay 在 ClaimQualityGate 稳定后再全面消费 Claim。

验收目标：

- projection eligibility 按消费方生效。
- 错误 Claim 不进入 Review/Graph/Research impact。
- 删除/脱敏能级联 invalidation。
- replay diff 可定位退化阶段。

## 代码边界

| 环节 | LLM / judge 负责 | 代码负责 |
| --- | --- | --- |
| Semantic span | 识别语义片段、类型、标签、遗漏 | locator 对齐、quote_hash、保存 EvidenceSpan |
| Claim extraction | 生成结构化候选 Claim | schema 校验、去重候选、写 candidate |
| Grounding | 判断 claim 是否被 evidence 支持 | EvidenceRef 权限、状态写入、低置信降级 |
| Coverage | 判断问题子需求是否覆盖 | 控制保守回答、暴露 missing_sections |
| Relation | 判断重复、补充、替代、冲突 | 只对高置信结果写 relation/state |
| Admission | 可提供解释建议 | 策略、HITL、状态机、副作用、审计 |
| Ask usage | 判断语义意图、scope/time 需求 | retrieval mode、ContextPack、引用、repair |
| Solidify | 选择对话范围、抽取用户事实/助手推断 | 不让 assistant inference active，执行 Admission |
| Research impact | 判断外部事件与已有 Claim 的语义关系 | 不直接覆盖用户 Claim，生成 decision/gap |
| Correction | 解析用户纠错意图 | supersede/state event/projection invalidation |
| Delete/privacy | 无 | 权限、级联影响、tombstone、redaction、projection invalidation |

## e2e_quality 设计

必须新增或强化这些 case：

### E2E-LIFE-SEM-001：复合句 Claim 拆分

输入：一句话同时包含条件、时间和两个事实。

期望：

- 至少生成两个结构化 Claim。
- 每个 Claim 有 subject/predicate/object。
- condition/valid_time 不丢失。
- Claim 都能回链 EvidenceRef。

### E2E-LIFE-SEM-002：同义支撑

输入：Claim 使用“切流量”，Evidence 使用“将请求切换到绿色环境”。

期望：

- Grounding 为 supported 或 partially_supported。
- 不依赖字面重叠。

### E2E-LIFE-SEM-003：范围不完整

输入：Evidence 只说明“服务端规范 A 默认开启”，问题问“Feature X 默认状态”。

期望：

- Coverage 为 partial。
- missing_questions 包含“哪个规范适用”。
- Answer 不给单一默认结论。

### E2E-LIFE-SEM-004：冲突但 scope 不同

输入：

- Claim A：规范 A 默认开启。
- Claim B：规范 B 默认关闭。

期望：

- Relation 不是 conflict，最多 supplement/uncertain。
- Ask 提示不同 scope，而不是判定互相矛盾。

### E2E-LIFE-SEM-005：真实冲突

输入：

- Claim A：同一服务 Feature X 默认开启。
- Claim B：同一服务 Feature X 默认关闭。

期望：

- Relation judge 输出 conflict。
- 代码写 `KnowledgeRelation(conflict)`。
- 两条 Claim 进入 conflicted 或待确认状态。
- Ask 不给单一确定结论。

### E2E-LIFE-SEM-006：表格证据

输入：表格中一行说明服务、字段、默认值。

期望：

- EvidenceBlock block_type=table。
- EvidenceSpan locator 能定位表格行/列。
- Claim 提取包含 subject/predicate/object。

### E2E-LIFE-SEM-007：Answer Claim 不入库

输入：Ask 生成带推理结论的回答。

期望：

- answer_claim 被抽取和 grounding。
- 不产生 active long-term Claim。
- 用户明确保存前不进入长期知识。

### E2E-LIFE-SEM-008：Claim 对 Ask 的增量证明

输入：同一批资料同时可以被老 Evidence 检索召回，但其中包含 scope/time 不同的多个事实。

期望：

- 关闭 Claim 增强时，Ask 至少能引用 Evidence，但只能给保守或并列说明。
- 开启结构化 Claim 后，Ask 能明确使用 scope/time disambiguation。
- 输出说明哪个结论适用于哪个 scope/time。
- citation 仍回链 EvidenceRef，不能只引用 Claim statement。

这个 case 用来防止 Claim 退化成“多存一份句子”。Claim 必须证明它改善了 Ask 的语义使用，而不是只增加 evidence chain。

### E2E-LIFE-SEM-009：真实 solidify 场景

输入：

```text
user: Atlas 项目的部署窗口是每周三上午十点。
assistant: 这可能意味着你们希望避开周末发布，但这个推断需要你确认。
```

期望：

- 用户明确事实进入 CandidateClaim 并可按 policy active。
- assistant 推断只能被标记为 assistant_inference candidate / ignored / rejected，不能 active。
- case 不使用与用户事实明显冲突的生硬推断，避免把 inference guard 和 conflict case 混在一起。
- e2e 断言不只统计 assistant_candidate_count，还要检查没有 assistant_inference active Claim。

### E2E-LIFE-SEM-010：Research 影响已有 Claim

输入：

- 已有用户 Claim：Kappa API rate limit 是每分钟 60 次。
- Research event：官方公告说明 Kappa API rate limit 调整为每分钟 120 次。

期望：

- Research event 生成 Artifact / Evidence / CandidateClaim。
- Research Claim 与旧 Claim 建立 `supersede` 或 `potential_conflict`。
- 旧 Claim 不被静默覆盖。
- Ask 回答时说明外部来源、时间和是否需要用户确认。

### E2E-LIFE-SEM-011：Review 只消费可用 Claim

输入：混合 active、partial_supported、assistant_inference、superseded、conflicted Claim。

期望：

- Review 只选择 active 且有 EvidenceRef 的 Claim。
- conflicted / partial_supported 进入 gap 或 decision。
- assistant_inference 和 superseded 不进入复习卡。

### E2E-LIFE-SEM-012：GraphProjection 回链

输入：一条结构化 Claim，包含 subject/predicate/object 和 EvidenceRef。

期望：

- GraphProjection 生成 entity/relation/fact。
- 每个 graph fact 可回链 Claim。
- 每个 Claim 可回链 EvidenceRef。
- Ask 从 graph 命中时最终 citation 仍解析到 EvidenceRef。

### E2E-LIFE-SEM-013：Correction Supersede

输入：

- 原 Claim：Atlas 部署窗口是周三上午十点。
- 用户纠错：不是周三，是周四上午十点。

期望：

- 新 Claim 进入 CandidateClaim 并按 user_asserted/admission active。
- 旧 Claim 变为 superseded。
- Ask 后续不再把旧 Claim 当 active 使用。
- 状态事件和 relation 可审计。

### E2E-LIFE-SEM-014：Delete / Privacy Cascade

输入：一个 Artifact 产生多个 EvidenceSpan 和 Claim，其中包含高敏感 Claim。

期望：

- 删除 Artifact 后，相关 EvidenceRef 失效。
- 依赖 Evidence 的 Claim 进入 deleted/stale/unsupported 之一。
- Review/Graph/Search projection 被 invalidated。
- 高敏感 Claim 不再进入 Ask context。

### E2E-LIFE-SEM-015：Extraction Replay Diff

输入：同一 Artifact 使用两个 prompt/model version 重抽取。

期望：

- 系统产出 semantic diff：新增 Claim、删除 Claim、scope 改变、support_status 改变。
- 低置信 diff 不自动写 active。
- e2e report 能指出退化发生在 segmentation、claim extraction、grounding、relation 还是 Ask usage。

## 指标

| 指标 | 含义 |
| --- | --- |
| semantic_span_alignment_rate | LLM span 可成功对齐原文 quote_hash 的比例 |
| candidate_claim_schema_valid_rate | Claim 结构化输出通过 schema 的比例 |
| claim_evidence_ref_rate | Claim 拥有有效 EvidenceRef 的比例 |
| grounding_semantic_accuracy | supported/partial/contradicted/not_found 判断准确率 |
| coverage_gap_recall | partial coverage 时缺口被识别的比例 |
| false_active_claim_rate | 不应 active 的 Claim 被 active 的比例 |
| relation_scope_precision | scope 不同的 Claim 不被误判 conflict 的比例 |
| extraction_partial_recovery_rate | semantic extraction 失败后 Artifact/Evidence 仍可问答的比例 |
| claim_ask_incremental_gain | 开启结构化 Claim 后，scope/time/conflict/supersede 类 Ask case 相比 Evidence-only 的质量提升 |
| claim_without_evidence_block_rate | 无有效 EvidenceRef 的 Claim 被阻止参与 Ask 决策的比例 |
| assistant_inference_active_rate | assistant inference 被错误 active 的比例，目标为 0 |
| research_claim_impact_precision | Research Claim 与已有 Claim 的 supplement/supersede/conflict 判断准确率 |
| review_invalid_claim_rate | Review 中出现 rejected/superseded/conflicted/无 EvidenceRef Claim 的比例，目标为 0 |
| graph_projection_backlink_rate | Graph fact 可回链 Claim 和 EvidenceRef 的比例 |
| correction_supersede_success_rate | 用户纠错后旧 Claim 被 supersede 且 Ask 不再使用旧 active Claim 的比例 |
| privacy_projection_invalidation_rate | 删除/脱敏后相关 Ask/Review/Graph/Search 投影失效的比例 |
| extraction_replay_semantic_diff_precision | 重抽取 diff 中真实语义变化的比例 |
| coverage_manifest_gap_recall | omitted/partial/failed region 被 coverage 识别并暴露的比例 |
| relation_write_precision | 写入 final conflict/supersede/duplicate relation 的准确率 |
| judge_calibration_error | judge confidence 与实际正确率的偏差 |
| projection_eligibility_violation_rate | 不满足消费方 eligibility 的 Claim 被投影的比例，目标为 0 |

## 非兼容落地步骤

1. 删除规则 Claim 抽取作为主路径，新增 `SemanticClaimExtractor` structured client。
2. 删除 term-overlap grounding 作为主路径，新增 `ClaimGroundingJudge`。
3. 扩展 EvidenceBlock/EvidenceSpan/Claim schema，强制保存 locator、semantic fields 和 extraction trace。
4. 将 `ingest_text()` 改成只编排 `ingest_knowledge + enhance_claim_lifecycle`，不包含旧规则抽取分支。
5. Ask coverage 改为 CoverageJudge 输出，启发式 coverage 只做 fallback diagnostic。
6. Relation 只允许确定性 duplicate candidate 和 LLM semantic relation adjudication 进入最终 relation。
7. e2e_quality 增加 `life_semantic` 分支，所有新增语义 case 进入 baseline gate。
8. 删除或降级旧 `extract_claims()` 在 Workspace 主链路中的使用；保留给测试 fallback 或 answer 粗粒度诊断时必须标记来源。
9. Ask 中 Claim 默认作为可选增强启用；只有 `claim_ask_incremental_gain` 和关键 semantic e2e 达标后，才能在相关问题类型中提升 Claim 权重。
10. 重写 `E2E-LIFE-005` 类 solidify fixture，使用真实对话场景，并断言 assistant inference 没有 active，而不只统计候选数量。
11. 将 Research、Review、GraphProjection、Correction、Delete/Privacy、Replay 都接入同一套 Claim/Evidence lifecycle eval，避免 Claim 只服务 Ask 或只服务 Capture。
12. 对所有消费方增加 Evidence-only fallback：当 Claim 质量、EvidenceRef 或 schema 不达标时，能力必须降级为 Evidence/Note/Graph 旧链路，而不是使用低质量 Claim。
13. 新增 `CoverageManifest`，CoverageJudge 必须读取 parse/semantic omitted regions。
14. 新增 `ClaimQualityGate`、`EvidenceRefHealth`、`JudgeCalibration` 和 per-consumer `ProjectionEligibility`。
15. Relation 写入 final conflict/supersede/duplicate 前必须通过 relation write gate；否则只生成 potential relation、gap 或 DecisionCard。
16. Replay diff 分两阶段：先做 schema/canonical/support/evidence_ref/status diff，再做完整 semantic diff。

## 风险与约束

- LLM 抽取会引入漂移，因此必须保存 prompt/model/version/input_hash，并支持 replay。
- 结构化抽取失败不能阻塞资料保存。
- 低置信语义判断必须降级为 candidate、partial 或 requires_decision。
- 成本需要通过 block batching、changed-region extraction 和后台增强控制。
- 对用户可见的 Claim 必须能展开到原文 EvidenceRef，不能只展示模型归纳。
- Claim 质量不足时应降级为 Evidence-only Ask。宁可少用 Claim，也不要让低质量 Claim 干扰老 Ask 的成熟检索和 EvidenceEngine 机制。
- 多消费方会放大错误 Claim 的影响。一个低质量 Claim 如果同时进入 Ask、Review、Graph 和 Research impact，会造成系统性污染，因此所有投影必须以 Claim quality gate 和 EvidenceRef backlink 为前置条件。
- LLM judge 链路过长会带来成本、延迟和漂移风险。必须按 P0-P3 分阶段启用，禁止一次性把所有 judge 放进同步主路径。
- Relation / conflict 写入风险高，应优先优化 precision 而不是 detection rate；宁可保留 potential_conflict，也不要误写 final conflict。
- Replay diff 完整语义比较成本高，应先落 schema-level diff 和 critical status diff。

## 最终口径

改造后的系统应这样表述：

> Capture 的确定性部分负责把来源变成可定位 Evidence；LLM structured extractor 负责把 Evidence 中的语义事实、范围、条件和候选 Claim 提出来；Grounding/Coverage/Relation judge 负责处理支撑、覆盖和冲突这些开放语义判断；代码负责 schema 校验、状态机、Admission、HITL、ProjectionJob、持久化和审计。Evidence 是 Ask 和其他能力的最低可靠边界，Claim 是建立在高质量 Capture/Solidify/Research/Correction 抽取之上的语义状态层；如果 Claim 不能表达 scope、time、state、relation 和 EvidenceRef，它就不应被投影给 Ask、Review、Graph 或 Research impact。这样 Workspace 不再依赖词项启发式伪装语义理解，也不会让低质量 Claim 干扰老 Ask 的成熟检索链路或污染其他业务能力。
