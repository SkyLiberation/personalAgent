# Capture / Ask 生命周期主链路目标设计

本文基于 `ChatGPT-知识管理Agent框架优化.md` 的评估继续设计，但明确采用 **不考虑兼容性** 的目标态：不再以 `KnowledgeNote / chunk` 作为事实主链路，也不再把 Workspace 作为 best-effort side-write。目标是把 capture / ask 从“能用的过渡 RAG 链路”升级为“以 Artifact / Evidence / Claim / KnowledgeState 为核心的知识生命周期 Agent”。

## 对评估的判断

这份评估总体合理，尤其准确指出了当前工程的两个事实：

1. 当前 `capture_*` 和 `ask` 作为 step projection workflow 是合理的。
2. 当前最大架构风险是双轨知识源：`KnowledgeNote / chunk` 是主链路，Workspace 的 `Claim / EvidenceSpan / KnowledgeRelation` 是增强侧写。

但评估里部分建议仍偏迁移期，不适合作为不兼容目标态。

## 采纳的合理部分

### 1. 固定 Workflow 拓扑仍然保留

Capture 和 Ask 都是高频、稳定、可产品化的业务流程，不应该每次交给 LLM 临时规划完整步骤。

目标态继续保留固定 WorkflowSpec：

```text
ingest_knowledge:
  create_artifact
  -> parse_artifact
  -> generate_evidence
  -> materialize_minimal_knowledge_item
  -> enqueue_projection_jobs

enhance_claim_lifecycle:
  extract_candidate_claims
  -> ground_claims
  -> admit_claims
  -> update_knowledge_item_projection
  -> enqueue_projection_jobs

answer_with_evidence:
  understand_question
  -> retrieve_evidence
  -> compose_answer
  -> verify_answer_claims
  -> repair_or_decline
  -> finalize_answer
```

LLM 可以参与语义判断，但不能发明主流程、跳过准入或直接执行副作用。

`ingest_knowledge` 的最低成功标准是 Artifact / Evidence 可用，而不是同步完成所有 Claim 抽取。Claim 生命周期应作为同一主模型下的可恢复增强链路执行，避免长文件、复杂网页或模型故障阻塞资料保存和证据问答。

### 2. Capture 的统一入口是对的

文本、链接、文件、对话片段和 Research source 都应进入同一条 ingest 主链路。区别只在 Artifact 的 `source_type`、解析器和证据 locator，不应存在多套长期知识写入逻辑。

目标态统一入口：

```text
User text / URL / file / thread excerpt / research source
  -> Artifact
  -> ParsedDocument
  -> EvidenceBlock / EvidenceSpan
  -> KnowledgeItem projection
  -> optional CandidateClaim / GroundingRun / ClaimAdmissionDecision
```

也就是说，Artifact / Evidence 是 ingest 的同步主链路；CandidateClaim / Grounding / Admission 是长期记忆增强链路，必须可重试、可跳过、可部分失败。

### 3. 文件结构不能被过早拍平

评估指出文件 ingest 的结构损失风险是合理的。目标态中，文件不再走 `inspect_artifact -> text -> capture_text` 这种文本化主链路，而是保留原生结构。

必须贯穿的 locator：

```text
artifact_id
page_number
section_path
element_id
bbox
table_id
cell_ref
source_span
quote_hash
```

文本只是 Evidence 的一种展示形式，不是文件知识的唯一形态。

### 4. Ask 的 retrieve / compose / verify / repair 分层是对的

评估认为 `ask-retrieve -> ask-compose -> ask-verify -> ask-repair` 合理，这一点继续采纳。

目标态强化边界：

- retrieve 只产出 EvidenceRef / ClaimRef / ContextPack。
- compose 只消费 ContextPack，不做隐藏检索。
- verify 必须升级为 answer_claim 级别。
- repair 只能补证据、重新生成、拒答或请求澄清，不能绕过 verifier。

### 5. AskRunContext 作为 durable artifact 是对的

大对象不应塞进 LangGraph checkpoint。目标态继续把检索池、ContextPack、answer claim verification、repair trace 存成 durable artifact。

