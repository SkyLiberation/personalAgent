# Capture / Ask 的 RAG 架构设计

本文按 RAG 架构重新组织 `capture` 和 `ask` 两条链路，说明当前实现、与优秀 RAG 系统的差距、推荐的目标形态，以及关键模型在各层中的职责。

对应代码主要位于：

- [src/personal_agent/web/api.py](../src/personal_agent/web/api.py)
- [src/personal_agent/agent/runtime_capture.py](../src/personal_agent/agent/runtime_capture.py)
- [src/personal_agent/agent/runtime_ask.py](../src/personal_agent/agent/runtime_ask.py)
- [src/personal_agent/agent/graph.py](../src/personal_agent/agent/graph.py)
- [src/personal_agent/agent/nodes.py](../src/personal_agent/agent/nodes.py)
- [src/personal_agent/core/models.py](../src/personal_agent/core/models.py)
- [src/personal_agent/core/evidence.py](../src/personal_agent/core/evidence.py)
- [src/personal_agent/graphiti/store.py](../src/personal_agent/graphiti/store.py)
- [src/personal_agent/graphiti/reranker.py](../src/personal_agent/graphiti/reranker.py)
- [src/personal_agent/storage/postgres_memory_store.py](../src/personal_agent/storage/postgres_memory_store.py)

## 当前结论

当前架构已经具备 RAG 的基本闭环：

```text
capture: 原始输入 -> note/chunk -> 本地存储 -> Graphiti 图谱索引
ask: question -> 图谱检索 -> 本地检索回退 -> web 回退 -> 生成 -> 校验
```

它的优势是分层清楚、证据模型已开始统一、图谱与原文 note 有 episode 映射、回答后有 verifier。主要差距在检索精度和上下文装配：

- 缺少真正的向量/BM25/全文混合本地索引，本地检索仍是简单 token 子串匹配。
- 图谱 `citation_hits` 虽然做了聚焦排序，但 prompt 事实块目前优先使用 `fact_refs / edge_refs`，精排结果没有完全控制生成上下文。
- 没有独立的 query understanding 层，时效性、问题类型、过滤条件、用户意图没有转成检索计划。
- rerank 主要是图谱边的启发式排序，缺少跨来源、跨粒度的统一 rerank。
- evidence score 更像引用数量和存在性评分，还不是事实级 grounding / faithfulness 校验。
- web 搜索是证据不足后的兜底，不是根据 freshness intent 主动参与检索。
- observability 主要靠日志和 trace step，尚缺少可评测的检索指标、召回集、rerank 过程和 prompt 上下文快照。

## 优秀 RAG 架构对照

| RAG 层 | 优秀架构通常具备 | 当前实现 | 主要差距 |
| --- | --- | --- | --- |
| Ingestion | 文档解析、清洗、结构保留、元数据抽取、增量更新 | `CaptureService` 提取正文，`RawIngestItem` 承载来源 | 元数据和结构化解析较少，缺少去重/版本/权限细粒度策略 |
| Chunking | 语义切分、层级 chunk、标题路径、窗口重叠 | `chunk_content()` 生成 parent + chunk notes | chunk 策略仍偏简单，缺少语义边界和检索优化字段 |
| Indexing | 向量、BM25/FTS、图谱、关键词、时间索引并存 | Postgres note + Graphiti 图谱 | 本地无向量/全文索引，Graphiti 是主语义索引 |
| Query Understanding | 改写、分解、时效识别、过滤条件、检索计划 | Router 判断 `ask`，ask 内部直接检索 | 缺少查询改写、多跳计划、freshness 策略 |
| Retrieval | 多路召回、元数据过滤、parent-child 展开 | 图谱优先，本地回退，web 回退 | 串行回退偏强，缺少并行召回和统一候选池 |
| Rerank | Cross-encoder/LLM rerank、MMR、多样性、阈值 | Graphiti 策略 + 图谱 edge 启发式 rerank | 缺少跨图谱/note/web 的统一 rerank |
| Context Assembly | 去重、压缩、引用锚定、预算控制、排序可解释 | 构建 graph/local/web prompt，含 citations/evidence | `citation_hits` 未完全主导 graph prompt；预算和压缩策略较弱 |
| Generation | 严格基于证据、引用约束、无法回答策略 | `_generate_answer()` + prompt 约束 | 生成和引用绑定不够强，答案结构未显式和 evidence 对齐 |
| Verification | 引用有效性、事实一致性、覆盖度、反证检查 | `AnswerVerifier` + retry | 校验仍偏轻量，缺少事实级 entailment |
| Evaluation | Recall@k、MRR、faithfulness、答案质量回归集 | `evals/` 有 ask/retrieval 评测雏形 | 需要覆盖图谱、chunk、web、时效、多跳案例 |

