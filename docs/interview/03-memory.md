# 记忆层

### 1. 你怎么区分短期记忆和长期记忆？

项目里实际有三类记忆。

短期记忆是当前 thread 的执行现场，由 LangGraph checkpoint 承载，包括 `messages`、plan、react、tool tracking、events、pending confirmation 等。它用于理解当前任务、恢复执行、继续多轮对话。

长期记忆是用户明确 capture 或 solidify 后写入的正式知识，由 Postgres `knowledge_notes` 和 `review_cards` 承载。它才是可反复检索和引用的业务知识。

情景记忆是每次 entry run 结束后系统自动沉淀的 `MemoryEpisode`，记录这次任务的意图（`workflow`）、结果（`outcome / summary`）、关键决策（`decisions`）和待办（`open_items`），由 `episodic_memory.record_entry_episode` 写入 `memory_episodes` 表。它不是事实知识，而是"做过什么"的行为轨迹。这是 best-effort 写入：整段包在 try/except 里，写失败只记日志、不影响主 run 结果。

此外还有第四类 `MemoryItem`（`memory_items` 表）：当一次 run 的 `outcome` 是 failed/cancelled 或带 errors 时，`record_entry_episode` 会同时沉淀一条 `memory_type="reflection"`、`status="candidate"` 的反思记忆（也支持 `procedural` 程序性记忆）。它是"从失败里学到的教训"候选，需后续从 candidate 确认为 confirmed 才生效，避免未经验证的反思直接污染回答。

一句话：checkpoint 管现场，`knowledge_notes` 管事实，`MemoryEpisode` 管做过什么，`MemoryItem` 管从中沉淀的反思 / 程序经验。

### 2. 为什么 checkpoint messages 不能直接当长期事实库？

因为对话历史里混有用户事实、用户临时想法、助手推测、错误回答、废弃方案和未验证判断。如果直接把聊天记录当事实库，后续回答很容易把“助手曾经说过”误当成“真实事实”。

所以项目里同一 thread 的 `messages` 是短期真源，只用于理解上下文和恢复任务；长期事实必须经过 capture 或 solidify 后进入 `knowledge_notes`。

### 3. `knowledge_notes` 为什么要设计 parent/chunk 两层？

parent note 表达文档级或主题级知识，chunk note 保存片段证据、原文定位和 citation 单元。这样可以避免把长文直接塞进 prompt，也能在回答时从命中的 chunk 回溯到 parent note。

这种结构同时服务检索和引用：检索可以命中细粒度片段，用户可见引用又能回到清楚的来源。

### 4. Graphiti 是不是长期事实真源？

不是。Graphiti 在项目里是语义索引层，负责实体、关系、episode 和 fact 检索。长期事实真源仍然是 Postgres 的 note/chunk。

Graphiti 可以帮助找到语义关系，但回答需要引用原文或业务真源时，仍要回到 `knowledge_notes` 和 chunk 证据。这样做可以避免图谱抽取结果漂移后替代原始知识。

### 5. EvidenceItem / ContextPack 解决了什么问题？

它们把不同来源的上下文统一成回答前的证据出口。不同 evidence source 提供的价值不一样：

- `note`：提供长期知识的主题级信息，例如标题、摘要、用户保存的完整知识背景，适合回答“这个知识点整体是什么”。
- `chunk`：提供更细粒度的原文片段、`source_span` 和 citation anchor，适合支撑精确引用，避免只拿 parent summary 生成泛泛回答。
- `graph_fact`：提供 Graphiti 抽取出的实体、关系和事实边，适合发现跨文档关系、多跳线索、人物 / 组织 / 项目之间的连接。
- `episode`：提供情景记忆证据，即过往 entry run 沉淀的 `MemoryEpisode`（意图、结果、决策、待办），适合回答"我上次让你做了什么""那个任务后来怎么样了"这类基于历史行为的问题。
- `web`：提供外部公开信息或时效性信息，适合本地知识不足、需要最新资料或用户明确要求联网时补充证据。虽然 `web_search` 在执行层是一个工具，但它产出的证据来源是公网网页，所以进入 evidence 层时标记为 `web`，而不是 `tool`。
- `tool`：这是 evidence schema 预留的工具结果来源类型，适合未来把内部 API 查询、计算工具输出、业务系统状态等"非网页、非本地笔记、非图谱事实"的工具结果纳入回答证据。当前生产 Ask 主链路主要使用 `note / chunk / graph_fact / episode / web`；如果禁用 web search，通常不会再出现 `tool` evidence。
- `procedural / reflection`：来自 `MemoryItem`（`memory_items_to_evidence`），分别是程序性经验和反思教训。它们不是默认主链路证据，按需注入，且 `reflection` 在打分里权重最低。

`EvidenceItem.source_type` 的完整取值是 `graph_fact / note / chunk / web / tool / episode / procedural / reflection` 共 8 类。

