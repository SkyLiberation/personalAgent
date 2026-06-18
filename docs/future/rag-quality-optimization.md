# Capture / Ask RAG 质量优化设计

本文设计一个**不考虑向后兼容**的目标形态：把当前 capture 入库链路和 ask 检索生成链路的质量上限，从“能用的多源 RAG”提升到“可评测、可解释、强 grounding 的知识库问答”。

平台化（durable execution、worker queue、versioning、replay）已在 [Workflow 平台化优化设计](workflow-platform-optimization.md) 中规划，本文不重复，只聚焦**证据质量与答案质量**这一条正交主线。

允许重命名模型、重建索引、替换 chunk / rerank / verify 的实现，新旧数据不要求共存。

## 目标

```text
Structure-faithful Capture
  -> Versioned Chunk / Provenance
  -> Multi-source Recall
  -> Fusion + Diversify + Compress
  -> Grounded Generation
  -> Entailment-level Verification
  -> Continuous Eval Gate
```

一句话：**把“多路召回 + 启发式 rerank + 启发式校验”升级为“结构忠实入库 + 可解释融合 + 蕴含级 grounding + 离线评测闭环”。**

## 当前差距

当前已有很好的基础（详见 [Capture / Ask 当前流程](../workflow/capture-ask-model-flow.md)）：

- capture：fingerprint 去重、parent/child note、Unstructured chunk、review、chunk-level graph sync。
- ask：query understanding、graph/structural/local/web/episodic/reflection 六路召回、`EvidenceItem` 归一、candidate enrichment、可插拔 rerank、ContextPack 预算、verifier + retry + web fallback。
- 抽象干净：`Retriever` Protocol、`RetrievalCoordinator`、`EvidenceReranker` Protocol、`AskRunContext` durable artifact。

与“强 grounding 知识库问答”相比，主要差距：

| 维度 | 当前状态 | 目标状态 |
| --- | --- | --- |
| 文件结构 | 上传文件先被 provider 抽成纯文本再 partition，页码/坐标/表格未贯穿 | 原生 partition，页码/bbox/表格/标题层级贯穿到 chunk 与 citation |
| Chunk 策略 | Unstructured 结构化 chunk，单一粒度 | 多粒度（sentence-window / auto-merging）+ chunk 质量打分 |
| 召回融合 | 多路 extend 进证据池 + dedupe | RRF / 加权融合 + 来源置信度，可解释打分 |
| 多样性 | 无 MMR / 去冗余仅靠 dedupe | MMR + 实体/文档级多样性约束 |
| 压缩 | ContextPack 按 char 预算截断 | 句级抽取式压缩 + 反证检索（contrastive retrieval） |
| Grounding | verifier 启发式 claim 检查 | claim 抽取 + 逐 claim 证据对齐 + 蕴含判定 |
| 来源 metadata | 手动/有限 | 自动抽取作者/日期/类型，进 filter 与时效判断 |
| 评测 | 有 evals，未成门禁 | 检索/生成/grounding 三类离线指标 + 回归门禁 |

## 目标架构

```text
Capture
  RawIngestItem
    -> NativePartitioner        (PDF/Word/HTML 原生结构, 不先转纯文本)
    -> StructuralChunker        (多粒度: element / sentence-window / auto-merge)
    -> ChunkQualityScorer       (信息密度 / 自包含度 / 噪声过滤)
    -> ProvenanceExtractor      (作者 / 日期 / 文档类型 / 页码 / bbox)
    -> ChunkRevision            (版本化, 内容指纹, 可回滚)
    -> Index (lexical + vector + graph)

Ask
  question
    -> QueryUnderstanding (现有)
    -> RetrievalCoordinator (现有六路)
    -> EvidenceFusion           (RRF / 加权 + 来源置信度, 可解释打分)
    -> Diversifier              (MMR + 实体/文档级去冗余)
    -> ContrastiveRetriever     (主动找反证 / 对立观点)
    -> ContextCompressor        (句级抽取式压缩到预算)
    -> GroundedGenerator        (逐句带 citation 约束)
    -> ClaimVerifier            (claim 抽取 -> 证据对齐 -> 蕴含判定)
    -> EvalHarness              (离线回放, 回归门禁)
```