Checkpoint 只保留：

```text
workflow_run_id
current_step
step_status
artifact refs
decision refs
summary result
```

大对象存储：

```text
IngestRunContext
AskRunContext
GroundingRun payload
VerificationRun payload
RepairTrace
```

### 6. EvidenceRef 是必要抽象

评估建议统一 `EvidenceRef`，这是目标态的关键。

目标态不允许 citation 只保存 snippet 或 note_id。所有回答引用都必须能解析到稳定证据：

```text
EvidenceRef
  source_kind: evidence_span | claim | artifact_block | web_snapshot | thread_message | research_source
  source_id
  artifact_id
  evidence_block_id
  evidence_span_id
  locator
  quote_hash
  extracted_at
  extraction_run_id
```

`EvidenceRef` 的原则是：所有 citation 必须解析到不可变或可版本化的证据快照。URL、Research source 和 Thread summary 本身都不是稳定 Evidence；只有 `web_snapshot / research_snapshot / thread_message` 加上 extracted span、locator 和 quote_hash，才可以作为回答引用。

## 不采纳或需要改写的部分

### 1. 不再把 Workspace side-write 做成目标方案

评估建议把 best-effort side-write 改为可恢复 outbox。这个建议在迁移期合理，但在不兼容目标态中不作为主方案。

目标态不是：

```text
IngestionPipeline 写 KnowledgeNote / chunk
  -> outbox
  -> Workspace side-write
```

而是：

```text
Artifact / Evidence / Claim 主链路成功
  -> KnowledgeItem projection
  -> retrieval index projection
  -> graph projection
  -> review projection
```

Outbox 仍可用于异步投影和重试，但它不再负责“把旧主链路同步到新主链路”。主链路只有一条。

### 2. 不再把 parent note + child chunk 当成过渡核心

`parent note + child chunk` 对当前工程合理，但目标态中它只是 UI 或索引投影，不是知识真源。

替代关系：

| 当前对象 | 目标态替代 |
| --- | --- |
| parent KnowledgeNote | KnowledgeItem projection |
| child chunk KnowledgeNote | EvidenceBlock / EvidenceSpan |
| note version status | Claim KnowledgeState |
| note related ids | KnowledgeRelation |
| note citation snippet | EvidenceRef |

### 3. 不再允许 Answer 只做 answer-level verify

目标态必须做 answer_claim 级诊断。整段答案通过或失败的粒度太粗，无法支撑纠错、保存结论、repair 和 eval。

目标输出：

```text
AnswerVerificationReport
  answer_claims:
    - claim_text
      support_status
      supporting_evidence_refs
      contradicting_evidence_refs
      confidence
      failure_reason
      repair_action
  overall_status
```

### 4. 不把 Graph 当第二事实源

GraphProjection 只服务检索、关系解释和冲突发现。图谱 fact 必须回链 Evidence / Claim，不能成为不可追溯事实源。

## 目标架构

### 1. Ingest 主链路

```text
ingest_knowledge
  -> create_artifact
  -> parse_artifact
  -> generate_evidence
  -> materialize_minimal_knowledge_item
  -> enqueue_projection_jobs

enhance_claim_lifecycle
  -> extract_candidate_claims
  -> ground_claims
  -> admit_claims
  -> update_knowledge_item_projection
  -> enqueue_projection_jobs
```

`ingest_knowledge` 和 `enhance_claim_lifecycle` 都属于同一个知识生命周期主模型，但执行要求不同：

| 链路 | 最低成功标准 | 失败影响 |
| --- | --- | --- |
| `ingest_knowledge` | Artifact / Evidence 可创建并可引用 | 保存失败或证据不可用 |
| `enhance_claim_lifecycle` | CandidateClaim 可抽取、grounding 可判断、admission 可记录 | 不阻塞资料保存和 evidence-grounded Ask |

因此 Claim 抽取失败不应导致 Artifact / Evidence 入库失败；Ask 也不应为了回答刚保存的资料而等待全部 Claim active。