这些来源底层结构完全不同：Postgres note/chunk、Graphiti fact、情景 episode、web hit、tool artifact 都不是同一种对象。如果直接塞进 prompt，排序、去重、预算控制和引用都会很乱。

所以项目先把它们归一成 `EvidenceItem`，保留 `source_type / source_id / title / snippet / fact / score / metadata` 等通用字段，再由 `ContextPack` 做去重、排序和字符预算裁剪。只有 selected evidence 会进入 prompt，用户可见 citations 也从 selected evidence 派生，避免“模型看见的内容”和“用户看到的引用”不一致。

### 6. 如果历史摘要和当前证据冲突，信哪个？

信当前 evidence、工具结果或长期记忆检索。短期摘要只帮助理解对话线索，例如用户目标、已确认选择、待办状态，不能作为事实证据。

项目里已经把摘要做成结构化 `ThreadSummary`（`core/models.py`）：它把 `user_goals / user_constraints / confirmed_decisions / pending_tasks / open_questions / assistant_assumptions / unverified_claims / evidence_refs` 分字段保存，随 LangGraph checkpoint 持久化，prompt 渲染时显式区分"已确认用户状态"和"助手假设 / 未验证声明"，并声明摘要不是既定事实。这样就把"摘要可能把助手推测压缩成确定表述"的风险结构化地隔离开。剩余待补的是摘要漂移、字段误分和长会话增量稳定性的质量评测。

### 7. `solidify_conversation` 如何避免把助手猜测写入长期知识？

当前做法是先通过 `compose` 从 checkpoint 对话中生成草稿，再通过 `capture_text` 写入长期知识。如果没有足够明确的知识正文，compose 会失败，不写入。

结构化 `ThreadSummary` 已经落地，把用户明确事实、已确认决策、助手假设、未验证声明分字段保存，这给 solidify 提供了区分"该写"和"不该写"的结构化依据。但 compose 当前还没有强制只消费 confirmed 字段、对 `assistant_assumptions / unverified_claims` 默认不写入，所以仍是一个风险点。更成熟的方向是让 compose 显式只采信 ThreadSummary 的已确认部分，对助手推测和未确认方案默认跳过，必要时向用户澄清。

### 8. 如果同一主题有新旧冲突记忆，现在怎么处理？未来怎么设计？

当前项目已经落地知识版本链和冲突消解的基础机制，不是空白。

- 重复采集：`source_fingerprint`（`ingestion_pipeline.py` 用 `sha256(source_type+ref+normalized_text)`）在 capture 入口先查重，命中即跳过，避免同一来源反复入库。
- 版本链：`NoteVersion`（`core/models.py`）带 `version`、`status`（`current/superseded/deprecated/conflicted`）、`topic_key`、`supersedes_note_ids`、`superseded_by_note_id`、`conflict_note_ids`。
- supersede：`MemoryFacade.supersede_note` 把旧 note 标 `superseded` 并双向链接，新 note `version+1` 并继承 `topic_key`。
- 冲突标记：`MemoryFacade.mark_notes_conflicted` 把多条 note 标 `conflicted` 并互填 `conflict_note_ids`。
- 检索端消费：evidence 选择阶段直接丢弃 `superseded/deprecated`，对 `conflicted` 扣分、对过期 stale 降权，避免旧知识被当最新事实引用。

所以现在已经能做"同一主题的新版本替换旧版本、冲突标记并在回答时降权"。还没补齐的是**自动冲突检测**（目前 supersede / conflicted 需要显式触发，缺少基于语义的自动发现）、**来源可信度模型**和**回答时的显式冲突提示**。更成熟的方向是引入置信度、时间新鲜度评分和检测到冲突时主动向用户澄清。

### 9. 情景记忆（MemoryEpisode）和长期 note 有什么区别？为什么不直接把对话结论 capture 成 note？

两者承载的东西不同。长期 note 是"事实/知识"，是用户明确要长期保存、可被反复引用的内容。情景记忆是"行为轨迹"，记录某次 entry run 的意图、结果、决策和待办，回答的是"我让你做过什么、那件事后来怎么样"。

不直接 capture 成 note 的原因是：情景记忆是系统对每次 run 的自动沉淀，不需要用户显式确认；如果都写成 note，会把大量"任务流水"混进事实知识库，污染检索和引用。所以情景记忆走独立的 `MemoryEpisode`，并在 evidence 层用独立的 `episode` 来源类型标记，与 `note/chunk` 区分开。

### 10. 情景记忆什么时候被检索？怎么判断一个问题需要它？

ask 前的 query understanding 会判断 `needs_episodic_context`。除了 LLM 理解，`query_step_projector.py` 还内置 `_looks_like_episodic_query` 启发式作为兜底（命中"上次/之前/做过/继续/那个任务"等历史行为标记词时置真）。当问题指向用户自己的历史行为时，系统才会把 `MemoryEpisode` 转成 `episode` evidence 进入排序。

