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
| 文件结构 | **已实现**:上传文件经 source_ref 走原生 partition,page/bbox/element_ids/title_path 贯穿到 chunk 与 citation | 多粒度 chunk(sentence-window/auto-merging)待做 |
| Chunk 策略 | **质量分已实现**:Unstructured 结构化 chunk + 启发式质量分,低分标 retrievable=false 不进检索 | 多粒度待做 |
| 召回融合 | ~~多路 extend 进证据池 + dedupe~~ **已实现 RRF 共识融合(见第 4 节)** | RRF 融合已落地;来源置信度加权待做 |
| 多样性 | **已实现**:MMR 选择(λ 可配),内容词 Jaccard 去冗余,跨来源近似复述也能压掉 | 实体/文档级硬约束待做 |
| 压缩 | **已实现**:rerank 前句级抽取式压缩,释放预算给 MMR | —— |
| 反证 | **已实现**:ContrastiveRetriever 反应式召回对立证据(见第 5 节),config 开关 | 默认关闭,可调反证查询策略 |
| Grounding | **已实现**:三态蕴含级 verify(claim → 证据对齐 → entailed/contradicted/not_enough_info),config 可选 | LLM/NLI judge 待插 |
| 来源 metadata | **已实现**:启发式自动抽取 author/published_at/doc_type/language 进 NoteSource.provenance | chunk 版本化(ChunkRevision)待做 |
| 评测 | **已实现**:三类离线指标(检索/生成/grounding)+ hermetic 回归门禁(`evals/rag_quality/`,见第 8 节) | answer_relevance/faithfulness 换 LLM judge 待做 |

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

### 1. 原生结构 partition（部分已实现）

> 状态:**locator(page/element_ids/title_path)+ bbox 已贯穿**;文件字节直达 partition 已通过 `source_ref` 路径实现。多粒度 chunk(sentence-window / auto-merging)未做。

现状已比文档最初描述更好:上传文件经 Web 路由落盘后,`source_ref` 指向**原始文件**,`partition_to_chunk_drafts` 对真实文件走 `partition(filename=...)` 原生路径([document_partition.py](../../src/personal_agent/core/document_partition.py)),而非先拍平成文本。结构 metadata 贯穿:

```text
file (via source_ref)
  -> partition (by file type)
  -> Element[] with: page_number, coordinates(bbox), category(Title/Table/...),
                     element_ids, title_path
  -> ChunkDraft 携带完整 element metadata + coordinates
  -> NoteChunk.{page_number, element_ids, title_path, coordinates, source_span}
```

已实现:`_coordinates()` 抽取 bbox,`ChunkDraft.coordinates` / `NoteChunk.coordinates` 承载,citation 可定位到"第几页的哪个区块"。

未做:`RawIngestItem.raw_bytes` 字节内联(当前依赖 `source_ref` 文件可达,Feishu 等无落盘路径的来源仍是文本);多粒度 chunk。

### 2. 多粒度 chunk + 质量打分（质量打分已实现）

单一 chunk 粒度对“精确定位”和“完整语义”是矛盾的。目标提供两种检索时可选的扩展：

- **sentence-window**(未做)：以句为检索单元，命中后回扩 N 句作为生成上下文，提升定位精度不损上下文。
- **auto-merging**(未做)：child chunk 命中过多时自动上卷到 parent，减少碎片。

> 状态:**chunk 质量打分已实现**。

每个 chunk 过 `ChunkQualityScorer`：信息密度、是否自包含、是否纯噪声（页眉/页脚/目录/导航）。低分 chunk 标记 `retrievable=false`，不进检索单元但保留在 parent 供回溯。