`enqueue_projection_jobs` 可以在 workflow 中触发，但不属于主事务成功条件。`ingest_knowledge` 成功只要求 Artifact / EvidenceSpan 可创建、可解析；索引、图谱、复习和 UI 投影失败只能生成 `ProjectionJob.failed / retrying`，不能把已经成功的 Artifact / Evidence 回滚。

#### create_artifact

负责保存来源和原始输入，不做语义判断。

```text
Artifact
  artifact_id
  source_type
  source_ref
  raw_location
  content_hash
  received_at
  owner_id
  workspace_id
  sensitivity_level
```

#### parse_artifact

负责把原始输入解析成结构化文档。

```text
ParsedDocument
  artifact_id
  parser_name
  parser_version
  language
  title
  elements[]
```

每个 element 必须带 locator：

```text
DocumentElement
  element_id
  element_type
  text
  page_number
  section_path
  bbox
  table_cell_ref
  source_span
```

#### generate_evidence

负责从 ParsedDocument 生成可引用证据。

```text
EvidenceBlock
  evidence_block_id
  artifact_id
  locator
  full_context
  element_ids
  extraction_run_id

EvidenceSpan
  evidence_span_id
  evidence_block_id
  start_offset
  end_offset
  text_span
  quote_hash
```

EvidenceBlock 用于上下文，EvidenceSpan 用于 citation 和 grounding。

#### extract_candidate_claims

这是语义不确定环节，应由 LLM 或 NLI/IE 模型处理，并输出严格结构。

```text
CandidateClaim
  claim_id
  claim_text
  claim_type
  subject
  predicate
  object
  qualifiers
  source_attribution
  evidence_span_ids
  canonical_key
  extraction_run_id
```

LLM 只能产生候选 Claim，不能直接写 active。

目标态建议把 `CandidateClaim` 与长期 `Claim` 建模为同一张 `claims` 表的不同生命周期状态，而不是分成两套事实对象：

```text
Claim
  claim_id
  claim_text
  claim_type
  lifecycle_state: candidate | grounded | verified | active | rejected
  support_status
  admission_status
  subject / predicate / object / qualifiers
  source_attribution
  evidence_span_ids
  canonical_key
  extraction_run_id
```

理由：

- `answer_claim` 转入长期候选时可以生成 `lifecycle_state=candidate` 的 Claim。
- CandidateClaim、GroundedClaim、VerifiedClaim 和 ActiveClaim 是同一对象的状态演进，便于审计和回放。
- 候选噪音通过 `lifecycle_state`、`admission_status` 和索引过滤控制，不进入 active 检索面。
- 避免 `candidate_claims -> claims` 分表转换带来的 ID 映射、citation 回链和 eval 归因复杂度。

#### ground_claims

负责判断 Claim 与 Evidence 的支撑关系。

```text
GroundingRun
  grounding_run_id
  claim_id
  evidence_span_ids
  judge_type
  judge_version
  support_status
  confidence
  rationale
```

`support_status` 只描述证据关系：

```text
supported
partially_supported
unsupported
contradicted
user_asserted
```

#### admit_claims

负责长期记忆准入，是进入 active 的唯一入口。

```text
ClaimAdmissionDecision
  decision_id
  claim_id
  admission_result
  reason
  required_action
  policy_version
```

准入结果：

```text
allow_active
keep_candidate
require_user_decision
reject
```

非法状态转移必须由代码阻断：

| 禁止转移 | 原因 |
| --- | --- |
| unsupported -> active | 证据不足 |
| contradicted -> active | 已被反证 |
| assistant_inference -> active | 助手推断不能直接成为用户事实 |
| user_denied -> active | 用户拒绝后不能被后台恢复 |

#### materialize_knowledge_item

KnowledgeItem 只是用户可见聚合，不是事实源。

```text
KnowledgeItem
  knowledge_item_id
  title
  summary
  claim_ids
  primary_evidence_refs
  state_projection
```

KnowledgeItem 不应等所有 Claim admission 完成后才出现。用户保存资料后应先生成最小投影，再随着 Evidence / Claim / Admission 更新状态。

