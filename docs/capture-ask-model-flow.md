# Capture / Ask 流程与模型职责

本文总结当前 `capture` 和 `ask` 两条主链路的执行过程，重点说明过程中涉及到的模型对象，以及这些模型的关键成员在链路中承担的职责。对应代码主要位于：

- [src/personal_agent/web/api.py](../src/personal_agent/web/api.py)
- [src/personal_agent/agent/runtime_capture.py](../src/personal_agent/agent/runtime_capture.py)
- [src/personal_agent/agent/runtime_ask.py](../src/personal_agent/agent/runtime_ask.py)
- [src/personal_agent/agent/graph.py](../src/personal_agent/agent/graph.py)
- [src/personal_agent/agent/nodes.py](../src/personal_agent/agent/nodes.py)
- [src/personal_agent/core/models.py](../src/personal_agent/core/models.py)
- [src/personal_agent/graphiti/store.py](../src/personal_agent/graphiti/store.py)

## 总体入口

当前外部调用主要从 Web API 或运行时 facade 进入：

```text
/api/capture       -> AgentService.capture() -> execute_capture()
/api/capture/upload -> CaptureService 解析文件 -> AgentService.capture()
/api/ask           -> AgentService.ask() -> execute_ask()
/api/ask/stream    -> execute_ask_stream()
```

`AgentService` 本身很薄，负责装配 `Settings`、`LocalMemoryStore`、`GraphitiStore`、`AskHistoryStore` 和 `CaptureService`，随后把行为交给 `AgentRuntime`。`AgentRuntime` 再通过 mixin 分拆出 capture、ask、entry、tools、admin、LLM 等具体能力。

## Capture 过程

### 1. 输入归一化

文本采集时，`/api/capture` 接收 `CaptureRequest`：

- `text`：用户提交的原始文本，或链接地址
- `source_type`：来源类型，如 `text`、`link`
- `user_id`：用户标识

如果 `source_type == "link"`，API 层先调用 `CaptureService.capture_text_from_url()` 把 URL 抓取成正文，并把原 URL 作为 `source_ref` 传入运行时。

文件采集时，`/api/capture/upload` 会先保存上传文件，然后通过 `CaptureService` 完成：

- `normalize_upload_filename()`：规范化文件名
- `source_type_from_upload()`：根据文件名和 content type 推断来源类型
- `capture_text_from_upload()`：把文件内容抽成文本

文件上传也会进入统一的 `capture()` 流程。主 note 会立即尝试写入图谱；长文产生的 chunk notes 会标记为 `pending`，再由 FastAPI `BackgroundTasks` 后台逐个同步图谱。

### 2. 构造采集状态

`execute_capture()` 会创建 `AgentState`：

```text
AgentState(
  mode="capture",
  user_id=normalized_user,
  raw_item=RawIngestItem(...)
)
```

这里最关键的是 `RawIngestItem`：

- `content`：真正要入库的正文
- `source_type`：正文来源类型，后续会写入 note
- `source_ref`：来源引用，例如 URL 或上传文件路径
- `user_id`：知识归属用户

`AgentState` 是 LangGraph 采集图里的共享状态容器，capture 链路会逐步填充：

- `note`：主笔记
- `chunk_notes`：长文切分后的子笔记
- `matches`：与当前内容相关的已有笔记
- `review_card`：复习卡

### 3. LangGraph 固定采集图

`build_capture_graph()` 的节点顺序是：

```text
capture -> enrich -> link -> schedule_review
```

每个节点对模型成员的作用如下。

`capture_node`：

- 从 `state.raw_item.content` 读取正文
- 生成 `KnowledgeNote`
- 长内容会通过 `chunk_content()` 拆成 parent note + chunk notes
- 写入 `state.note` 和 `state.chunk_notes`

`enrich_node`：

- 更新 `state.note.summary`
- 如果没有 tags，则从内容中提取 `state.note.tags`

`link_node`：