已实现落点:
- [agent/chunk_quality.py](../../src/personal_agent/agent/chunk_quality.py):`ChunkQualityScorer` Protocol + `HeuristicChunkQualityScorer`(确定性密度/噪声打分,无 LLM),`RETRIEVABLE_THRESHOLD`。
- [agent/nodes.py](../../src/personal_agent/agent/nodes.py):`_chunk_notes_from_drafts` 对每个 chunk 打分,写入 `NoteChunk.quality_score` / `retrievable`。
- [memory/facade.py](../../src/personal_agent/memory/facade.py):`search_memory` over-fetch 后过滤 `retrievable=False` 的 chunk,parent note 默认 `retrievable=True` 不受影响。
- Protocol 设计:未来可插拔换成模型打分的 scorer,不改 pipeline。

### 3. Provenance 自动抽取 + chunk 版本化

新增 `ProvenanceExtractor`（capture pipeline 内 enrich 之前一步）：

### 3. Provenance 自动抽取 + chunk 版本化（provenance 已实现）

> 状态:**provenance 抽取已实现**;chunk 版本化(ChunkRevision)未做。

新增 `ProvenanceExtractor`（capture pipeline 内 capture_node 一步）：

```text
raw item content + source metadata
  -> 抽取: author, published_at, doc_type, language
  -> 写入 NoteSource.provenance (child chunk 继承 parent)
  -> 供 ask 的 metadata filter / freshness 判断使用
```

`published_at` 让时效判断不再只靠 capture 时间；`doc_type` 让 filter 能区分“正式文档 vs 聊天片段”。

已实现落点:
- [core/models.py](../../src/personal_agent/core/models.py):`NoteProvenance`(author/published_at/doc_type/language),`NoteSource.provenance`。
- [agent/provenance.py](../../src/personal_agent/agent/provenance.py):`ProvenanceExtractor` Protocol + `HeuristicProvenanceExtractor`(metadata + 文件名扩展名 + 正文日期正则 + 中英语言判断,无 LLM)。
- [agent/nodes.py](../../src/personal_agent/agent/nodes.py):`capture_node` 填充 parent provenance,`_chunk_notes_from_drafts` 让 child chunk 继承。
- Protocol 设计:未来可插拔换成能从自由文本抽作者/日期的模型 extractor。

未做 —— chunk 版本化：source 内容更新时不直接覆盖，按 `content_fingerprint` 生成新 `ChunkRevision`，旧版本标记 superseded：

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

### 4. 可解释证据融合（已实现）

> 状态：**已落地**。下文描述的三层(实体身份去重 → 共识记录 → RRF 融合)已在主链路实现,本节同时保留设计意图与实现落点。

#### 背景:冗余从哪来

召回路实际是 graph(可配 graphiti / structural / hybrid / graphrag)+ local + episodic + reflection + web 五类源(注意 structural 不是独立第六路,而是 `graph_provider` 的取值)。其中 **graph 与 local 的底库都是 `knowledge_notes`**:graph 经 episode→note 映射回 note,local 直接召回 note,同一篇极易被两路同时召回。

原去重 key 绑了 `source_type + snippet[:160]` 这类易变维度——graph 路会改 score、加 `retrieved_by` metadata,导致同一实体漏判成两条,且"留第一条"可能留下低分那条。

#### 三层解法

```text
多路 extend (各路在 _absorb 时保留 per-source rank)
  -> 实体身份去重   canonical_evidence_key: note/chunk 按 source_id, fact 按 fact, web 按 url
  -> 共识合并       同实体合并, 取最高分代表, 记 retrieved_by_all / consensus_count / source_ranks
  -> RRF 融合       apply_rrf_fusion: fusion_score = Σ 1/(k + rank_source), k=60
  -> 启发式 ranker  fusion_score 进打分 (×3, 上限 0.15), reason 带 rrf_consensus=N
  -> rerank -> ContextPack
```

RRF 只用**排名**不用绝对分,天然规避"graph 的 0.55 floor vs local 余弦 0.8 不可比"的问题;同一 note 在多路都靠前 → 多个 `1/(k+rank)` 项相加 → 分数自然升高。**冗余因此从成本浪费翻转成置信信号:被多路召回 = 共识 = 排名加分。**

