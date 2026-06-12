# 深入追问（检索 / 编排 / 治理 / 可靠性）

这一节集中放面试官容易在细节上深挖的问题，答案都对应当前真实代码。

### 1. evidence 的预算（char_budget 5000、max_items 12）怎么定？预算不够时会丢关键 chunk 吗？

预算是为了控制进 prompt 的上下文规模和成本。`select_ranked_evidence` 先按启发式分数降序排，再按字符预算和条数上限裁剪，分成 `selected` 和 `dropped`。

会不会丢关键 chunk 取决于排序质量：因为是先排序再裁剪，理论上低分项才被丢。风险点是启发式打分如果不准，可能把关键 chunk 排到预算外。所以这里依赖 query understanding 的 filters 和 rerank 把真正相关的 chunk 顶上去，必要时再用 LLM rerank 替代纯启发式。预算和上限都是可调参数，不是写死的业务约束。

### 2. evidence 排序是启发式还是 LLM？打分维度有哪些？

默认是启发式打分（`_rank_evidence_item`，`core/evidence.py`），维度包括来源类型权重、term overlap（`×0.12`，上限 0.48）、是否命中 query filters、是否过期或冲突（conflicted 扣 0.18、stale 降权、orphan 扣 0.12、superseded/deprecated 扣 1.0 并在选择阶段直接丢弃）、freshness bonus（带 `published_at` 的 +0.04）等。来源类型权重从高到低是 `chunk(0.22) > note(0.18) > graph_fact(0.16) > web(0.14) > episode(0.13) > procedural(0.12) > reflection(0.11) > tool(0.10)`。LLM rerank 作为可选策略存在，evals 里专门对比过 heuristic 和 LLM rerank 的效果。

这样设计的考虑是：启发式便宜、可解释、无额外延迟，适合主链路默认；LLM rerank 留给确实需要更高排序质量的场景，由 eval 决定是否值得开启。

### 3. query_planner 拆出的子查询是并行还是串行检索？结果怎么合并？

要分两层说，因为"并行"在这条链路里有两个不同含义。

第一层是**检索源之间的并行**。`RetrievalPlan` 有个 `parallel` 标志，当同时需要 graph 和 local 两个源时为 true。此时主查询用 `ThreadPoolExecutor(max_workers=2)` 把 graph 检索和 local 检索并行跑（graph 超时 60s、local 超时 30s），否则退化为串行依次跑。这是"源并行"。

第二层是**子查询（sub_queries）的检索，目前是串行**。`runtime_ask.py` 里是 `for sub_q in retrieval_plan.sub_queries:` 顺序循环，每个子查询依次做一次 graph 检索（子查询当前只扩展 graph 这一路，不重复跑 local），结果合并进同一个证据池。所以多跳拆分出来的 2-3 个子查询不是并发执行的。

结果合并不是简单拼接：每路检索（主查询 graph/local + 各子查询 graph）产出的 matches、citations、evidence 都通过 `_merge_notes / _merge_citations` 汇入同一个 `all_evidence` 池，最后由 `build_context_pack` 统一做跨来源去重（按 source_type + source_id/url + fact + snippet 前缀）、排序和预算裁剪。

坦诚的边界：子查询串行是当前实现的一个性能短板。子查询之间相互独立、没有数据依赖，完全可以像主查询的源并行那样用线程池并发，这是一个明确的优化点；之所以还没做，是因为子查询通常只有 2-3 个且只走 graph 一路，串行延迟可接受，没有优先级压力。

### 4. 几路检索分别能检索什么？怎么互补？默认实际启用哪几路？

先纠正一个容易说错的口径：它们不是"三路对等的数据源"。准确说有两个真正不同的数据存储（Postgres note/chunk、Neo4j 图谱），外加 web 和 episode 两条补充流；structural 不是独立数据源，而是和 local 共享同一批 note 的另一种召回策略。

各自检索对象：