## RAG 总体目标架构

推荐把系统稳定抽象成两条流水线：离线/准实时索引流水线和在线回答流水线。

```text
Capture / Indexing Pipeline
  EntryInput
  -> Source normalization
  -> Content extraction
  -> Cleaning + metadata enrichment
  -> Semantic chunking
  -> Local document store
  -> Local lexical/vector indexes
  -> Graph extraction / Graphiti episode
  -> Index status + trace

Ask / Retrieval-Augmented Generation Pipeline
  Question
  -> Query understanding
  -> Retrieval plan
  -> Multi-source retrieval
  -> Candidate normalization
  -> Rerank + diversity + threshold
  -> Context assembly
  -> Grounded generation
  -> Verification / retry / fallback
  -> AskResult
```

当前代码已经覆盖其中一部分，但还需要把“检索候选”和“生成上下文”之间的边界显式化：所有来源都先变成 `EvidenceItem`，再由统一 rerank 和 context assembly 决定哪些证据进入 prompt。

## Capture / Indexing Pipeline

### 1. Source normalization

入口由 `AgentService.entry()` 和 `AgentRuntime.execute_entry()` 负责路由。采集类输入最终进入 `execute_capture()`：

```text
EntryInput(source_type="text"|"link"|"file")
  -> CaptureService 提取正文
  -> RawIngestItem
```

核心模型：

- `EntryInput.text`：用户提交的文本、链接或文件入口信息。
- `EntryInput.source_type`：来源类型。
- `EntryInput.source_ref`：URL、上传文件路径等来源引用。
- `RawIngestItem.content`：真正进入索引流水线的正文。
- `RawIngestItem.user_id`：知识归属和检索隔离边界。

目标改进：

- 为上传文件、网页、手工笔记保留更完整 metadata，例如标题、作者、发布时间、抓取时间、文件页码、MIME type。
- 增加 source fingerprint，支持重复采集检测和版本更新。

### 2. Cleaning and chunking

当前 `build_capture_graph()` 固定执行：

```text
capture -> enrich -> link -> schedule_review
```

`capture_node` 生成 `KnowledgeNote`；长文通过 `chunk_content()` 拆成 parent note 和 chunk notes：

```text
KnowledgeNote(parent)
  -> KnowledgeNote(chunk 1)
  -> KnowledgeNote(chunk 2)
  -> ...
```

核心字段：

- `KnowledgeNote.content`：原文或 chunk 正文。
- `KnowledgeNote.summary`：摘要，当前也参与展示和本地匹配。
- `KnowledgeNote.parent_note_id`：chunk 的父文档。
- `KnowledgeNote.chunk_index`：chunk 顺序。
- `KnowledgeNote.source_span`：chunk 在原文中的位置。

目标改进：

- chunk 应尽量按语义边界切分，并保留标题路径、章节、页码、段落位置。
- parent note 适合展示和文档级召回，chunk note 适合证据级召回。
- 可增加 small-to-big retrieval：先召回 chunk，再自动展开 parent / 邻近 chunk。

### 3. Local store and local indexes

当前本地持久化由 `PostgresMemoryStore` 负责。`link_node` 会：