#### 实现落点

- [core/evidence.py](../../src/personal_agent/core/evidence.py):`canonical_evidence_key()`、`_merge_evidence_group()`、`apply_rrf_fusion()`,以及 `_rank_evidence_item()` 内的 fusion boost。
- [ask/retrievers.py](../../src/personal_agent/agent/ask/retrievers.py):`RetrievalContribution.source`,`_absorb()` 标注 per-source rank。
- [ask/stages.py](../../src/personal_agent/agent/ask/stages.py):`_assemble_context()` 在 dedupe 后插入 `apply_rrf_fusion()`。
- `EvidenceItem.metadata` 现携带 `source_ranks` / `retrieved_by_all` / `consensus_count` / `fusion_score`,trace 可解释"这条证据为何排前"。

#### 后续

- 来源置信度加权(graph fact > web snippet)尚未做,可作为 RRF 之上的加权项。
- per-source rank 当前取"贡献内顺序",未来各 retriever 若产出自带分数的有序列表,可进一步精确。

### 5. 多样性 + 反证检索（MMR + 反证均已实现）

当前 ContextPack 只按相关性和预算选，容易“同一观点的多条近似证据”挤满预算。

> 状态:**MMR 多样性已实现**;**反证检索(ContrastiveRetriever)已实现**(默认关闭)。

- **MMR 多样性**(✅):`select_ranked_evidence` 改为 MMR 选择,每步选 `λ·relevance − (1−λ)·max_sim` 最大的候选,相似度用内容词 Jaccard(`_jaccard`),跨来源的近似复述也能去冗余。`λ` 由 `ask.context_mmr_lambda`(默认 0.7)配置。
- **反证检索（ContrastiveRetriever）**(✅):做成 **verification 阶段的反应式 hook** —— 仅当首轮 verify 出现 `contradicted` / `not_found` 的 claim 时,才把这些 claim 改写成"对立"子查询(claim 核心词 + 反对/风险/例外等 cue),反向召回对立证据并入证据池,然后重组上下文 + 重新生成 + 重新校验。按需触发,不增加正常路径开销。

已实现落点:
- [core/evidence.py](../../src/personal_agent/core/evidence.py):`select_ranked_evidence` MMR 选择 + `_jaccard` 内容相似度;过期版本(superseded/deprecated)硬过滤保留。
- [core/rerankers.py](../../src/personal_agent/core/rerankers.py):`rerank` 接口加 `mmr_lambda` 透传,heuristic / llm 两路共用。
- [core/config_models.py](../../src/personal_agent/core/config_models.py) + [ask_pipeline_factory.py](../../src/personal_agent/agent/ask_pipeline_factory.py):`context_mmr_lambda` 配置贯穿。
- [ask/retrievers.py](../../src/personal_agent/agent/ask/retrievers.py):`ContrastiveRetriever`(实现 `Retriever` 谱系,经 `retrieve_for_claims` 驱动,标 `retrieved_by="contrastive"`)+ `RetrievalCoordinator.add_contrastive_evidence` hook。
- [ask/stages.py](../../src/personal_agent/agent/ask/stages.py):`VerificationStage._contrastive_pass` 反应式触发(`_should_seek_contrast` 判定),`ctx.contrastive_tried` 防重入。
- 配置:`ask.contrastive_retrieval`(默认 `false`,开启后才走反证)。

收益：答案不再是单侧证据的复述，verifier 也有反例可用，减少“看似 grounded 实则片面”的回答。

### 6. 抽取式上下文压缩（已实现）

当前 ContextPack 到预算就按 char 截断，可能切掉关键句、留下噪声句。

> 状态:**已实现**。

`compress_evidence`（rerank 之前）对长 note/chunk 片段做句级抽取:

```text
evidence snippets + question
  -> 句级打分 (与 question 词重叠)
  -> 抽取式保留 top 句 (原序, 锚点不变), 丢弃无关句
  -> 释放的预算让 MMR 选入更多不同证据
```

抽取式（非生成式）压缩保证不引入幻觉，且保留原句 citation 锚点。

已实现落点:
- [core/evidence.py](../../src/personal_agent/core/evidence.py):`compress_evidence`(句级词重叠打分,保原序,跳过短片段和 graph_fact/web 原子证据,无重叠时不动)+ `_split_sentences`。
- [agent/ask/stages.py](../../src/personal_agent/agent/ask/stages.py):`_compressed_evidence` 在 rerank 前压缩,trace 记录 `trimmed_snippets`。
- 配置:`ask.context_compress_max_sentences`(默认 3,设 0 关闭)。

### 7. 蕴含级 grounding 校验（已实现）

当前 `AnswerVerifier` 以启发式 claim 检查为主，文档明确指出“复杂蕴含判断仍需更强 verifier”。

> 状态:**已实现**(三态启发式判定,config 可选;LLM/NLI judge 留接口待插)。

verify 升级为逐 claim 三态对齐:

```text
answer
  -> _extract_claims          # 把答案拆成原子 claim(复用既有切句)
  -> 对每个 claim 在证据池内按词重叠对齐最佳证据
  -> EntailmentJudge          # entailed / contradicted / not_enough_info
  -> 聚合(沿用 AnswerVerifier 既有逻辑):
       entailed       -> supported   -> 提分
       contradicted   -> contradicted-> 触发 issue + 反证 / web fallback
       not_enough_info-> not_found   -> 警告 / 触发反证
```

关键改进在**冲突精度**:不再只靠"词重叠 + 单一负词翻转",而是在*已对齐*证据上判 polarity(增加/减少等反义对)、negation parity、numeric(claim 断言的数字证据不含)三类冲突 —— 且冲突判定有 `aligned` 门槛,避免无关的否定句误翻转无关 claim。

已实现落点:
- [agent/entailment.py](../../src/personal_agent/agent/entailment.py):`EntailmentJudge` Protocol + `HeuristicEntailmentJudge`(确定性、无 LLM)+ `EntailmentVerdict`。
- [agent/verifier.py](../../src/personal_agent/agent/verifier.py):`AnswerVerifier._grounding_checks` 抽成可重写 hook;`EntailmentAnswerVerifier` 子类只换 grounding 策略,复用全部 citation / 打分 / fallback 逻辑;verdict→status 映射让下游聚合零改动;`create_answer_verifier` 工厂。
- [core/config_models.py](../../src/personal_agent/core/config_models.py) + [agent/runtime.py](../../src/personal_agent/agent/runtime.py):`ask.verifier`(默认 `heuristic`,设 `entailment` 启用),runtime 经工厂构造。

输出仍是 `VerificationResult`(每 claim 的 `status` + 支撑 citation + reason 带 verdict 前缀),前端可逐句展示 grounding 状态,序列化无需改动。未做:把 judge 换成真正的 NLI / LLM 实现(Protocol 已留位)。

### 8. 离线评测闭环（已实现）

质量优化没有评测就是盲改。目标建立三类离线指标，并接成回归门禁（与 [Workflow 平台化](workflow-platform-optimization.md) 的 eval gate 对齐）：

```text
固定问答集 (question + 标注证据 + 参考答案 + 标注 claim grounding)
  -> 检索指标:  recall@k / nDCG@k / context precision
  -> 生成指标:  answer relevance / faithfulness
  -> grounding: claim 级 entailment 准确率 / 反证覆盖
```

> 状态:**已实现**(hermetic 回归门禁;打分纯函数化,无 DB/LLM)。