- **local**：查 Postgres `knowledge_notes`，是混合检索——pg_search (ParadeDB) BM25 词法召回（用 pg_search 自带中文 tokenizer 分词）+ 128 维向量余弦（HNSW 索引），两路用 RRF 融合，再叠加 metadata filter（source_type/tag/时间/parent_id）。命中 chunk 后会扩展到 parent note 和相邻 chunk。它擅长"按内容相似度找到最相关的笔记片段"，是检索的通用底座。
- **graph（Graphiti）**：查 Neo4j，返回实体节点、关系边/fact、episode，BFS 跳数可配。它擅长 local 给不出的东西——多跳关系、"A 和 B 怎么关联"、跨文档的实体连接。命中的 episode 再映射回 Postgres note 做引用锚点。这是和 local 真正正交的互补：不同存储、不同对象粒度。
- **structural**：读的是**和 local 同一批 `knowledge_notes`**，在内存里按 parent→section 层级建索引，做 TF-IDF 风格的词项 IDF 打分，并在父文档和子片段之间传播分数。它和 local 的区别不是数据源，而是召回机制——local 偏语义/词法混合，structural 偏确定性的结构化宽召回。
- **web**：外部公网时效信息，本地不足或要求联网时补充。
- **episode**：当 `needs_episodic_context` 命中时，对 `memory_episodes` 表做全文/三元组检索，召回过往任务轨迹。

互补关系要分两类讲清楚：

- graph vs local 是**真互补**：不同存储、不同粒度（关系 fact vs 内容片段），一个回答"它们怎么关联"，一个回答"最相关的原文是什么"。
- local vs structural 是**召回策略的多样性**，不是数据互补：同一批 note，两种排序口径，目的是 hybrid 模式下用 structural 的确定性宽召回兜住 local 向量召回可能漏掉的项。这也是为什么它们被设计成"融合"而不是默认并排跑。

默认实际启用哪几路要诚实说：默认 `graph_provider=graphiti` 配置下，主链路只跑 **graph + local 两路并行**，web 按需触发，episode 按需触发。structural 只有在显式配 `graph_provider=structural` 或 `hybrid` 时才进 graph 这个槽位，目前主要用于 evals 对比。所以面试里不要说"系统同时跑三路检索"，准确表述是"默认 graph+local，structural/web/episode 按 provider 配置和 query 信号条件启用"。

融合发生在 evidence 层而非检索层：每路产出统一成 `EvidenceItem` 后进同一个 `ContextPack` 去重、排序、预算裁剪。各检索器只负责召回自己擅长的，融合逻辑集中在一处。evals 里 `test_retrieval_strategies.py` 专门用 MRR/Recall 对比 local、graphiti、structural、hybrid，hybrid 是否更优是测出来的，不是默认假设。

### 5. 这么多检索手段，不会有冗余和冲突问题吗？

会，这是这套设计必须正视的代价，应该坦诚讲清楚现在做到了什么、还没解决什么。

先说冗余。冗余确实存在，有几个原因：local 命中 chunk 后会主动扩展 parent + 邻居 chunk；graph 命中的 episode 又会映射回同一批 note；hybrid 模式下 structural 和 local 读的是同一批 `knowledge_notes`。所以同一条知识很可能从多路重复进入证据池。

当前的去重是两层，但**不彻底**：

- 入池前 `_dedupe_evidence_items` 按 `(source_type, source_id 或 url, fact, snippet 前 180 字)` 去重。
- 选择进 prompt 时再按 `(source_type, source_id 或 url 或 title)` 做 diversity 二次去重，且只对 `note/chunk/web/episode` 生效，`graph_fact` 不参与 diversity 去重。

关键边界要主动点破：这两层去重的 key 都**带 source_type**。也就是说同一条 note 如果从 local 进来标 `note`、又通过 graph episode 映射进来也标 `note`，能去重；但如果一路标 `chunk`、另一路标 `note`（parent 和它的 chunk），或者 graph 把它表达成 `graph_fact`，source_type 不同就不会被判为重复。所以现在能消除"完全同源同型"的重复，但消不掉"同一知识的不同表述形态"。真正彻底的做法应该是引入跨来源的内容指纹或 parent_note_id 归并，这是已知待补项。

再说冲突，要分两种：

- **版本冲突**（同一主题新旧笔记矛盾）：已经有处理。evidence 打分里 `version_status=conflicted` 扣 0.18，`superseded/deprecated` 直接扣 1.0 并在选择阶段丢弃，`orphan`（graph 命中但 note 已删）扣 0.12。这是结构化、可解释的降权。
- **内容冲突**（local 说 X、web 说非 X，两条都是 current 版本）：**目前基本没有专门处理**。系统不会检测两条证据在事实上互相矛盾，只是把它们按各自分数排进同一个 prompt，最终由回答模型权衡。文档里追问型问题对 web vs 本地、graph 孤儿给了口径（按问题类型选信源、降权无法回溯的 graph fact），但这是**回答策略**层面的引导，不是检索层的冲突检测。