- 调用 `find_similar_notes(user_id, content)` 找相似笔记。
- 写入 `KnowledgeNote.related_note_ids`。
- 持久化 parent note 和 chunk notes。

当前 `find_similar_notes()` 是简单 token 子串匹配：

```text
query.split()
  -> token in title/summary/content
  -> score
  -> parent 去重
```

这是当前本地 RAG 最大短板之一。优秀 RAG 通常至少需要：

- Lexical index：Postgres FTS、pg_trgm、BM25 或中文分词索引。
- Vector index：按 chunk embedding 检索语义相似内容。
- Metadata filter：按 `user_id / source_type / source_ref / created_at / tags / graph_sync_status` 过滤。
- Parent-child expansion：chunk 命中后展开父文档和邻近 chunk。

### 4. Graph indexing

`execute_capture()` 会调用：

```text
GraphitiStore.ingest_note(result.note)
```

返回 `GraphCaptureResult`，再回写到 `KnowledgeNote`：

- `graph_episode_uuid`
- `entity_names`
- `relation_facts`
- `graph_node_refs`
- `graph_edge_refs`
- `graph_fact_refs`
- `graph_sync_status`
- `graph_sync_error`

长文 chunk notes 在 Graphiti 配置完整时会先置为 `pending`，再由后台 `sync_note_to_graph(note_id)` 同步。

目标改进：

- 明确 parent 和 chunk 是否都应进入图谱；如果都进，需要避免实体/关系重复污染。
- 图谱 episode 应可回溯到 note/chunk/source_span。
- 图谱事实应进入统一 evidence 层，不应在生成阶段绕过 rerank。

## Ask / RAG Pipeline

### 1. Query understanding

当前 `execute_ask()` 做的准备较轻：

```text
bind_session(user_id, session_id)
conversation_messages -> working_context
question -> GraphitiStore.ask()
```

对话历史来自 LangGraph checkpoint `messages`，由 ask branch 以 `conversation_messages` 传入。历史只用于理解指代、目标和更正，不作为事实证据。

优秀 RAG 通常会在检索前生成结构化查询理解结果，例如：

- `needs_freshness`：是否需要今天、最新、实时信息。
- `needs_personal_memory`：是否需要个人知识库。
- `needs_graph_reasoning`：是否需要实体关系、多跳推理。
- `query_rewrite`：适合检索的改写问题。
- `sub_queries`：多跳或复合问题拆解。
- `filters`：用户、时间、来源、标签、文件范围。
- `answer_policy`：必须引用、允许 web、证据不足时拒答。

当前缺少这一层，导致 ask 只能按固定顺序串行检索。

### 2. Retrieval plan

当前检索计划是硬编码三层回退：

```text
1. Graphiti graph retrieval
2. Local note retrieval
3. Web search fallback
```

这个顺序可用，但不是优秀 RAG 的理想形态。更推荐根据 query understanding 形成计划：

```text
个人知识问题:
  graph + local 并行召回

事实时效问题:
  web 优先或 web + local 并行

多跳关系问题:
  graph 优先，local chunk 补证据

原文定位问题:
  local chunk / lexical 优先，graph 辅助扩展
```

目标是让“是否检索、检索哪里、检索多少、如何合并”成为显式决策，而不是固定 fallback。

### 3. Graph retrieval

当前图谱检索：

```text
GraphitiStore.ask(question, user_id, trace_id)
  -> graphiti.search_(query=question, config=search_strategy.search_config)
  -> search_result.nodes / search_result.edges
  -> strategy.citation_hits(question, edges, node_names_by_uuid)
  -> GraphAskResult
```

`PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY` 支持：

- `hybrid_rrf`
- `hybrid_mmr`
- `hybrid_cross_encoder`
- `edge_rrf`
- `edge_node_distance`

`GraphCitationHit` 是当前图谱 rerank 的关键输出：

- `episode_uuid`：支撑事实的 episode。
- `relation_fact`：关系事实。
- `endpoint_names`：关系两端实体。
- `matched_terms`：命中的问题关键词。
- `entity_overlap_count`：问题实体重叠数量。
- `score`：启发式相关性分数。