`state_projection` 不应设计成只能表达一个状态的单一枚举，因为 Evidence 已经可问答、Claim 仍在后台处理、索引投影还未完成这些情况可能同时成立。推荐使用主状态加 flags：

```text
KnowledgeItem.state_projection:
  primary_state: indexing | evidence_ready | ready | partial_failed
  flags:
    - claims_pending
    - index_projection_pending
    - graph_projection_pending
    - review_projection_pending
```

状态含义：

| 状态 | 含义 |
| --- | --- |
| `indexing` | Artifact 已创建，解析或证据生成仍在进行 |
| `evidence_ready` | EvidenceSpan 可引用，Ask 可以基于证据回答 |
| `ready` | Evidence、Claim projection 和索引投影均完成 |
| `partial_failed` | 主证据可用，但部分增强链路失败，可重试或解释 |

Flags 含义：

| Flag | 含义 |
| --- | --- |
| `claims_pending` | Claim 抽取、grounding 或 admission 仍在后台进行 |
| `index_projection_pending` | 检索索引投影未完成或等待重试 |
| `graph_projection_pending` | 图谱投影未完成或等待重试 |
| `review_projection_pending` | 复习计划投影未完成或等待重试 |

### 2. Ask 主链路

```text
answer_with_evidence
  -> understand_question
  -> retrieve_evidence
  -> compose_answer
  -> verify_answer_claims
  -> repair_or_decline
  -> finalize_answer
```

#### understand_question

LLM 处理语义意图，输出检索计划。

```text
QueryUnderstanding
  rewritten_query
  required_sources
  freshness_requirement
  target_artifact_ids
  target_claim_types
  needs_personal_memory
  needs_external_web
  ambiguity
```

如果问题需要澄清，workflow 可以中断并生成 DecisionCard，而不是强行检索。

#### retrieve_evidence

召回对象是 Evidence / Claim，而不是 note/chunk。

```text
retrievers:
  evidence_span_retriever
  claim_retriever
  artifact_structure_retriever
  graph_projection_retriever
  thread_message_retriever
  web_snapshot_retriever
```

所有来源归一为：

```text
EvidenceCandidate
  evidence_ref
  text
  source_kind
  score
  retrieval_reason
  relation_to_question
  claim_refs
  conflict_markers
```

#### compose_answer

生成阶段只消费 ContextPack。

```text
ContextPack
  selected_evidence_candidates
  selected_claim_refs
  conflict_notes
  missing_evidence_notes
  evidence_coverage: complete | partial | sparse | none
  missing_sections:
    - page_range
    - section_path
    - element_type
  budget_summary
```

回答必须逐关键结论绑定 citation。没有证据时必须保守回答或请求补充资料。

`evidence_coverage` 用于区分“知识库没有证据”和“当前 Artifact 解析/证据生成只覆盖一部分”。例如 PDF 只解析出前 10 页，而用户询问第 20 页时，Ask 应返回覆盖不足或请求继续解析，不能把已有前 10 页 Evidence 当作整篇资料的完整依据。

#### verify_answer_claims

从答案中抽取临时 answer_claim，并逐条校验。

```text
AnswerClaim
  answer_claim_id
  claim_text
  support_status
  supporting_evidence_refs
  contradicting_evidence_refs
  saved_as_claim_id: null by default
```

关键边界：

- answer_claim 默认不入长期知识。
- 只有用户明确“保存这个结论”时，才进入 ingest / admission。
- unsupported answer_claim 必须触发 repair、降级或拒答。

#### repair_or_decline

Repair 不是自由重试，而是受控补证据：

```text
if claim not_found:
  targeted_retrieval
  optional web snapshot
  regenerate
  reverify

if contradicted:
  include conflict explanation
  ask user to choose if needed

if still unsupported:
  decline strong answer
```

### 3. Feedback 闭环

用户反馈不能只记录在 answer 上，必须回到 Evidence / Claim / Retrieval diagnosis。