设计原则：**所有新增能力落在现有 Protocol 接口内**（`Retriever` / `EvidenceReranker` / `CandidateEnricher` / `AnswerVerifier`），新增的是实现与中间模型，不引入第二套编排框架。

## Capture 侧

### 1. 原生结构 partition

当前 `capture_file` 先用 provider 把上传内容抽成纯文本，再交给 `partition_to_chunk_drafts`，页码、坐标、表格结构在第一步就丢了。

目标：文件字节直接进 Unstructured 原生 partition，结构 metadata 全程贯穿：

```text
file bytes
  -> partition (by file type, hi_res for PDF)
  -> Element[] with: page_number, coordinates(bbox), category(Title/Table/...),
                     parent_id, table html
  -> ChunkDraft 携带完整 element metadata
  -> KnowledgeNote.source.locator = {page, bbox, element_ids}
```

收益：citation 可定位到“第几页的哪个区块”，表格不再被压成乱序文本，前端可做原文高亮回跳。`RawIngestItem` 增加 `raw_bytes` / `mime_type` 字段，`capture_node` 不再要求上游先转文本。

### 2. 多粒度 chunk + 质量打分

单一 chunk 粒度对“精确定位”和“完整语义”是矛盾的。目标提供两种检索时可选的扩展：

- **sentence-window**：以句为检索单元，命中后回扩 N 句作为生成上下文，提升定位精度不损上下文。
- **auto-merging**：child chunk 命中过多时自动上卷到 parent，减少碎片。

每个 chunk 过 `ChunkQualityScorer`：信息密度、是否自包含、是否纯噪声（页眉/页脚/目录/导航）。低分 chunk 标记 `retrievable=false`，不进检索单元但保留在 parent 供回溯。这直接解决文档里“chunk 质量评测不是主链路”的缺口。

### 3. Provenance 自动抽取 + chunk 版本化

新增 `ProvenanceExtractor`（capture pipeline 内 enrich 之前一步）：

```text
parent note content + source metadata
  -> 抽取: author, published_at, doc_type, language, title
  -> 写入 KnowledgeNote.source.provenance
  -> 供 ask 的 metadata filter / freshness 判断使用
```

`published_at` 让时效判断不再只靠 capture 时间；`doc_type` 让 filter 能区分“正式文档 vs 聊天片段”。

chunk 版本化：source 内容更新时不直接覆盖，按 `content_fingerprint` 生成新 `ChunkRevision`，旧版本标记 superseded：

```text
ChunkRevision
  chunk_id
  revision        # 自增
  content_fingerprint
  status          # active | superseded
  graph_episode_uuid
```

收益：重复采集同一来源的新版本时增量更新而非全删重建，graph sync 只对变化 chunk 重跑，引用历史答案时可回溯当时版本。

## Ask 侧

### 4. 可解释证据融合

当前六路召回各自把 `EvidenceItem` extend 进 `evidence_pool`，再 dedupe，融合靠后续 rerank 的单一分。问题：不同来源分数不可比，没有显式融合。

目标：在 `RetrievalCoordinator._absorb` 之后、rerank 之前插入 `EvidenceFusion`：

```text
per-source ranked lists (graph / local / structural / web / ...)
  -> Reciprocal Rank Fusion (RRF)         # 跨源 rank 融合, 不依赖分数可比
  -> source confidence weighting          # 来源置信度加权 (graph fact > web snippet)
  -> EvidenceItem.fusion_score + explain  # 每条证据带可解释来源贡献
```

`EvidenceItem` 增加 `fusion_score` 与 `source_contributions`，trace 里能看到“这条证据为何排前”。这是落在现有证据池模型内的增强，不改召回器接口。

### 5. 多样性 + 反证检索

当前 ContextPack 只按相关性和预算选，容易“同一观点的多条近似证据”挤满预算。

- **MMR 多样性**：在 `EvidenceReranker` 内用 MMR 平衡相关性与冗余，并加实体/文档级约束（同一 note 不超过 K 条、覆盖更多不同实体）。
- **反证检索（ContrastiveRetriever）**：对已选证据的核心 claim 主动反向检索“相反/限定条件/例外”，把对立证据也纳入 ContextPack。