当前风险：

- `citation_hits` 是聚焦后的事实，但 `GraphAskResult.fact_refs / edge_refs` 仍保存了原始 `search_result.edges`。
- `_build_graph_fact_blocks()` 当前优先使用 `fact_refs`、再使用 `edge_refs`、最后才使用 `citation_hits`。
- 因此，精排事实可能没有真正主导 prompt 上下文，模型会受到 Graphiti 原始边顺序影响。

推荐调整：

```text
graph facts for prompt:
  1. citation_hits
  2. 与 citation_hits 未重复且通过阈值的 fact_refs
  3. 必要的邻接补充 edge_refs
  4. relation_facts fallback
```

更进一步，可以在 `GraphAskResult` 中区分：

- `raw_edge_refs`：调试和可视化用。
- `ranked_fact_refs`：进入生成上下文的事实。
- `citation_hits`：可映射到 note/chunk 的引用事实。

### 4. Local retrieval

当前本地回退：

```text
build_ask_graph(store)
  -> answer_node()
  -> PostgresMemoryStore.find_similar_notes(user_id, question)
```

命中的 notes 会转成：

- `matches`
- `Citation`
- `EvidenceItem(source_type="note"|"chunk")`

当前问题：

- 中文问题没有分词或 n-gram 支持。
- 没有 embedding 语义召回。
- 没有按字段加权，例如标题、summary、chunk content 权重不同。
- 没有 query rewrite 和 metadata filter。
- 返回数量偏少，且先截断再交给 rerank 的空间不足。

推荐目标：

```text
local retrieval:
  lexical candidates top 30
  + vector candidates top 30
  + graph-neighbor expanded notes
  -> normalize to EvidenceItem
  -> unified rerank
```

### 5. Web retrieval

当前 web 仅在 verifier 判断本地证据不足时触发：

```text
if not verification.sufficient and _web_search_available:
  web_search(query=question, limit=5)
```

这适合兜底，但不适合“今天、最新、价格、天气、版本、新闻”等时效问题。优秀 RAG 应该在 query understanding 阶段识别 freshness intent，并主动把 web 放进 retrieval plan。

推荐目标：

- `needs_freshness=True` 时，web 优先或与本地并行。
- web evidence 必须携带 `url / title / snippet / published_at / provider`。
- 生成时明确区分“个人知识库记录”和“网络搜索结果”。
- 对网络结果增加来源可信度和时间新鲜度排序。

### 6. Candidate normalization

当前已有统一证据模型 `EvidenceItem`，这是向优秀 RAG 演进的好基础。

当前转换：

```text
GraphAskResult -> graph_result_to_evidence()
local matches  -> notes_to_evidence()
web results    -> web_results_to_evidence()
```

目标是让所有来源先归一到候选证据池：

```text
EvidenceItem(
  source_type="graph_fact"|"note"|"chunk"|"web"|"tool",
  source_id=...,
  title=...,
  snippet=...,
  fact=...,
  source_span=...,
  url=...,
  score=...,
  metadata=...
)
```

然后统一进行：

- 去重：同一 note、同一 fact、同一 URL 合并。
- 归因：graph fact 尽量映射回 note/chunk/source_span。
- 过滤：低分、过旧、无引用、跨用户污染候选剔除。
- 扩展：chunk 命中后补 parent、邻近 chunk、关联 graph facts。

### 7. Unified rerank

当前 rerank 主要发生在图谱边内部：

```text
rank_graph_citation_hits()
  -> _rank_graph_hits()
  -> _select_focus_hits()
```

优秀 RAG 应把 rerank 从“图谱专用”升级为“跨来源统一”：

```text
EvidenceItem candidates
  -> lexical/vector/graph/web score normalization
  -> cross-encoder or LLM rerank
  -> MMR diversity
  -> threshold
  -> top evidence for prompt
```

推荐排序信号：