这样设计是为了避免情景记忆污染事实类回答：问"光合作用原理"不应该把"上周你帮我整理过笔记"这种轨迹翻出来。情景记忆只在与历史行为相关时才作为证据，且在 evidence 排序里和 note/chunk 一起按相关度竞争预算。

### 11. 情景记忆具体存在哪里？检索是怎么做的？

存在 **Postgres 的 `memory_episodes` 表**，和长期知识的 `knowledge_notes`、复习卡 `review_cards` 同库不同表。整条 `MemoryEpisode` 序列化成 `payload`（JSON）存一列，另有一列 `search_text` 供检索。

要点是它**不进 LangGraph checkpoint，也不进图谱**：checkpoint 存的是当前 thread 的短期执行现场，图谱（Neo4j）存的是实体关系，情景记忆是独立的一张 Postgres 业务表，生命周期跨 run、跨 session 持久保留。失败时附带产生的 reflection 候选则存另一张表 `memory_items`。

检索用的是 **ParadeDB BM25 全文检索**（`search_episodes` 对 `search_text` 列做 `paradedb.match`），不是向量检索，取 top 5，且 **session 优先、全局兜底**——先限定当前 session 搜，搜不到再放宽到该 user 全局。这里要诚实标注一个边界：BM25 是词法匹配，问法和记录用词差太远可能漏召回，没有语义向量召回兜底。

### 12. 为什么情景记忆不用 LLM 生成摘要？

因为它是"记账型"任务，不是"理解型"任务。`build_entry_episode` 从头到尾是**确定性字段抽取**——从 `EntryResult` 的 events、execution_trace、capture_result 里取意图、工具名、note_id、决策事件，用模板拼成 title / summary，没有任何 LLM 调用。理由有四层：

- **记的是客观发生了什么，不需要再创作**：这次 intent 是什么、调了哪些工具、碰了哪些 note、结果是 completed 还是 waiting_confirmation，这些字段在 `EntryResult` 里已经是确定的。LLM 摘要反而会引入改写、漏字段甚至幻觉，确定性抽取保证"记的就是真发生的"。
- **写入在主链路关键路径上，不能拖慢、不能失败**：`record_entry_episode` 在每次 `execute_entry / resume_entry` 结束后同步调用。加一次 LLM 调用就给每个请求多付一次延迟、成本和失败点；纯 Python 抽取才能做到又快又不影响主流程（它本身是 best-effort 记账，包在 try/except 里）。
- **成本与价值不匹配**：情景记忆是每一次 run 都写，量大、单条价值低、多数永远不会被检索到。给每条任务流水都跑一次 LLM 摘要，成本线性爆炸。
- **可复现、可测试**：同样的 `EntryResult` 永远产出同样的 episode，单测好写、行为可预测。

正好有个反例印证：同在记忆层的**短期对话摘要 ThreadSummary 确实用 LLM**，因为那是要把多轮对话理解、压缩、分桶（用户目标 / 已确认决策 / 助手假设 / 未验证声明），是理解型任务，确定性抽取做不了。所以这是**按任务性质分配**——需要理解力的地方（对话压缩、事实固化）用 LLM，记账型的情景沉淀不用。

### 13. 情景记忆只在 ask 分支用，如果 router 没路由到 ask 怎么办？

先说为什么只在 ask 用：因为情景记忆是"证据"，而只有 ask 是"基于证据回答问题"的分支。其他分支要么是写入动作（capture / delete / solidify），要么数据来自 checkpoint（summarize_thread），都不需要历史证据。而**"问起历史行为"这件事本身就会被 router 判成 ask**——用户问"之前那个任务成功了吗"，router 不会路由到 capture 或 delete，而是 ask，然后 ask 内部的 query understanding 再判 `needs_episodic_context`。所以"只在 ask 用"和"历史行为类问题走 ask"是自洽的，检索条件和它该出现的分支天然对齐。

但这确实有脆弱点，要诚实讲：

- **强依赖两道 LLM 判断串联**：命中链路是 `router 判 ask` → `query understanding 判 needs_episodic_context`，任何一道误判都会让历史召回失效，且没有 fallback。
- **`direct_answer` 是盲区**：这个分支走小模型，上下文只来自当前 thread 的对话消息，**完全不调 `search_episodes`，也不读长期 note**。如果一个本应进 ask 的历史问题被 router 误分到 direct_answer，这条问题就拿不到情景记忆，只能靠当前对话窗口回答。
- **全工程只有一个消费点**：`search_episodes` 只在 `runtime_ask.py` 被调用，没有"任何分支都先查一遍历史"的公共前置。

所以准确口径是：**"只在 ask 用"是基于"历史问题都会走 ask"这个假设的合理简化，假设成立时没问题；代价是把正确性押在了 router 分类上，direct_answer 是这个假设破裂时唯一会漏的地方，目前无兜底。** 修复方向是给 direct_answer 加一次轻量 episodic 检查，或把"历史行为类问题"的路由召回率作为专门 eval 指标盯住。

---

[← 返回索引 INDEX.md](INDEX.md)