- 调用 `LocalMemoryStore.find_similar_notes()`
- 把相似笔记写入 `state.matches`
- 把相似笔记 id 写入 `state.note.related_note_ids`
- 持久化 `state.note` 和 `state.chunk_notes`

`schedule_review_node`：

- 基于 `state.note.summary` 创建 `ReviewCard`
- 写入 `state.review_card`
- 持久化复习卡

### 4. KnowledgeNote 的核心成员

`KnowledgeNote` 是 capture 过程最终沉淀的长期知识模型。

基础归属与来源：

- `id`：笔记唯一标识
- `user_id`：所属用户
- `source_type`：来源类型
- `source_ref`：来源引用
- `created_at / updated_at`：创建和更新时间

内容与检索：

- `title`：由正文前缀生成，作为展示和检索标题
- `content`：完整正文或 chunk 正文
- `summary`：摘要，用于列表、检索、回答证据
- `tags`：简单关键词标签
- `related_note_ids`：本地相似笔记关联

长文切分：

- `parent_note_id`：chunk 指向父笔记
- `chunk_index`：chunk 在文档中的序号
- `source_span`：chunk 对应的原文范围

图谱同步：

- `graph_sync_status`：`idle / pending / synced / failed`
- `graph_sync_error`：图谱同步失败原因
- `graph_episode_uuid`：Graphiti episode UUID
- `entity_names`：Graphiti 抽取出的实体名
- `relation_facts`：Graphiti 抽取出的关系事实
- `graph_node_refs / graph_edge_refs / graph_fact_refs`：结构化图谱引用

### 5. 图谱同步

`execute_capture()` 会调用：

```text
GraphitiStore.ingest_note(result.note)
```

返回模型是 `GraphCaptureResult`：

- `enabled`：本次图谱写入是否成功启用
- `error`：失败原因
- `episode_uuid`：写入 Graphiti 后的 episode 标识
- `entity_names`：抽取出的实体
- `relation_facts`：抽取出的关系事实
- `related_episode_uuids`：写入后搜索到的相关历史 episode
- `node_refs / edge_refs / fact_refs`：结构化图谱节点、边、事实

成功后 `_merge_graph_capture()` 会把这些成员回写到 `KnowledgeNote`：

```text
GraphCaptureResult -> KnowledgeNote.graph_episode_uuid
                   -> KnowledgeNote.entity_names
                   -> KnowledgeNote.relation_facts
                   -> KnowledgeNote.graph_node_refs / graph_edge_refs / graph_fact_refs
                   -> KnowledgeNote.graph_sync_status="synced"
```

如果图谱写入失败：

- 主 note 的 `graph_sync_status` 会置为 `failed`
- `graph_sync_error` 会记录失败原因
- chunk notes 在 Graphiti 配置完整时会先置为 `pending`
- API 层随后后台调用 `sync_note_to_graph(note_id)`，成功后置为 `synced`，失败则置为 `failed`

### 6. CaptureResult

capture 链路最终返回 `CaptureResult`：

- `note`：主 `KnowledgeNote`
- `chunk_notes`：长文 chunk notes
- `related_notes`：本地或图谱发现的相关笔记
- `review_card`：本次生成的复习卡

API 层再把它映射为 `CaptureResponse` 返回前端。

## Ask 过程

### 1. 会话绑定与上下文刷新

`execute_ask(question, user_id, session_id)` 先做会话级准备：

```text
bind_session(user_id, session_id)
set_goal("回答用户问题: ...")
refresh_conversation_summary(user_id, session_id)
context_snapshot()
```

这里主要依赖 `MemoryFacade` 和 `WorkingMemory`：

- `bind_session()`：绑定当前 `user_id:session_id`，切换会话时重置短期工作记忆
- `conversation_summary`：从最近问答历史拼出上下文
- `task_goal`：记录当前任务目标
- `context_snapshot()`：把任务目标、会话摘要、计划和最近步骤拼成 prompt 上下文

### 2. 第一层：Graphiti 图谱检索