- question 与 snippet/fact 的语义相关性。
- citation 是否能回到原文。
- graph fact 是否有 note/chunk 锚点。
- source freshness。
- source authority。
- parent/chunk 覆盖多样性。
- 与对话上下文指代的匹配程度。

### 8. Context assembly

当前 prompt 构造分为：

- `_build_graph_answer_prompt()`
- `_build_local_answer_prompt()`
- `_build_web_answer_prompt()`

其中 graph prompt 包括：

```text
question
+ working_context
+ graph entity/node summary
+ graph facts from fact_refs / edge_refs / citation_hits
+ anchored citations
+ note evidence snippets
```

优秀 RAG 的 context assembly 应该是独立层，输入统一 rerank 后的 `EvidenceItem`，输出受 token budget 控制的上下文包。

推荐上下文结构：

```text
Question:
  原始问题 + 改写问题

Dialogue constraints:
  只用于指代和更正，不作为事实证据

Evidence:
  [E1] graph_fact + anchored note snippet
  [E2] chunk snippet + source_span
  [E3] web result + url + published_at

Instructions:
  只能基于 Evidence 回答
  每个关键结论标注 evidence id
  证据不足时说明缺口
```

关键要求：

- 进入 prompt 的 evidence 必须来自统一 rerank 后的结果。
- 图谱事实和原文 snippet 要绑定展示，避免只有 graph fact 没有出处。
- raw graph edges 可以保留给调试，但不应默认全部进入生成上下文。
- 对话历史只能放在 constraints 区，不能混进 evidence 区。

### 9. Grounded generation

当前最终生成调用 `_generate_answer()`，使用：

- `settings.openai_api_key`
- `settings.openai_base_url`
- `settings.openai_model`

Graphiti 内部还会使用：

- `settings.graphiti.llm_model or settings.openai.model`
- `settings.graphiti.llm_small_model or settings.openai.small_model`
- `settings.openai_embedding_model`
- `settings.embedding_api_key / embedding_base_url`

目标生成策略：

- 回答必须先给直接结论。
- 每个关键结论要能追溯到 evidence id / citation。
- 对个人知识库和 web 结果进行来源区分。
- 证据不足时拒答或给出不确定性，而不是填补空白。
- 对冲突证据要显式指出冲突来源。

### 10. Verification and fallback

当前 `AnswerVerifier.verify()` 会检查：

- citation 是否指向 matches 中存在的 note。
- evidence 数量和类型。
- fallback 措辞。
- evidence score 是否达到阈值。

不足：

- citation 有效不等于答案事实被 citation 支撑。
- 证据分数主要是数量和存在性，不是事实一致性。
- retry prompt 没有把 evidence 重新强绑定到答案句子。

目标校验：

```text
answer claims
  -> claim extraction
  -> each claim supported by evidence?
  -> citation points to exact snippet/fact?
  -> conflicts?
  -> freshness satisfied?
  -> final answer / retry / ask clarification / web fallback
```

## 推荐的新模型边界

当前模型已经可用，但建议逐步把“检索过程”和“回答结果”拆得更清楚。

### 已有核心模型

| 模型 | 当前职责 |
| --- | --- |
| `EntryInput` | 统一入口输入，承载文本、链接、文件等来源 |
| `RawIngestItem` | capture 待入库正文和来源 |
| `AgentState` | LangGraph 节点间状态 |
| `KnowledgeNote` | 长期知识、chunk、图谱 episode 映射、原文证据载体 |
| `GraphCaptureResult` | 图谱写入结果 |
| `GraphAskResult` | 图谱检索结果 |
| `GraphCitationHit` | 图谱关系事实到 episode/note 的候选引用 |
| `Citation` | 对外展示和 verifier 使用的轻量引用 |
| `EvidenceItem` | 统一 graph/note/chunk/web/tool 证据 |
| `CaptureResult` | capture 输出 |
| `AskResult` | ask 输出 |

### 建议新增或强化的模型