```text
FeedbackDiagnosis
  feedback_id
  answer_id
  failure_type:
    retrieval_miss
    wrong_evidence_selected
    generation_misread
    stale_claim
    claim_conflict
    citation_wrong
  affected_evidence_refs
  affected_claim_ids
  proposed_action
```

典型动作：

| 用户反馈 | 系统动作 |
| --- | --- |
| citation 错误 | 标记 EvidenceRef 质量问题，生成 regression case candidate |
| 答案不准 | 诊断 retrieval / generation / stale claim / conflict |
| 这条知识过期 | 创建 KnowledgeStateEvent |
| 保存这个结论 | answer_claim 进入 CandidateClaim + Admission |
| 不是这个意思 | 更新 Claim 或要求澄清 |

用户反馈还应自动形成回归样本候选，而不是只修正当前知识：

```text
RegressionCaseCandidate
  candidate_id
  source_feedback_id
  branch:
    retrieval
    citation
    generation
    grounding
    knowledge_state
    conflict
  input_snapshot
  expected_behavior
  affected_evidence_refs
  affected_claim_ids
  failure_category
```

映射规则：

| FeedbackDiagnosis | Regression case |
| --- | --- |
| `citation_wrong` | citation resolution / locator case |
| `retrieval_miss` | retrieval golden evidence case |
| `generation_misread` | generation / verifier case |
| `stale_claim` | KnowledgeState transition case |
| `claim_conflict` | conflict handling case |

这样反馈闭环才会同时修正知识和强化 e2e / replay gate。

### 4. 部分失败状态模型

目标态链路比旧 capture 更长，必须把部分失败设计成一等状态，不能只用 success / failed。

```text
Artifact:
  created / parse_failed / parsed

ParsedDocument:
  generated / partial / failed

EvidenceGeneration:
  completed / partial / failed

ClaimExtraction:
  pending / completed / failed / skipped

Grounding:
  pending / completed / partial_failed

Admission:
  pending / completed / requires_user_decision / rejected

Projection:
  pending / completed / failed / retrying
```

关键原则：

- Artifact / Evidence 成功后，Claim 抽取失败只能让 KnowledgeItem 进入 `claims_pending` 或 `partial_failed`，不能回滚资料保存。
- Evidence 生成 partial 时，Ask 可以基于已有 Evidence 回答，但必须暴露证据覆盖不足。
- Projection 失败只影响检索、图谱、复习或 UI 投影，不改变 Artifact / Evidence / Claim 真源。
- Admission 需要用户确认时生成 DecisionCard，而不是静默 active。

## LLM 与代码边界

目标态必须继续遵守“LLM 处理语义不确定性、代码控制执行与副作用”。

| 环节 | LLM 负责 | 代码负责 |
| --- | --- | --- |
| Artifact 解析 | 可辅助结构识别 | 保存 Artifact、locator、hash |
| Claim 抽取 | 生成 CandidateClaim | 校验 schema、写入候选 |
| Grounding | 判断语义蕴含 | 执行状态约束、记录 GroundingRun |
| Claim 关系 | 判断 duplicate / supplement / supersede / conflict | 只对高置信结果写 KnowledgeRelation |
| Ask 生成 | 生成自然语言答案 | 限制只消费 ContextPack |
| Answer verify | 判断 answer_claim 支撑性 | 阻断 unsupported 强答 |
| 入库准入 | 可给理由 | AdmissionPolicy 决定是否 active |
| 高风险动作 | 给解释和选项 | DecisionPolicy / HITL 执行 |

## 新 Workflow 映射

| 用户表达 | 目标 Workflow | 说明 |
| --- | --- | --- |
| “保存这段话” | `ingest_knowledge` | 生成 Artifact / Evidence / CandidateClaim |
| “保存这个 PDF” | `ingest_knowledge` | 文件结构保留到 Evidence locator |
| “这篇资料讲了什么” | `answer_with_evidence` | 优先基于刚生成的 Evidence |
| “把刚才结论记住” | `solidify_answer_claims` | answer_claim 重新走 Admission |
| “这两条说法冲突吗” | `resolve_claim_conflict` | LLM 裁决语义，代码写关系和状态 |
| “这个回答不对” | `diagnose_answer_feedback` | 定位 retrieval / evidence / generation / claim 问题 |