ask 优先调用：

```text
GraphitiStore.ask(question, normalized_user, trace_id)
```

返回模型是 `GraphAskResult`：

- `enabled`：图谱是否可用且检索成功
- `error`：图谱失败原因
- `answer`：Graphiti 检索摘要，不是最终答案
- `entity_names`：命中的实体名
- `relation_facts`：命中的关系事实
- `related_episode_uuids`：相关 episode UUID
- `citation_hits`：把关系事实按问题相关性排序后的命中项
- `node_refs / edge_refs / fact_refs`：图谱结构化引用

Graphiti 检索方案由 [search_strategies.py](../src/personal_agent/graphiti/search_strategies.py) 管理，`PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY` 可以在 `hybrid_rrf / hybrid_mmr / hybrid_cross_encoder / edge_rrf / edge_node_distance` 之间切换。策略类负责选择 Graphiti `search_config`，并调用 [reranker.py](../src/personal_agent/graphiti/reranker.py) 生成 `citation_hits`。

Graphiti 原始检索返回 `search_result.nodes` 和 `search_result.edges`，项目不会直接把所有 edge 平铺给回答生成，而是先做一层关系事实排序：

```text
graphiti.search_(question)
  -> search_result.edges
  -> strategy.citation_hits(question, edges, node_names_by_uuid)
     -> rank_graph_citation_hits(question, edges, node_names_by_uuid)
     -> _rank_graph_hits(question, edges, node_names_by_uuid)
     -> _select_focus_hits(question, ranked_hits)
     -> limit 12
  -> GraphAskResult.citation_hits
```

`rank_graph_citation_hits()` 是这层胶水/适配器的公开入口。它不依赖 `Settings`、Neo4j client 或本地存储，只接收 edge-like 对象、问题文本和节点名映射，输出可引用的 `GraphCitationHit` 列表。

内部的 `_rank_graph_hits()` 会遍历每条 Graphiti edge：

1. 读取 `edge.fact` 作为 `relation_fact`
2. 通过 `edge.source_node_uuid / edge.target_node_uuid` 查出关系两端实体名
3. 对 `relation_fact` 和用户问题计算相关性分数
4. 对 `edge.episodes` 中的每个 episode 生成一个 `GraphCitationHit`
5. 按相关性排序并去重

当前相关性分数由几类启发式信号组成：

- `endpoint_score`：如果关系两端实体名出现在问题中，每命中一个实体加较高权重
- `direct_match_score`：如果问题文本和关系事实存在包含关系，额外加分
- `overlap_score`：问题和关系事实的字符 bigram 重叠数量
- `keyword_score`：问题关键词出现在关系事实中时加分，长关键词权重更高
- `relation_bonus`：相邻关键词组合后出现在关系事实中时加分

排序时优先级不是只看总分，而是按下面的 tuple 倒序：

```text
(
  entity_overlap_count,
  len(matched_terms),
  score,
  len(relation_fact),
)
```

也就是说，命中问题实体的关系事实优先；其次看命中关键词数量；再看综合分；最后用事实文本长度作为弱排序项。排序后 `_dedupe_citation_hits()` 会按 `(episode_uuid, relation_fact)` 去重，避免同一个 episode 上重复引用同一条事实。

`_select_focus_hits()` 会再做一次聚焦：

1. 如果有命中问题实体的 hit，只保留这些 hit 参与后续筛选
2. 如果有关系事实命中问题关键词，只保留这些 keyword hits
3. 如果最高分大于 0，只保留 `score >= top_score - 3` 的近邻高分事实

因此，`citation_hits` 表示“从 Graphiti 返回的关系边里，和当前问题最贴近、且能映射回 episode 的事实命中项”。

`citation_hits` 的成员用于把图谱事实映射回本地 note：

- `episode_uuid`：支撑该事实的 episode
- `relation_fact`：关系事实文本
- `endpoint_names`：关系两端实体名
- `matched_terms`：命中的问题关键词
- `entity_overlap_count`：问题与实体重叠数量
- `score`：启发式相关性分数

