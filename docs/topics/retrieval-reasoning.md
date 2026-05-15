# 检索与推理层说明

本文汇总当前项目检索与推理层的职责划分、当前能力、已知限制和后续改进方向。对应代码主要位于 [src/personal_agent/agent/runtime.py](../../src/personal_agent/agent/runtime.py)、[src/personal_agent/agent/verifier.py](../../src/personal_agent/agent/verifier.py) 和 [src/personal_agent/graphiti/store.py](../../src/personal_agent/graphiti/store.py)。

## 设计目标

检索与推理层负责让回答尽量基于个人知识库和图谱证据，而不是直接让 LLM 猜：

- 优先使用 Graphiti/Neo4j 图谱检索
- 图谱不可用时回退本地笔记检索
- 本地检索证据不足时回退到 Firecrawl 网络搜索
- 将 Graphiti 抽取出的 node / edge / fact 作为语义检索与推理主材料
- 将 chunk / note 原文片段作为证据出处和 citation 定位材料
- 将图谱事实、笔记片段和网络搜索结果组织成可追溯证据
- 生成回答后进行 verifier 校验
- 低置信度时尝试自修正或标注不确定性

## 组件分层

### 1. `GraphitiStore`

代码位置：[store.py](../../src/personal_agent/graphiti/store.py)

作用：

- 判断 Graphiti 是否配置可用
- 将 note 同步为 graph episode
- 通过 Graphiti search 查询相关节点和关系
- 生成 relation facts、entity names、episode UUIDs
- 支持删除 episode

#### 自定义本体与兼容层

自定义本体定义位于 [ontology.py](../../src/personal_agent/graphiti/ontology.py)，当前包含：

- `Person`
- `Project`
- `Concept`
- `Organization`
- `Source`

由于 DeepSeek 与 Graphiti 的结构化输出约定并不完全一致，项目增加了兼容层：

- [deepseek_compatible_client.py](../../src/personal_agent/graphiti/deepseek_compatible_client.py)
- [dashscope_compatible_embedder.py](../../src/personal_agent/graphiti/dashscope_compatible_embedder.py)
- [store.py](../../src/personal_agent/graphiti/store.py)

当前已兼容的常见差异包括：

- 列表根对象自动包装为 Graphiti 期望的对象结构
- `entity -> name`
- `type / entity_type -> entity_type_id`
- `facts -> edges`
- `source_entity / target_entity -> source_entity_name / target_entity_name`
- 字典式摘要转换为 `summaries: [{name, summary}]`
- DashScope embedding 单批限制自动分片

#### Graphiti 返回内容

Graphiti 原始接口主要在两类场景返回图结构结果：

1. 写入 note 时调用 `add_episode`
2. 问答检索时调用 `search_`

当前项目不会把 Graphiti 原始对象直接暴露给上层，而是转换成内部模型。

写入 note 后，Graphiti 的 `add_episode` 结果会包含：

- `episode.uuid`：本次写入生成的 graph episode 标识
- `nodes`：抽取出的实体节点
- `edges`：抽取出的关系边，每条边有 `fact`

项目将其包装为 `GraphCaptureResult`：

```text
enabled
error
episode_uuid
entity_names
relation_facts
related_episode_uuids
```

其中 `episode_uuid` 会回写到本地 `KnowledgeNote.graph_episode_uuid`，`entity_names / relation_facts` 会回写到 note 的图谱字段，`related_episode_uuids` 用于记录本次内容和既有图谱 episode 的关联。

当前 `_ingest_note()` 在 `add_episode` 成功后还会执行一次 `search_`：

```text
add_episode
  -> 写入当前 note
  -> 返回当前 episode_uuid / nodes / edges

search_after_ingest
  -> 用 note.summary 搜索用户图谱
  -> 从命中 edge.episodes 中收集历史 episode UUID
  -> 排除当前 add_episode 生成的 episode_uuid
  -> 填充 related_episode_uuids
```

这次 `search_` 不会修改 `episode_uuid / entity_names / relation_facts`，只用于补充 `related_episode_uuids`。Runtime 随后会用这些 UUID 反查本地 `KnowledgeNote.graph_episode_uuid`，并更新当前 note 的 `related_note_ids`。因此它的作用是“写入后关联笔记发现”，不是 Graphiti 入库的必要步骤。

问答检索时，Graphiti 的 `search_` 结果会包含：

- `nodes`：命中的实体节点
- `edges`：命中的关系边
- `edge.fact`：关系事实文本
- `edge.episodes`：支撑该关系边的 episode UUID 列表

项目将其排序、去重并包装为 `GraphAskResult`：

```text
enabled
error
answer
entity_names
relation_facts
related_episode_uuids
citations
citation_hits
```