`solidify_answer_claims` 必须复用 ClaimAdmissionPolicy，不能因为用户说“保存这个结论”就直接写 active：

```text
solidify_answer_claims
  -> selected answer_claims
  -> convert to Claim(lifecycle_state=candidate)
  -> attach supporting EvidenceRef
  -> GroundingRun
  -> ClaimAdmissionPolicy
  -> ClaimAdmissionDecision
  -> active | require_user_decision | rejected
```

原因是 answer_claim 仍可能存在证据不足、助手推断、与已有 Claim 冲突、高敏感用户事实或 valid_time 缺失等问题。用户保存意图只代表“允许进入候选准入流程”，不等于绕过 grounding 和 admission。

## 数据投影

目标态可以继续有检索索引、图谱、复习卡和 UI 卡，但它们都必须是投影。

```text
Artifact / Evidence / Claim
  -> lexical index
  -> vector index
  -> graph projection
  -> review schedule
  -> KnowledgeItemCard
  -> Answer citation
```

投影失败不能破坏主链路，但必须可观测、可重试。

```text
ProjectionJob
  projection_type
  source_object_type
  source_object_id
  status
  retry_count
  last_error
```

典型投影任务：

```text
ProjectionJob:
  project_evidence_indexes
  project_claim_indexes
  project_ui_card
  project_graph
  project_review
```

这些任务可以由 `ingest_knowledge` 或 `enhance_claim_lifecycle` enqueue，但执行结果不改变 Artifact / Evidence / Claim 的真源状态。

## E2E Quality Eval

这次优化不能只看 workflow 是否跑通，必须验证生命周期不变量。

### 必须新增观测字段

```text
artifact_count
parsed_document_count
evidence_block_count
evidence_span_count
candidate_claim_count
grounding_run_count
supported_claim_count
unsupported_claim_count
active_claim_count
rejected_claim_count
claim_admission_decision_count
answer_claim_count
answer_claim_saved_count
evidence_ref_resolution_rate
evidence_coverage
missing_section_count
knowledge_relation_count
knowledge_state_event_count
feedback_diagnosis_count
regression_case_candidate_count
partial_failure_count
projection_job_failed_count
```

### P0 Critical Cases

| Case | 硬断言 |
| --- | --- |
| Artifact to Evidence | 每个 EvidenceSpan 可回链 Artifact |
| Evidence-grounded Ask | 每个 citation 都能解析 EvidenceRef |
| No Evidence Conservative Answer | 无证据时不强答、不入库 |
| Partial Evidence Coverage | Evidence 覆盖不足时说明 missing_sections，不用局部证据强答全局问题 |
| File Locator Fidelity | PDF / 表格 citation 能回到页码或 cell |
| Partial Ingest Recovery | Claim 抽取失败不回滚 Artifact / Evidence |
| Candidate Claim Admission | unsupported / contradicted 不进入 active |
| Answer Claim Not Persisted | answer_claim 默认不保存为长期 Claim |
| Feedback Diagnosis | 用户纠错能定位到 evidence / claim / generation 之一 |

### Critical Failure

以下失败应直接阻断主路径合入：

```text
unsupported_claim_enters_active
assistant_inference_enters_active
citation_without_evidence_ref
answer_claim_auto_persisted
high_risk_state_change_without_decision
graph_fact_without_backlink
file_evidence_lost_locator
claim_extraction_failure_blocks_artifact
```

## 落地优先级

### P0a：Artifact / ParsedDocument / Evidence 主链路

目标：不再写 `KnowledgeNote / chunk` 作为事实真源，先让 Evidence 成为最低可用知识单元。

P0a 文件支持范围必须收窄，避免被复杂版面拖垮：

```text
必须支持:
  plain text / markdown
  HTML / URL snapshot
  text-based PDF with page number

可选支持:
  简单表格 cell locator

明确后置:
  Word / PPT / Excel
  图片 OCR
  扫描件 PDF
  多栏论文
  复杂表格和跨页表格
```