| 模型 | 建议职责 |
| --- | --- |
| `QueryUnderstanding` | 结构化表达时效性、检索范围、改写问题、过滤条件 |
| `RetrievalPlan` | 决定 graph/local/web 是否并行、各自 top_k、策略和阈值 |
| `RetrievalCandidate` | 原始候选，保留来源原始分数和 debug 信息 |
| `RankedEvidence` | rerank 后的 evidence，包含统一分数、排序理由和是否进入 prompt |
| `ContextPack` | 最终 prompt 上下文包，记录 token budget、evidence 顺序和压缩结果 |
| `VerificationReport` | claim-level 支撑关系、冲突、缺口和 fallback 决策 |

这些模型不一定要一次性落库，但应作为代码边界出现。否则检索、rerank、prompt 拼接会继续耦合在 runtime 中。

## 目标 Ask 流程

推荐最终整理为：

```text
EntryInput(text=question)
  -> QueryUnderstanding
  -> RetrievalPlan
  -> graph retrieval
  -> local lexical retrieval
  -> local vector retrieval
  -> optional web retrieval
  -> EvidenceItem candidates
  -> unified rerank
  -> ContextPack
  -> grounded generation
  -> claim verification
  -> retry / fallback / final
  -> AskResult
```

与当前流程相比，关键变化是：

- graph/local/web 不再只是固定串行 fallback，而是由 plan 决定。
- 所有候选先进入统一 evidence 池，再统一 rerank。
- prompt 只吃 rerank 后的 `ContextPack`，避免 raw graph edges 绕过 `citation_hits`。
- verifier 从引用存在性升级为事实支撑性。

## 目标 Capture 流程

推荐最终整理为：

```text
EntryInput(source)
  -> SourceDocument
  -> cleaned document
  -> semantic chunks
  -> KnowledgeNote parent/chunks
  -> metadata / fingerprint / version
  -> local lexical index
  -> local vector index
  -> graph index
  -> index status
  -> CaptureResult
```

与当前流程相比，关键变化是：

- capture 不只是“存 note”，而是完整索引流水线。
- chunk 是检索单元，parent 是展示和上下文扩展单元。
- Graphiti 是图谱索引之一，不应替代本地向量/全文索引。
- 每个索引状态都可观测、可重试、可重建。

## 演进优先级

### P0：修正当前明显错位

- 调整 `_build_graph_fact_blocks()`，让 `citation_hits` 优先进入 graph prompt。
- 限制未经聚焦的 `fact_refs / edge_refs` 进入 prompt。
- 在文档和代码里明确 raw graph refs 与 ranked graph facts 的区别。

### P1：补齐本地检索

- 为 `KnowledgeNote` / chunk 增加全文或 trigram 检索。
- 增加 embedding 索引，至少支持 chunk 级语义召回。
- 本地检索返回更大的候选集，再交给 rerank。

### P2：引入 QueryUnderstanding 和 RetrievalPlan

- 识别时效性、个人知识库需求、图谱推理需求。
- 对 freshness 问题主动 web 检索。
- 对多跳问题优先 graph，对原文定位问题优先 chunk。

### P3：统一 rerank 和 ContextPack

- 所有 graph/note/chunk/web 候选先归一到 `EvidenceItem`。
- 实现跨来源 rerank、去重、多样性和 token budget。
- prompt 只使用 `ContextPack`，不再在各回答函数里临时拼来源。

### P4：强化 verification 和 evaluation

- 增加 claim-level support 检查。
- 建立 Recall@k、MRR、faithfulness、answer quality 回归评测。
- 为 graph/local/web 分别记录召回、rerank、入 prompt、被引用情况。

## 当前设计要点

- capture 的稳定主线是本地 note 入库并尝试 Graphiti 写入；图谱同步状态由 `graph_sync_status / graph_sync_error` 表达。
- ask 的当前主线是图谱优先、本地兜底、必要时 web 搜索。
- `KnowledgeNote` 同时承担长期知识、chunk 定位、图谱 episode 映射和原文证据载体。
- `EvidenceItem` 是后续升级为优秀 RAG 架构的关键模型，应逐步成为所有检索候选的统一中间层。
- 当前最需要修的是“精排证据必须控制生成上下文”，否则检索排序和最终回答之间会断开。