所以诚实的总结是：冗余靠 dedupe + diversity + 预算裁剪部分兜底，但跨形态去重不彻底；版本冲突有结构化降权，内容冲突还依赖打分排序和回答模型自行权衡，没有显式的冲突检测和"证据互斥提示"。这也正是为什么默认只开 graph + local 两路、不默认全开 structural——多开一路召回，冗余和潜在矛盾的治理成本就上升一截，在去重和冲突机制还没做厚之前，控制召回路数本身就是一种风险控制。

这个判断不是拍脑袋，evals 里有数据支撑（见 `docs/rag-eval-results.md`，30q 评测集）：

- **多开一路召回不是线性收益**。MultiHopRAG 上把 graph 单路换成 structural + graphiti 的 hybrid，overall 只从 MRR 0.422 微升到 0.434、R@10 0.706 升到 0.733，但同时 R@5 从 0.686 跌到 0.644、NDCG@5 从 0.365 跌到 0.346。也就是说多召回一路把更多正确 evidence 推进了 top10，却让前 5 名的排序质量变差——冗余候选挤占了高位。结论写得很直白：多跳仍需要 source-aware MMR / set coverage reranker，而不是简单扩大候选池。
- **放宽预算让冗余进来，指标反而更差**。把 ContextPack 从 12 项/5000 字放宽到 24/12000，每 query 平均 match 只从 4.8 升到 5.9，但所有指标下降（MRR 0.375 → 0.283，R@5 0.681 → 0.614），21 条非空 query 里 better=0 / worse=4。其中 2 条返回了更多 match 却命中更少 expected，说明 rerank 在更大的混合候选池里把正确 evidence 排出了 top-k。这正是"冗余不解决问题、反而稀释排序"的实证。
- **不同来源的偏好甚至互相打架**。按 question_type 看，hybrid 让 comparison_query 的 MRR 从 0.333 提升到 0.667，却让 temporal_query 从 0.905 掉到 0.762——同一套融合权重，对一类问题是补充、对另一类就是干扰。单一权重无法同时服务多类问题，这是"多路不天然互补"最直接的证据。
- **裁剪确实会系统性丢证据**。端到端 `current_runtime_ask` 的 MRR（0.375）显著低于 retrieval-only 的 graphiti_hybrid_rrf（0.589），diagnostics 显示端到端每 query 平均只保留约 4.8 个 match，而多跳 set-recall 需要凑齐 2-4 篇 evidence，被裁到 ~5 个的最终池会丢尾部 evidence。这说明去重+预算裁剪不是没有代价，它在多跳场景下会牺牲召回完整性。

所以面试里可以这样收口径：我不是简单堆检索手段，evals 已经证明"多召回一路、放宽预算"在多跳上不必然变好，真正的瓶颈是混合候选池的排序/融合质量，而不是召回数量——这也是为什么默认保守地只跑 graph + local，把 structural/hybrid 留给有 eval 验证的场景。

往生产走，这里要补的是：跨来源内容指纹去重、按 parent_note_id 归并不同形态、source-aware MMR 或按 query_type 调权的融合（而不是直接合池丢给 LLM rerank）、检测高分证据之间的事实矛盾并在回答里显式提示分歧，而不是让模型默默挑一个。这些方向在 `rag-eval-results.md` 的"下一步"里也已列为待办。

### 6. 要加一个新 intent（比如"更新知识"），改动面有多大？

因为 workflow 是声明式 frozen 的，主要改动集中在几处：在 router 加 intent 分类与默认决策；在 `workflow.py` 的模块级 `_build_registry()`（构造 `WORKFLOW_REGISTRY`）里声明新的 `WorkflowSpec`（节点、依赖、风险、HITL、projection_policy）；如果涉及新工具，在工具层注册并补 args schema 和 governance；如果需要步骤执行，PlanValidator 加 intent 特定规则；最后补 eval。新声明的 spec 还会被 `WorkflowSpecValidator` 和 `validate_registry_against_capabilities` 两道 spec 层闸门检查（对真实注册表跑断言，见 `tests/test_workflow_validator.py`），所以"加一份声明"必须同时通过 spec 自洽与工具能力一致性校验。

这个边界是刻意的：流程拓扑集中在 WorkflowRegistry 一处声明，LLM 不能临场发明控制流，所以加 intent 是"加一份声明 + 接治理"，而不是改散落各处的 if-else。