随后 `_graph_matches_and_citations()` 会：

1. 用 `related_episode_uuids / citation_hits.episode_uuid` 反查本地 `KnowledgeNote`
2. 生成 `matches`
3. 把命中的 note 和 relation fact 组装为 `Citation`

### 3. Citation 的作用

`Citation` 是回答对外展示和校验用的轻量证据引用：

- `note_id`：引用的本地 note
- `title`：引用标题
- `snippet`：用于展示和校验的片段
- `relation_fact`：图谱关系事实，可为空
- `url`：网络搜索结果的 URL
- `source_type`：`note` 或 `web`

在图谱路径中，`relation_fact` 是很重要的成员：它把“图谱事实”与“本地原文片段”连接起来。回答生成时会优先使用图谱事实网络推理，同时用 `snippet` 做证据锚点。

### 4. 图谱回答生成与校验

当 `GraphAskResult.enabled=True` 时，运行时会构建图谱回答 prompt：

```text
question
+ working_context
+ graph entity/node summary
+ graph facts from fact_refs / edge_refs / citation_hits
+ anchored citations
+ note evidence snippets
```

然后调用 `_generate_answer()`。这里使用的不是 Pydantic 模型，而是配置里的 LLM 参数：

- `settings.openai_api_key`
- `settings.openai_base_url`
- `settings.openai_model`

`openai_model` 用于最终自然语言回答生成。Graphiti 客户端内部也会使用：

- `settings.openai_model`：Graphiti 抽取、搜索相关 LLM 能力
- `settings.openai_small_model`：传入 Graphiti 兼容客户端的小模型配置
- `settings.openai_embedding_model`：向量检索与 embedding
- `settings.embedding_api_key / embedding_base_url`：可覆盖 embedding 服务

生成后进入 `AnswerVerifier.verify()`：

- 校验 citation 是否能对应到 matches
- 计算 evidence score
- 判断证据是否充足
- 必要时 `_retry_if_needed()` 用 correction prompt 再生成一次

如果图谱答案校验通过，直接返回 `AskResult`。

### 5. 第二层：本地检索回退

如果图谱不可用，或图谱答案证据不足，ask 会回退到本地 LangGraph：

```text
build_ask_graph(store)
AgentState(mode="ask", question=question, user_id=normalized_user)
answer_node()
```

`answer_node` 会调用 `LocalMemoryStore.find_similar_notes()`：

- 把匹配笔记写入 `state.matches`
- 生成初始 `state.answer`
- 生成 `state.citations`

运行时随后会重新构建本地回答 prompt，将：

- 当前问题
- working memory 上下文
- 本地 `KnowledgeNote` 证据块
- `Citation` 片段

交给 `_generate_answer()` 生成更自然的回答。生成后同样进入 verifier 和 retry。

### 6. 第三层：网络搜索回退

当本地证据仍不足，且 `_web_search_available=True` 时，ask 会调用 `web_search` 工具。

网络结果会被转换为：

- `Citation(source_type="web", url=...)`
- `EvidenceItem(source_type="web", ...)`

回答 prompt 会明确要求说明信息来自网络搜索，并用来源编号标注。

### 7. EvidenceItem 的作用

`EvidenceItem` 是比 `Citation` 更统一的内部证据模型，用于收敛图谱、本地、chunk、web 和工具证据：

- `evidence_id`：证据项 id
- `source_type`：`graph_fact / note / chunk / web / tool`
- `source_id`：note id、edge id、url 等
- `title`：证据标题
- `snippet`：原文片段
- `fact`：图谱事实
- `source_span`：chunk 原文范围
- `url`：web 来源
- `score`：相关性分数
- `metadata`：额外结构化信息

ask 链路会把三层检索结果累计到 `all_evidence`：

```text
GraphAskResult -> graph_result_to_evidence()
local matches  -> notes_to_evidence()
web results    -> web_results_to_evidence()
```