## GraphRAG 失败模式对照评估

本节对照《Graph RAG 失败案例分析》中归纳的典型失败模式，逐条评估当前工程的暴露面与防御能力。personal agent 是单用户、低数据量场景，scale 类失败（百万实体、5000ms 查询、3-10 天更新滞后）天然不会触发，但结构性失败模式都仍存在。

### 当前已自然规避的失败模式

| 失败模式 | 不触发原因 |
| --- | --- |
| 图查询性能瓶颈（Neo4j 大图遍历 3-30s） | 单用户规模，实体/关系数量远低于阈值 |
| 信息更新滞后（3-10 天） | capture 是用户实时入口，分钟级落库 |
| 维护团队成本（>10 人 NLP 团队） | 个人项目，靠模型与启发式自洽 |

### 当前明确防御不住的失败模式（按危险程度排序）

#### 1. 抽取质量黑盒 —— 最致命

文章的核心警示：实体/关系抽取 F1 一旦掉到 0.6-0.7，整个图谱就不可信，但表面上系统仍能跑。

当前现状：

- `graphiti/ontology.py` 的 `ENTITY_TYPES / CUSTOM_EXTRACTION_INSTRUCTIONS` 只是约束 Graphiti 抽取行为，没有任何 precision/recall 评测、抽样人审或对比基准。
- `graph_sync_status` 仅记录单 note 同步成功/失败，不记录抽到了几个实体、几条关系、是否合理。
- 没有抽取质量回归集，每次模型/prompt 调整都是盲调。

风险：长文 chunk 大量入图后，错误事实会沉默地污染 `citation_hits`，verifier 检查 citation 是否回指 note 时也无法发现事实本身就是错的。

需要补的最小可见度：

- capture 阶段记录每个 note 抽出的实体数、关系数、平均事实长度，落到 trace。
- 建一个 100 条左右的人工标注集，月度跑一次 precision/recall。
- 抽取异常（实体数=0、关系全为弱连接词如“相关/有关”）触发 warning。

#### 2. 关系方向反转 / 类型混淆

文章给的典型样本：“A 收购 B” 错抽成 “B 收购 A”、“投资/出资/持股/融资” 在图里并存却不归一。

当前现状：

- 完全依赖 Graphiti 内部抽取，没有对称性校验、关系类型规范化、同义关系合并。
- 没有 user-level 关系类型词表，回答阶段也没有“反向解读”兜底。

风险：错一次就在 `relation_facts / edge_refs` 里永久沉淀，后续多跳推理会累积放大。

最小防御：

- 维护一个 user-level 关系同义表（投资/出资/持股 → 投资类），在 `_merge_graph_capture` 时归一化。
- 对涉及方向语义的关系类型（收购、隶属、上下级）增加抽样人审入口。

#### 3. 多跳错误传播

文章给的数学：每步抽取/消歧准确率 0.9，3 跳后错误率 1-(0.9)^3 ≈ 27%。

当前现状：

- Graphiti `hybrid search` 的 `bfs_max_depth` 默认 3 —— 正好踩在 27% 错误率临界点。已通过 `PERSONAL_AGENT_GRAPH_SEARCH_MAX_HOPS`（默认下调到 2）、`PERSONAL_AGENT_GRAPH_SEARCH_LIMIT`、`PERSONAL_AGENT_GRAPH_SEARCH_MIN_SCORE` 三个开关在 `GraphitiStore` 构造时统一收紧（见 [graphiti/search_strategies.py](../src/personal_agent/graphiti/search_strategies.py) `apply_search_config_overrides`）。
- prompt 装配阶段，`citation_hits` 已主导 `_build_graph_fact_blocks`（占 limit 的 75% 配额），剩下给 `fact_refs / edge_refs` 兜底。
- 仍缺：path-level 调试输出（每条命中事实的 hop_count），便于事后归因。