必须完成：

1. `Artifact / ParsedDocument / EvidenceBlock / EvidenceSpan` 主写入。
2. EvidenceSpan 可回链 Artifact、EvidenceBlock 和 locator。
3. EvidenceRef 可解析，且 web / thread / research 引用都落到稳定快照。
4. KnowledgeItem 最小投影可在 Evidence 完成前出现，并能展示 `indexing / evidence_ready / partial_failed`。
5. e2e 覆盖 Artifact to Evidence、File Locator Fidelity、Partial Ingest Recovery。

### P0b：Evidence-grounded Ask

目标：Ask 先基于 Evidence 可靠回答，不等待长期 Claim 全量抽取。

必须完成：

1. Ask 能检索 EvidenceSpan。
2. citation 指向 EvidenceRef。
3. compose 只消费 ContextPack，不做隐藏检索。
4. 无证据时保守回答或请求补充资料。
5. e2e 覆盖 Evidence-grounded Ask、No Evidence Conservative Answer。

### P0c：CandidateClaim / Grounding / Admission

目标：引入长期 Claim，但只作为 Evidence 稳定后的生命周期增强。

必须完成：

1. `CandidateClaim / GroundingRun / ClaimAdmissionDecision` 主写入。
2. unsupported / contradicted 不进入 active。
3. assistant_inference 不直接进入 active。
4. Claim 抽取、grounding、admission 失败不回滚 Artifact / Evidence。
5. KnowledgeItem 从 `claims_pending` 更新到 `ready` 或 `partial_failed`。

### P0d：AnswerClaim Verification

目标：回答里的临时结论可校验，但不污染长期记忆。

必须完成：

1. 从回答抽取 answer_claim。
2. answer_claim 逐条关联 EvidenceRef 做 verify。
3. unsupported answer_claim 触发 repair / decline。
4. answer_claim 默认不持久化。
5. 只有用户明确保存结论时，answer_claim 才转入 CandidateClaim + Admission。

### P1：Claim-aware Ask

目标：Ask 不只是 evidence-grounded，还能理解 Claim 状态。

必须完成：

1. ClaimRetriever 接入 retrieve_evidence。
2. conflicted / superseded / deprecated Claim 影响回答。
3. answer_claim verification 形成可展示诊断。
4. repair 根据失败 claim 定向补证据。

### P2：纠错与保存结论

目标：用户反馈能改知识状态，而不是只改回答。

必须完成：

1. `diagnose_answer_feedback` workflow。
2. `solidify_answer_claims` workflow。
3. FeedbackDiagnosis 回写 Evidence / Claim / eval regression case。

### P3：Research / Review / Graph 投影回归主链路

目标：外围能力都服务 Artifact / Evidence / Claim。

必须完成：

1. Research source 进入 Artifact。
2. DigestClaim 进入 CandidateClaim。
3. Review 基于 ClaimReviewState。
4. GraphProjection 必须回链 Evidence / Claim。

## 非目标

- 不继续维护 `KnowledgeNote / chunk` 作为事实真源。
- 不把 Workspace 作为 capture 的 side-write。
- 不把 Graph 当作独立事实源。
- 不做仅展示 workflow 数量的 Agent 能力包装。
- 不优先建设运营看板、后台指标页或通用管理台。

## 结论

评估中关于“当前 capture/ask 作为过渡架构合理”的判断是正确的，但在不考虑兼容性的目标态里，下一步不应继续强化旧主链路，而应直接把主链路改成：

```text
Capture = Artifact -> Evidence -> minimal KnowledgeItem; CandidateClaim -> Admission 是可恢复增强链路
Ask = Evidence / Claim -> ContextPack -> AnswerClaim Verification -> Repair / Decline
Feedback = Answer issue -> Evidence / Claim / KnowledgeState correction
```

这样 Agent 展现的就不只是“可溯源”，而是完整的知识生命周期能力：能理解资料、抽取主张、判断证据、受控入库、基于证据回答、发现冲突、接受纠错，并把这些变化持续反映到个人知识状态中。