收益：答案不再是单侧证据的复述，verifier 也有反例可用，减少“看似 grounded 实则片面”的回答。两者都实现成新的 `EvidenceReranker` / `Retriever`，通过现有可插拔配置选用。

### 6. 抽取式上下文压缩

当前 ContextPack 到预算就按 char 截断，可能切掉关键句、留下噪声句。

目标新增 `ContextCompressor`（rerank 之后、build_context_pack 之前）：

```text
selected evidence + question
  -> 句级打分 (与 question 相关性)
  -> 抽取式保留 top 句, 丢弃无关句
  -> 在更小 token 预算内塞进更多有效信息
```

抽取式（非生成式）压缩保证不引入幻觉，且保留原句 citation 锚点。

### 7. 蕴含级 grounding 校验

当前 `AnswerVerifier` 以启发式 claim 检查为主，文档明确指出“复杂蕴含判断仍需更强 verifier”。

目标把 verify 升级为逐 claim 对齐：

```text
answer
  -> ClaimExtractor          # 把答案拆成原子 claim
  -> 对每个 claim 在 ContextPack 内对齐证据
  -> EntailmentJudge         # entailed / contradicted / not_enough_info
  -> 聚合:
       全部 entailed       -> 通过
       存在 contradicted   -> retry / 修正 / web fallback
       not_enough_info     -> 标注不确定 + 触发反证或 web 检索
```

输出结构化 `VerificationReport`（每 claim 的判定 + 支撑 citation），前端可逐句展示 grounding 状态。这落在现有 `AnswerVerifier` 接口内，替换实现即可。

### 8. 离线评测闭环

质量优化没有评测就是盲改。目标建立三类离线指标，并接成回归门禁（与 [Workflow 平台化](workflow-platform-optimization.md) 的 eval gate 对齐）：

```text
固定问答集 (question + 标注证据 + 参考答案)
  -> 检索指标:  recall@k / nDCG / context precision
  -> 生成指标:  answer relevance / faithfulness
  -> grounding: claim 级 entailment 准确率 / 反证覆盖
```

任何 chunk 策略、rerank、prompt、verifier 实现的改动，先跑回放对比基线，回归即拦截。`AskRunContext.trace_steps` 已经记录了中间态，是天然的回放数据源。

## 数据模型改动

不考虑兼容，目标态直接重建：

```text
KnowledgeNote.source
  + provenance: {author, published_at, doc_type, language}
  + locator:    {page_number, bbox, element_ids}

KnowledgeNote (chunk)
  + retrievable: bool
  + quality_score: float
  + revision: int
  + content_fingerprint: str
  + status: active | superseded

EvidenceItem
  + fusion_score: float
  + source_contributions: dict[str, float]
  + sentence_spans: list[span]      # 压缩后保留的句锚点

VerificationReport
  claims: list[{text, verdict, citations}]
  overall: pass | needs_fix | uncertain
```

向量/词法索引随 chunk 粒度变化重建，graph episode 按 chunk revision 重新映射。

## 分期

虽然不考虑兼容，落地仍建议分层验证：

1. **入库结构层**：原生 partition + provenance + chunk 质量分。先把“进去的东西”做对。
2. **检索质量层**：fusion + MMR + 压缩。证据进 prompt 前的质量。
3. **答案可信层**：反证检索 + 蕴含级 verify。答案出去前的可信度。
4. **评测门禁层**：离线回放 + 回归拦截。锁住前三层不退化。

每层独立可验证，且都能用第 4 层的指标度量收益。

## 非目标

- 不引入 LlamaIndex / Haystack 等第二套 RAG 框架。现有 `Retriever` / `EvidenceReranker` / `AnswerVerifier` Protocol 已是合适的扩展点，新增的是实现而非框架。
- 不替换 LangGraph 编排与 Graphiti 图谱，本文只动证据与答案质量，不动 step workflow 拓扑。
- 不做通用搜索引擎或多租户检索平台，范围限定在个人知识库问答。