其中 `answer` 不是最终自然语言回答，而是 Graphiti 检索摘要，主要包含最相关实体和关联事实；最终回答仍由 `AgentRuntime` 基于图谱事实、笔记证据和 working memory 重新生成。

`citation_hits` 是项目在 Graphiti `edges` 基础上加工出来的证据命中结构：

```text
episode_uuid
relation_fact
endpoint_names
matched_terms
entity_overlap_count
score
```

它的作用是把图谱关系事实映射回本地 note，并进一步生成 `relation_fact + snippet` 证据锚点。

#### 语义层与证据层的职责边界

当前检索与推理链路已经开始让 Graphiti 抽取出的 node / edge / fact 成为图谱问答的一等语义材料，而不是仅把 Graphiti 当成 episode 召回器。

当前长文 chunk 仍然有价值，但它的主要职责应收敛为“原文证据单元”：

```text
Semantic Layer
  -> Graphiti nodes / edges / facts
  -> 负责实体、关系、事实链、多跳推理和答案组织

Evidence Layer
  -> parent note / chunk note / source_span / original snippet
  -> 负责回查原文、citation、高亮定位和抽取结果校验
```

因此目标不是用 chunk 替代 Graphiti node，也不是彻底删除 chunk，而是把问答重心调整为：

```text
Graphiti node / edge / fact 主导召回、排序和推理
  -> episode UUID 回查 note/chunk
  -> 生成 relation_fact + snippet citation
```

这样可以利用 Graphiti 对文章进行语义切分后得到的知识单元，同时保留原文可追溯性，避免抽取事实丢失限定条件、代码块、表格、步骤和上下文语气后无法回查。

### 2. 本地检索

代码位置：[memory_store.py](../../src/personal_agent/storage/memory_store.py)

作用：

- 按用户列出本地 notes
- 基于简单 token 命中做相似检索
- 根据 graph episode UUID 反查 note

### 3. 回答生成

代码位置：[runtime.py](../../src/personal_agent/agent/runtime.py)

作用：

- 构造图谱回答 prompt
- 构造本地回答 prompt
- 注入 working memory 上下文
- 注入 citations、matches、relation facts 和 snippets

### 4. `AnswerVerifier`

代码位置：[verifier.py](../../src/personal_agent/agent/verifier.py)

作用：

- 校验 citation 是否指向真实匹配 note
- 计算 evidence score
- 识别兜底措辞
- 判断回答证据是否足够
- 支持传入统一 `EvidenceItem` 列表进行更丰富的证据评分

### 5. 统一 Evidence / Citation 模型

代码位置：[evidence.py](../../src/personal_agent/core/evidence.py)

作用：

- 定义 `EvidenceItem` 统一证据模型（`evidence_id / source_type / source_id / title / snippet / fact / source_span / url / score / metadata`）
- 提供 `graph_result_to_evidence()` — 将 `GraphAskResult` 转为 `EvidenceItem` 列表，含 episode→note 反查和 orphan 标记
- 提供 `notes_to_evidence()` — 将本地 `KnowledgeNote` 列表转为 `EvidenceItem`
- 提供 `web_results_to_evidence()` — 将 web search 结果转为 `EvidenceItem`
- 提供 `evidence_to_citations()` — 从 `EvidenceItem` 派生前端兼容的 `Citation` 列表

## 当前能力

- 已支持 Graphiti + Neo4j 图谱检索
- 已支持图谱不可用时本地链路回退
- 已支持图谱 relation facts
- 已支持保存 Graphiti node / edge / fact 结构化引用
- 已支持图谱回答 prompt 优先注入 Graphiti fact network，并将 note/chunk snippet 作为原文证据锚点
- 已支持 episode 映射综合 `citation_hits / fact_refs / edge_refs / related_episode_uuids`
- 已支持 note snippet citation
- 已支持 `relation_fact + snippet` 证据锚点
- 已支持回答后 verifier 校验
- 已支持低置信度自修正和不确定性标注
- 已支持删除目标解析时利用图谱 episode、本地相似检索、关键词和 recent citations
- 已支持 ask 三层检索回退（图谱 → 本地 → 网络搜索）
- 已支持 Graphiti 写入后通过 `search_after_ingest` 发现 related notes（非关键步骤，失败不影响核心图谱同步）
- 已支持长文 parent + chunk 检索单元：`parent_note_id / chunk_index / source_span`
- 已支持 chunk note 独立后台图谱同步（capture 设 `graph_sync_status="pending"`，API 层 background_tasks 调用 `sync_note_to_graph()`）
- 已支持级联删除时清理 chunk 的 graph episode
- 已支持相似检索按 parent 去重，并在回答证据中区分 parent summary 与 chunk content
- 已补基础回归样本：`test_verifier.py` 覆盖 web citation 计分与孤儿 citation，`test_plan_executor.py` 覆盖 resolve 多级回退和 `relation_fact + snippet` 相关执行路径
- 已实现统一证据模型 `EvidenceItem`（`core/evidence.py`），将 Graphiti `fact_refs / edge_refs / citation_hits`、本地 note/chunk、web 搜索结果和工具结果收敛为可追踪证据结构
- `ToolResult` 已扩展 `evidence` 字段，`graph_search / web_search` 工具返回统一证据
- `RuntimeAskMixin.execute_ask()` 已积累三层检索的 `EvidenceItem`，`AskResult.evidence` 随 API 响应返回
- `AnswerVerifier.verify()` 已支持可选 `evidence` 参数，基于 evidence 类型和 orphan 状态增加证据充分性评分
- `ReActStepRunner` 已支持在迭代间传递 `evidence`，每次 `ReActIteration` 保留工具返回的证据