`AskResult.evidence` 会把这些证据带回上层，为后续更丰富的 citation 面板、证据评分和高亮定位做准备。

### 8. AskResult 与历史记录

ask 最终返回 `AskResult`：

- `answer`：最终回答文本
- `citations`：展示和校验用引用
- `matches`：本地匹配到的 `KnowledgeNote`
- `evidence`：统一证据列表
- `session_id`：会话 id

返回前会调用 `MemoryFacade.record_turn()`：

- 优先写入 `AskHistoryStore`，也就是 Postgres 问答历史
- 如果 Postgres 未配置或失败，降级写入 `LocalMemoryStore.conversations.json`
- 同步刷新 `WorkingMemory.conversation_summary`
- 如果有 citations，会写入 `CrossSessionStore.recent_citations`，供后续删除知识等操作解析目标

## Capture 与 Ask 的模型流转对照

### Capture

```text
CaptureRequest / upload form
  -> CaptureService 提取正文
  -> RawIngestItem
  -> AgentState.raw_item
  -> KnowledgeNote / chunk_notes
  -> ReviewCard
  -> GraphCaptureResult
  -> KnowledgeNote 图谱字段回写
  -> CaptureResult
  -> CaptureResponse
```

### Ask

```text
AskRequest
  -> AgentState(question, user_id)
  -> GraphAskResult
  -> KnowledgeNote matches
  -> Citation
  -> EvidenceItem
  -> LLM 生成 answer
  -> verifier / retry
  -> AskHistoryRecord
  -> AskResult
  -> AskResponse
```

## 关键模型职责速查

| 模型 | 主要出现位置 | 核心职责 |
| --- | --- | --- |
| `CaptureRequest` | Web API | 接收文本采集请求 |
| `AskRequest` | Web API | 接收问答请求 |
| `RawIngestItem` | capture runtime | 承载待入库原始内容和来源 |
| `AgentState` | LangGraph | 在节点之间传递 capture / ask 中间状态 |
| `KnowledgeNote` | 存储、检索、回答 | 长期知识、chunk、图谱字段和原文证据的统一载体 |
| `ReviewCard` | capture | 为新 note 生成复习卡 |
| `GraphCaptureResult` | Graphiti 写入 | 表示图谱入库结果，并回写到 note |
| `GraphAskResult` | Graphiti 检索 | 表示图谱检索结果，是 ask 第一层证据来源 |
| `GraphCitationHit` | Graphiti 检索加工 | 将图谱关系事实映射回 episode / note |
| `GraphNodeRef / GraphEdgeRef / GraphFactRef` | 图谱字段 | 保存结构化图谱节点、边、事实 |
| `Citation` | ask 输出和 verifier | 轻量证据引用，面向展示和校验 |
| `EvidenceItem` | ask 内部证据层 | 统一表达 graph / note / chunk / web / tool 证据 |
| `CaptureResult` | runtime 输出 | capture 结果聚合 |
| `AskResult` | runtime 输出 | ask 结果聚合 |
| `AskHistoryRecord` | 历史存储 | 持久化问答历史 |

## 当前设计要点

- capture 的稳定主线是本地 note 入库并立即尝试 Graphiti 写入；图谱同步结果由 `graph_sync_status / graph_sync_error` 表达。
- ask 的主线是三层检索：图谱检索优先，本地笔记兜底，必要时网络搜索补充。
- `KnowledgeNote` 同时承担长期知识、原文证据、chunk 定位和图谱 episode 映射。
- `Graph*Result` 不直接暴露给前端，而是在 runtime 中转换成 `KnowledgeNote`、`Citation`、`EvidenceItem` 和最终回答。
- `Citation` 面向展示与轻量校验，`EvidenceItem` 面向更完整的证据追踪。
- `openai_model` 负责自然语言回答生成，也参与 Graphiti 的 LLM 能力；`openai_embedding_model` 负责图谱/语义检索的 embedding。