### 7. projection_policy 为什么只给 delete/solidify 开，ask 为什么不投影成 PlanStep？

因为只有需要步骤状态、HITL 确认或 checkpoint 恢复的 workflow 才值得付出 PlanStep 投影的成本。delete 要确认和恢复，solidify 要先 compose 再 capture，这些都需要可展示、可恢复的步骤图。

ask、capture、direct answer、summarize 有直接 Graph 分支和 `execution_trace`，不需要额外步骤状态。给它们也投影成 PlanStep 只会增加无谓的状态管理开销，所以默认 `projection_policy="none"`。

### 8. 真要做开放式 autonomous planner，怎么加 guardrail？和 PlanValidator 什么关系？

PlanValidator（`StepProjectionValidator`）现在校验的是确定性投影出来的步骤图：步骤类型、依赖环、工具注册、args schema、风险等级、ReAct 越权、intent 规则。它本身就是 guardrail 的核心。它之上还有一层更早的闸门：`WorkflowSpecValidator` 在 spec 声明期就把 delete_longterm 必须 high+confirmation+hitl 这类不变式拦在源头，所以非法流程在变成 PlanStep 之前就过不了。

如果引入 autonomous planner，它生成的计划仍然必须过同一个 PlanValidator，再加几道：限制可组合的工具集（只允许低风险只读）、要求每条计划可映射到已知能力、必须有 eval 覆盖、高风险动作仍走 HITL。也就是说 autonomous planner 只是换了"谁生成计划"，校验、确认、审计这套边界不变。

### 9. PolicyEngine 的规则是硬编码还是可配置？

引擎规则是代码里的判定逻辑（owner 校验、高风险确认、react 守卫、deny 等），但接受 `Settings.policy` 注入的 `PolicyRules` 做可配置覆盖，比如 allow/deny 名单。`AgentRuntime` 从 `Settings.policy` 构造规则并把同一个 engine 注入工具层和记忆层。

诚实口径是：现在是"固定判定骨架 + 可配置覆盖"，还不是完整的策略 DSL 或规则引擎。workspace/tenant、RBAC/ABAC、更细的来源策略还要继续补。

### 10. owner 校验依赖 user_id，不传 user_id 就跳过，这算不算越权口子？

是一个需要正视的边界。当前实现里写/更新路径只有 `user_id` 非空才做 owner 校验，单用户或内部调用场景下可以接受，但做多用户 SaaS 时必须改成强制要求 user_id，缺失即拒绝，而不是跳过。这正是文档里"多租户权限还需补齐"的具体体现之一。

### 11. checkpoint resume 后，工具执行到一半（graph 删了 note 没删）怎么保证一致性？

当前主要靠两层：幂等（`idempotency_key` 防止确认动作重复执行）和步骤状态（`PlanStepState` 记录每步做到哪、失败没失败、重试几次）。delete 的真正删除发生在确认 resume 之后，且 `delete_note` 会删 note、chunk、review card 和可用的 graph mapping。

但跨存储的原子性目前没有分布式事务保证，如果删除中途失败，可能出现孤儿 graph episode。文档里也承认这点，对应的兜底方向是图谱对账、孤儿检测和删除同步重试。这是诚实要讲的边界，不要包装成"已经强一致"。

### 12. retry 只对 transient 错误重试，怎么判定 transient？判错会怎样？

Gateway 的重试策略只对被分类为 transient 的错误（如超时、临时网络错误）重试，对参数错误、权限拒绝这类永久错误不重试。判定依据是错误类型/error_kind。

判错的后果：把永久错误误判为 transient 会做无谓重试，浪费时间但通常不会造成副作用（因为有幂等）；把 transient 误判为永久会过早失败、降低成功率。所以分类逻辑要保守，写副作用的工具更要靠幂等兜底，避免重试导致重复执行。

### 13. 横向扩容后进程内幂等账本失效，持久化打算怎么做？

`IdempotencyStore` 是接口，默认 `InMemoryIdempotencyStore` 只在单进程有效。持久化方向是换成共享存储后端（如 Postgres 表或 Redis），key 用 thread_id + run_id + step_id + tool 组合，保证同一次确认动作跨进程唯一；写入用"先占位再执行"的原子操作（如唯一约束或 SETNX），命中已存在的 key 直接拒绝重放。接口已经预留，替换实现即可，不用动业务工具。

---

[← 返回索引 INDEX.md](INDEX.md)