## 已知限制

### 1. Graphiti 语义结果仍需更深层推理规划

当前问答 prompt 已经优先注入 `node_refs / edge_refs / fact_refs / citation_hits` 形成图谱事实网络，并用 note/chunk snippet 作为出处锚点。但事实网络的多跳路径选择、冲突事实处理、时间线排序和跨 episode 证据合并仍偏启发式。

后续需要进一步把 node / edge / fact 的检索规划从 prompt 组织升级为更明确的 graph reasoning planner。

### 2. ask 检索排序仍偏启发式

当前图谱结果和本地结果已经可用，但复杂问题下的 rerank、证据合并和多跳推理仍有提升空间。

### 3. verifier 是轻量规则校验

`AnswerVerifier` 主要基于 citation 有效性、匹配数量、图谱加分和兜底措辞计算 evidence score。它不是完整事实校验器，也不会深入判断关系事实是否逻辑一致。

### 4. 复杂推理能力仍有限

当前更擅长基于已有 note 和 graph facts 组织答案。跨多个实体、多个时间点、多条关系的推理仍需要更强的检索规划和证据组合。

### 5. chunk 级 Graphiti episode 已支持后台同步

chunk note 现已支持独立图谱同步：capture 阶段对每个 chunk 设 `graph_sync_status="pending"`，API 层 background_tasks 对每个 chunk 独立调用 `sync_note_to_graph()`（含重试/退避）。chunk note 可获得独立的 `episode_uuid / entity_names / relation_facts`，图谱搜索命中后 episode 反查可达章节级。

级联删除时也会清理 chunk 独立持有的 graph episode。

后续 chunk 的定位应更明确地作为 evidence/source 层能力存在：保留 parent note 全文与 chunk 的 `source_span`，让 `relation_fact` 能精确定位到 chunk 内段落，但不要让 chunk snippet 取代 Graphiti facts 成为主要推理材料。

### 6. `search_after_ingest` 已降级为非关键步骤

`search_after_ingest` 已用 try/except 包裹：成功时正常生成 `related_episode_uuids`，失败时记录 warning 日志并将 `related_episode_uuids` 设为空列表，不影响 `add_episode` 的结果返回。`related_note_ids` 在搜索失败时保持为空或已有值。

### 7. Graphiti nodes / edges 已进入本地知识模型

`KnowledgeNote` 已新增 `graph_node_refs / graph_edge_refs / graph_fact_refs` 结构化字段，保留 Graphiti 的节点 UUID、类型标签、摘要、边的方向和 episode 归属。原有的 `entity_names / relation_facts` 字符串字段保留用于向后兼容。

`GraphCaptureResult` 和 `GraphAskResult` 同步携带 `node_refs / edge_refs / fact_refs`，`_merge_graph_capture` 会将结构化引用写入本地笔记。`_build_graph_answer_prompt` 已升级为在实体名称旁附带节点摘要。

### 8. verifier 重试链路存在结果重复计算

`execute_ask()` 当前会先 `verify` 初版回答，再调用 `_retry_if_needed()`，最后再次 `verify` 终版回答。这个流程语义上是合理的：初版校验用于生成 correction prompt，终版校验用于决定是否标注不确定性、记录分数和触发 web fallback。

`_retry_if_needed()` 现已返回 `RetryResult(answer, verification, attempts)`，外层不再需要重复计算终版 `VerificationResult`。`web_enabled` 上下文参数已补齐，web citation 场景的校验上下文与 retry 内重校验一致传递。

## 演进方向

- 增强图谱 rerank：综合 edge score、entity overlap、fact relevance、episode freshness 和 source confidence
- 引入稳定 rerank 和评测样本
- 基础 citation / relation fact / snippet 回归样本已补，继续扩展更细粒度的质量评测
- 增强多跳推理和证据链可视化
- 将 evidence 从回答生成、verifier 扩展到前端 citation 面板和高亮定位