后续防御：

- 在 trace 里记录每条命中事实的 hop_count、来源（citation_hits / fact_refs / edge_refs），方便事后复盘。
- 评估降级到 max_hops=1 是否影响必要的多跳召回。

#### 4. 同名实体消歧弱

文章给的统计：人物名消歧准确率 72%、产品名 65%。

当前现状：

- Graphiti 内部有 entity resolution，但**没有 user-level 别名/同名校正**。personal agent 场景里“老板/张总/张三/三哥”指同一人是常态。
- 没有 UI 入口让用户主动维护别名表。
- 抽取阶段全靠 LLM 自己理解上下文，错了不可见。

最小防御：

- 增加 user-level alias 表（`canonical_name → [aliases]`），在 capture 入图前对实体名做归一化。
- ask 阶段把 alias 注入到检索 query，提高召回。

#### 5. 成本随长文线性爆炸 —— 已确认

当前每个 chunk 各跑一次 Graphiti `ingest_note`，每次都做实体/关系抽取 LLM 调用，N 个 chunk 等于 N 次 LLM 调用。

文档原 P0~P4 没列这条。最小成本控制：

- 选择性入图：实体密度/信息熵 gate，纯描述/样板段不入图。
- 长文先做一次文档级摘要 + 关键实体清单入图，chunk 仅在本地 lexical/vector 索引中可达。
- 批量抽取：合并同文档多 chunk 到单次 extraction prompt，再回写各 chunk 的 `graph_*_refs`。
- 预算约束：按 user/source 维度限频，避免单次大文件触发几十次 LLM 调用。

#### 6. 查询意图理解缺位

这是文档 P2 列出的 `QueryUnderstanding` 层，目前未实现。

当前现状：ask 直接进检索，没有改写、子问题拆解、freshness 识别、过滤条件抽取。文章 10.6.5 的所有查询规划失败模式都直接暴露：意图反向理解、过度宽泛、多跳消歧错误传播。

#### 7. 图谱健康指标缺失

文章 10.6.9 给的可行性评估工具（图密度、查询模式、消歧难度、稳定性四维评分）当前完全没做：

- 没有度数、连通分量、孤立节点统计。
- 没有定期 audit 入口回答“图谱是否还值得维持”。
- 没有质量阈值告警。

最小防御：定期跑一次图谱健康脚本，输出 `avg_degree / isolated_ratio / largest_component_ratio / repeat_entity_ratio`，留作演进决策依据。

### 文章建议但当前架构反向的关键点

文章强烈推荐**混合方案：向量为主（覆盖 90% 查询），图为辅（仅处理结构化多跳）**。

当前架构是反过来的：

- 检索顺序：图优先 → 本地兜底 → web 兜底。
- 本地检索是 token 子串匹配（`find_similar_notes` 简单 split + in 判断），是文章定义的最弱形态。

这对应文档 P1 要补的本地全文/向量索引，但还没动。建议在落地 P1 时把检索顺序也调整为：本地 lexical + vector 并行召回为主，图谱作为关系推理补充。

### 与现有 P0~P4 演进路径的差距

现有路径覆盖了**检索侧**升级（rerank、context assembly、verifier、本地索引），但几乎没覆盖：

- **图谱质量本身的可观测性**（抽取 precision/recall、健康指标、关系归一化）。
- **图谱构建成本**（长文批量抽取、选择性入图、预算约束）。
- **同名消歧的 user-level 兜底**。

建议在 P0~P4 之外增加一条平行路径 **PG**（Graph Quality）：

- PG-0：抽取数量/异常 trace + 关系同义归一表。
- PG-1：长文批量抽取 + 选择性入图，控制 capture 成本。
- PG-2：user-level alias 表 + capture 前实体归一化。
- PG-3：图谱健康月度 audit 脚本（密度/连通性/重复实体）。
- PG-4：抽取质量回归集 + 月度 precision/recall。