设计要点 —— **打分与运行解耦**:scorer 只认 `RunOutput`(ranked/selected evidence ids + answer + claim verdicts 的薄投影),从不接触实时管线,所以每个指标都能从序列化的 run 数据复现、用手搓 fixture 单测。门禁测试对预标注 fixture 打分并断言聚合阈值,完全 hermetic;只有 CLI runner 才驱动真实 `execute_ask` 或回放序列化的 `AskRunContext`(文档点名的 DB-free 回放路径)。

已实现落点(均在 [evals/rag_quality/](../../evals/rag_quality/)):
- `metrics.py`:`precision_at_k` / `context_precision` / `answer_relevance` / `faithfulness` / `claim_entailment_accuracy` / `contrastive_coverage`;recall@k / nDCG@k 直接复用 `evals/open_ragbench/metrics.py`,不重造;词法打分复用 `core.evidence._terms` / `_jaccard`,与检索/校验同一词空间。
- `dataset.py` + `cases.json`:`RagEvalCase`(question + gold evidence ids + reference + 标注 claim verdicts + 需反证数)+ `RunOutput` 投影 + JSON 加载器(容忍未知键)。
- `scorer.py`:`score_case` → `CaseScore`,`aggregate` → `RagQualityReport`(均值 + `check_thresholds` 回归判定)。
- `runner.py`:`run_output_from_context` / `run_output_from_result` 双适配器 + `replay_contexts` 离线回放 + `main()` CLI。
- `test_rag_quality_gate.py`:hermetic 门禁,**claim verdict 由真实 `EntailmentAnswerVerifier` 产出**(verifier 退化会在此暴露);`baseline.json` 冻结回归阈值。
- `test_metrics.py`:指标纯函数 + 数据集/聚合单测。

关键真实性发现:门禁初跑暴露 `rq-005`(答案断言"量子计算颠覆密码学")在反证证据进池后被 verifier 从 `not_found` 翻成 `contradicted` —— 这正是第 3 层反证检索 + 蕴含校验联动的正确效果,据实更新了标注而非改判定逻辑。`claim_accuracy` 阈值设 0.75(低于实测 0.80),因启发式 verifier 对多句 claim 的切分粒度与标注不同(已知 verifier 局限,非 harness bug),诚实留出回归头寸。

任何 chunk 策略、rerank、prompt、verifier 实现的改动，先跑回放对比基线，回归即拦截。`AskRunContext.trace_steps` 与 `to_artifact_payload` 已经记录中间态,是天然的回放数据源。未做:把 `answer_relevance` / `faithfulness` 的词法启发式换成 LLM/NLI judge(函数边界即替换点);接入 `record_workflow_eval_run` 的 DB 侧门禁。

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

1. **入库结构层**(✅ 主体已实现):原生 partition + bbox 贯穿 + provenance 抽取 + chunk 质量分/retrievable 过滤。待做:多粒度 chunk、chunk 版本化、RawIngestItem 字节内联。
2. **检索质量层**(✅ 已实现):RRF 共识融合 + MMR 多样性 + 抽取式压缩(第 4-6 节)。
3. **答案可信层**(✅ 主体已实现):反证检索(反应式 hook)+ 蕴含级 verify(三态启发式判定)。待做:LLM/NLI judge 实现替换。
4. **评测门禁层**(✅ 已实现):离线回放 + 三类指标 + hermetic 回归拦截(`evals/rag_quality/`)。锁住前三层不退化。待做:词法生成指标换 LLM/NLI judge、接 DB 侧 eval gate。

每层独立可验证，且都能用第 4 层的指标度量收益。

## 非目标

- 不引入 LlamaIndex / Haystack 等第二套 RAG 框架。现有 `Retriever` / `EvidenceReranker` / `AnswerVerifier` Protocol 已是合适的扩展点，新增的是实现而非框架。
- 不替换 LangGraph 编排与 Graphiti 图谱，本文只动证据与答案质量，不动 step workflow 拓扑。
- 不做通用搜索引擎或多租户检索平台，范围限定在个人知识库问答。
