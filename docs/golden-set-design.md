# 自建 Golden Set 设计

> 状态:持续维护 · 数据来源口径:**手工标注真实场景** · 创建于 2026-06-22 · 最近真实环境验证:2026-06-26

## 1. 背景与问题

工程需要同时覆盖外部基准与项目自身场景。两者用途不同:

| 层 | 位置 | 性质 | 作用 |
| --- | --- | --- | --- |
| 公开 RAG 基准 | [evals/multihoprag/](../evals/multihoprag/)、[evals/open_ragbench/](../evals/open_ragbench/) | 借来的外部数据集,只测检索 IR 指标 | 非本工程领域数据,与真实 capture/note 语义脱节 |
| 自建能力金标 | `evals/*_quality/` | 手工标注项目真实场景,覆盖 RAG、Router、Orchestration、Conversation | 衡量本系统的检索、决策、执行与多轮状态质量 |

本文定义统一的 golden set 口径、目录结构、标注规范、门禁策略与结果解释方式。公开基准用于横向比较,自建金标用于项目内回归,二者不能相互替代。

## 2. 设计原则

1. **复用已验证的口径,不另起炉灶。** [evals/rag_quality](../evals/rag_quality/) 的 `RagEvalCase → RunOutput → scorer → baseline.json` 四段式已跑通,新能力的金标沿用同一形状:`Case`(标注)→ `RunOutput`(可打分投影)→ `scorer`(纯函数指标)→ `baseline.json`(回归门禁地板)。
2. **标注与管线解耦。** scorer 只消费 thin 投影(`RunOutput`),从不直接吃 `AskRunContext`/runtime,保证指标可独立单测。fixture/stub 只验证 scorer 与系统契约,不计作 Golden Test 结果。
3. **门禁是地板,不是目标。** `baseline.json` 里每个指标是"不得低于"的回归地板。降地板需评审理由;升地板即棘轮式提质。
4. **真实场景优先。** 所有 case 的 `question`/`input` 来自真实领域(个人知识/笔记)手工标注,而非合成模板。先小批量(每能力 20–30 条)跑通门禁,再考虑脚本扩充。

## 3. 多类金标口径(scope)

"golden set" 对本工程不是单一概念,而是一组互不相同的标注口径。各能力独立交付,优先级如下。

需要先明确当前评测边界:RAG、Router、Orchestration 的 case 都以**一条独立用户输入或一次运行**为评测单元。即使输入文本包含“刚才”“这段对话”等字样,若 runner 没有注入真实历史消息,它仍然是单轮样本;单次输入被拆成多个有序 intent,也只是**单轮多目标**,不等于多轮对话。跨 turn 的上下文继承、状态演化与 HITL resume 由 §3.4 单独覆盖。

### 3.0 能力边界与互补关系(职责矩阵)

各套金标**职责互斥、不可相互替代**。每套只对自己评测单元内的一类质量负责,并显式声明"不覆盖什么、交给谁"。这张矩阵是判断"某能力该进哪套金标"以及"两套是否冗余"的唯一依据。

| 金标 | 评测单元 | 专属能力(仅此处覆盖) | 明确不覆盖(交给谁) |
| --- | --- | --- | --- |
| RAG (§3.1) | 单次"检索 → 生成"运行 | 检索 IR(recall/ndcg/precision)、答案相关性与忠实度、claim 判定、对比证据、图证据覆盖 | 意图路由、步骤编排、多轮状态 |
| Router (§3.2) | 单轮路由决策 | ready/clarify 判定、意图集合 F1、有序意图、clarify 字段精度 | 步骤是否真正执行、终态、副作用(→ Orchestration) |
| Orchestration (§3.3) | **单次** entry → router → steps → terminal | 事件子序列里程碑、`forbidden_events` 负向不变式、**不挂死**终态、单点事故回归网(如 SSE 卡死) | 任何跨 turn 的状态继承与 resume(→ Conversation) |
| Tool (§3.3.2) | 单个工具能力声明 / 工具调用投影 | 工具业务义务、risk、side effect、permission scope、confirmation、idempotency、timeout、retry、rate limit、artifact 契约 | workflow 是否选择该工具(→ WorkflowPlanner/Orchestration),工具底层业务算法质量(→ 对应用例或端到端 case) |
| Research (§3.3.3) | 单个 Research 目标 / 固定研究语料 → 工作流契约与事件质量 | 一次性研究、订阅创建、已有 run 执行、订阅/简报管理如何被组织成固定工作流;固定语料下基于事件帧的来源去重、事件聚类、可信度、个人相关性排序与 digest 选择 | 单个研究工具的治理义务(→ Tool),真实外网/真实 LLM 质量(→ Research 真实 runner) |
| Conversation (§3.4) | **整段会话**的多轮轨迹与状态演化 | thread 连续性、HITL resume 闭环、跨轮上下文保留、副作用 delta、整段任务成功 | 单点编排契约与孤立事故回归(→ Orchestration) |

**为什么 Orchestration 与 Conversation 不冗余(常见疑问)**:一个 Conversation case 的每个 turn 内部确实复用与 Orchestration 相同的 entry→steps→terminal 流程,二者在"单轮编排"这段存在**实现重叠**(见下方共享指标核心)。但它们的**评测语义不可互换**:

- Orchestration 要的是**孤立、可精确归因、单点**的回归信号——`forbidden_events` 这类负向不变式、以及 orch-009 那种"复刻生产事故"的回归网,必须保持单轮纯净,不能被卷进多轮判定。
- Conversation 的 `final_task_success` 是**全有或全无的合取门**(任一 turn 任一指标非满分即归零)。把单点编排 case 塞进来会让单点失败的归因被多轮合取淹没,违反 §6.1.2"专项事故应另设精确回归 case,不能只依赖宽松平均分"。
- Conversation 的 `thread_continuity` / `resume_success` / `context_retention` / `side_effect_delta` 在单轮里**不存在对应物**——没有"前一轮"。

因此正确的去冗余方式不是合并金标,而是**抽取共享的纯函数指标**(见 §4 共享指标核心),消除代码重复的同时保留两套各自的评测边界。新增能力(如 `consolidate_knowledge` 自动主题整理)按本矩阵归位:其端到端"选源 → supersede"副作用应进 Orchestration(单次运行),"先写多条笔记 → 再整理"的跨轮依赖应进 Conversation。

**自包含 vs 有状态(Phase 1 / Phase 2)**:Orchestration 的 case 进一步分两类。**自包含**(如 orch-001~009:你好 / 删除 / 总结)的正确性只取决于输入本身,无需预置数据。**有状态**的正确性*定义在库里已存在的数据上*——`consolidate_knowledge` 与 `inspect_knowledge_gaps` 是典型:前者不先 seed ≥ 2 条同主题笔记只会命中"至少两条"拒绝分支;后者不先 seed 出冲突/孤岛,检测永远返回"无缺口"。二者都测不到真正语义。有状态流程**必须先 seed DB 再跑完整 `execute_entry`**,且按 §6.2 用独立 `user_id` 隔离。

按 §6,只有真实 LLM + 真实管线才算 Golden Test,因此这两个有状态流程都用真实 router LLM(`build_real_service` 从环境装配,未配置则 skip),**不使用 stub 路由**;seed 走 store(属基础设施,非 stub),每次用唯一 `user_id` 保证隔离与确定性:

- [evals/test_consolidate_knowledge_flow.py](../evals/test_consolidate_knowledge_flow.py):seed 后走完整 router→planning→step→tool,断言路由到 `consolidate_knowledge`、抵达终态(不挂死)、源笔记被 supersede 且回链综述;含"仅一条来源 → 优雅拒绝、不挂死、不误改"反例。
- [evals/test_inspect_knowledge_gaps_flow.py](../evals/test_inspect_knowledge_gaps_flow.py):seed 两条同主题、极性相反的笔记造出 `potential_conflict`,断言路由到 `inspect_knowledge_gaps`、抵达终态、报告含确定性表头(per-gap 措辞可能经 LLM 改写,表头不会);含"同极性 → 无冲突、报告干净"反例。

二者覆盖了 use-case 层测试(`tests/test_agent_flows.py` / `tests/test_knowledge_gap_analyzer.py`,直调用例、用假依赖)与 Orchestration thin 投影(无 seed、无副作用维度)都触及不到的整条**真实有状态编排路径**。

### 3.1 RAG 质量金标

- **口径**:`{question → gold_evidence_ids, reference_answer, gold_claim_verdicts, claims_needing_contrast}`,即现有 [dataset.py](../evals/rag_quality/dataset.py) 的 `RagEvalCase`。
- **质量指标**:recall@5 / ndcg@5 / context_precision / answer_relevance / faithfulness / claim_accuracy / contrastive_coverage。
- **图检索指标**:
  - `graph_contribution_rate` —— 检索证据中由 Graphiti/GraphRAG/structural 路径贡献的比例。
  - `graph_hit_rate` —— case 是否至少命中一条图证据。
  - `graph_requirement_met` —— 对 `requires_graph_evidence=true` 的 case,必须实际命中图证据;非图证据答对也不能替代图检索覆盖。
- **效率指标**:`latency_ms` / `latency_p95_ms` / `llm_call_count` / `input_tokens` / `output_tokens` / `total_tokens` / `total_tokens_p95`。
- **覆盖矩阵**:
  - 单跳精确命中 / 多跳召回(已有雏形)
  - 含矛盾证据、需对比证据翻转判定
  - 无答案 / 证据不足(应 `not_found` 而非编造)
  - 中文长文 chunk 折叠回 parent 的召回
  - 同义改写、跨 note 概念聚合
- **reference run 来源**:离线层使用经评审的确定性投影;真实层回放真实管线输出。两类结果必须分开报告。

### 3.2 Router 意图金标

- **口径**:`{entry_input → expected_outcome ("ready"|"clarify"), expected_intents (有序), expected_clarification_fields?}`。对齐 [router.py](../src/personal_agent/agent/router.py) 的 `RouterOutput` 契约。
- **评测边界**:单轮路由。`entry_input` 默认不携带历史消息;`expected_intents: [a, b]` 表示同一轮输入的多目标有序分解,不是两个对话轮次。
- **指标**:
  - `outcome_accuracy` —— ready/clarify 判定正确率
  - `intent_set_f1` —— 多目标意图集合的 F1(顺序无关)/ 或有序 Kendall-tau(若顺序有语义)
  - `clarify_precision` —— 该追问时确实追问、不该追问时不打扰
- **标注难点**:意图边界主观,需在标注规范里固化"何时算 clarify"的判据(见 §5)。

### 3.3 Orchestration 端到端金标

- **口径**:`{user_input → expected_step_sequence (类型/顺序), expected_terminal_outcome, expected_hitl_interrupts?}`。覆盖单次 entry → router → steps → terminal,以及 HITL interrupt 是否正确发生。
- **指标**:
  - `step_sequence_match` —— 期望步骤序列的编辑距离 / 类型集合命中
  - `terminal_outcome_match` —— 终态产物是否符合期望
  - `hitl_trigger_accuracy` —— 该中断处确实触发 HITL
- **依赖**:需运行 Postgres;scorer 可离线单测,Golden Test 必须运行真实全流程。
- **评测边界**:case 只执行一次 `execute_entry`;clarify case 验证“正确暂停”,用户下一轮补充信息后的 resume 属于 §3.4。

### 3.3.1 WorkflowPlanner 依赖规划金标

- **为什么独立建集**:Router 只负责把用户输入拆成有序 Goal,不应该输出执行依赖;Orchestration 端到端金标又太重,不适合快速验证 task DAG / step DAG 的确定性编译。因此单独建立 `workflow_planner_quality` 金标,专门覆盖 `RouterDecision.goals -> ExecutionPlan / ExecutionStep`。离线 gate 使用 fake structured model 覆盖 LLM 依赖判断路径,真实运行时使用结构化模型判断语义依赖,确定性规则负责安全补强和兜底。
- **口径**:`{goals → expected_task_dependencies, expected_step_dependencies}`。case 输入是已经人工评审过的 Goal 序列,输出断言 Planner 生成的 task-level 依赖和关键 step-level 依赖。
- **当前覆盖**:
  - 写入后追问同一知识:`capture_text -> ask` 必须依赖。
  - 多个互不相关只读 ask 不应仅因同属一轮就强制依赖。
  - 后续 goal 有“继续/上述/刚才”等指代线索时依赖前一个 task。
  - 连续长期写入需要串行,避免副作用乱序。
  - 只读 ask 与无关写入同属一轮时,写入不依赖先前只读 task。
  - 当模型判断前序 Goal 依赖后序 Goal 时,Planner 需要通过 task DAG 拓扑排序生成正确执行顺序。
- **指标**:
  - `task_dependency_exact` —— task-level 依赖图完全匹配。
  - `task_dependency_node_accuracy` —— 每个 task 的依赖列表逐点匹配率。
  - `task_dependency_edge_f1` —— task 依赖边的 F1。
  - `step_dependency_exact` —— 标注的关键 step 依赖完全匹配。
  - `step_dependency_node_accuracy` —— 标注 step 的依赖列表逐点匹配率。
  - `step_dependency_edge_f1` —— 标注 step 依赖边的 F1。
  - `overall_exact` —— task 与 step 两层都完全匹配。
- **门禁**:`evals/workflow_planner_quality/test_workflow_planner_gate.py`。该 gate 不调用 LLM、不依赖数据库,属于离线快测。

### 3.3.2 Tool 治理义务金标

- **为什么独立建集**:工具是 Agent 触碰长期记忆、外部网络、后台任务和高风险副作用的真实边界。Workflow registry gate 能检查 workflow 引用了已注册工具,StepProjectionValidator 能检查当前 runtime 是否可执行,但它们不负责回答“这个工具的业务义务是否声明正确”。因此单独建立 `tool_quality` 金标,覆盖 `ToolGovernance` 与业务场景的一致性。
- **口径**:Tool 金标分两层。第一层是 `{tool_name, business_scenario → expected_governance}`,断言该工具必须声明的 exposure、risk、side_effects、permission_scope、requires_confirmation、idempotency_key_required、audit_required、timeout、retry、rate_limit。第二层是 `{tool_name, args → expected_artifact_contract}`,通过 fake 依赖走真实 `ToolExecutor / ToolGateway`,断言 artifact shape、error_kind、evidence、确认门禁、副作用调用次数和幂等 replay。
- **当前覆盖**:
  - 只读本地检索:`graph_search` 只能 `read_local`,不能外网或写入。
  - 公网搜索和 URL 采集:必须声明 `external_network`,有限流、超时和有限重试。
  - 长期记忆写入:`capture_text / capture_upload / update_note / consolidate_knowledge` 必须声明 `write_longterm` 和对应权限域。
  - 高风险删除/恢复:`delete_note / restore_note` 必须 high risk、HITL confirmation、idempotency、audit 且不自动重试。
  - 周期性情报与 Research workflow:订阅、收集、后台 run 状态变更必须声明研究域权限、外网访问或长期写入副作用。
  - 运维诊断与重试:`inspect_workflow_run` 只能只读,`retry_worker_task` 必须是 scoped 中风险写入。
- **指标**:
  - `exposure_exact` —— 工具暴露面是否符合场景。
  - `risk_exact` —— 风险等级是否符合副作用强度。
  - `confirmation_exact` —— 是否正确要求人工确认。
  - `side_effect_exact` —— 副作用集合是否完全匹配。
  - `permission_scope_exact` —— 权限域是否准确。
  - `idempotency_exact` —— 高风险确认动作是否要求幂等 key。
  - `audit_exact` —— 是否要求审计。
  - `resource_policy_exact` —— timeout / retry / rate limit 是否符合预期。
  - `outcome_exact` —— 执行结果 ok/failure 是否符合预期。
  - `error_kind_exact` —— 失败是否被归类为 transient / invalid_param / permission / unrecoverable。
  - `data_shape_match` —— 成功 artifact 是否含必要字段。
  - `evidence_count_match` —— evidence 数量是否达到场景要求。
  - `repeat_exact` —— replay 行为是否符合幂等预期。
  - `call_count_exact` —— fake 依赖记录的副作用调用次数是否准确。
  - `overall_exact` —— 对应层全部匹配。
- **门禁**:
  - `evals/tool_quality/test_tool_quality_gate.py`:不调用工具、不依赖数据库或网络,只装配真实 tool builders 并读取 `tool_governance()`。
  - `evals/tool_quality/test_tool_execution_contract_gate.py`:通过 fake 依赖调用真实工具网关,覆盖 artifact shape、错误分类、确认门禁、副作用调用次数和幂等 replay。

### 3.3.3 Research 能力金标

- **为什么独立建集**:Research 不是单个工具,而是一组围绕外部信息收集、证据缺口追踪、事件聚类、可信度校准、个人相关性排序、简报生成和周期订阅的领域能力。Workflow 是否编译成固定步骤属于确定性 contract,应由普通单元测试和 `WorkflowSpecValidator` 覆盖,不放进 golden set。Research 金标只回答一个问题:固定研究语料进入真实 `ResearchService` 后,当前策略是否真的完成了来源去重、动态补证据、语义事件聚类、可信度校准、个人相关性排序和 digest 选择。
- **口径**:
  - Event/loop quality 契约:`{topic, fixed_search_results_by_query, fixed_event_frames, fixed_graph_matches → expected_query_terms, expected_gap_types, expected_source_count, expected_events, expected_digest_title_terms}`。gate 不访问真实外网/LLM,但会执行真实 `ResearchService.prepare_run → initialize_state → run_research_loop → synthesize_digest → verify_digest`;固定 `event_frames_by_title` 相当于 replay LangExtract 的结构化事件帧输出。
  - Event quality 真实层:`{topic, fixed_search_results, real_langextract_frames, fixed_graph_matches → expected_*}`。搜索结果和图谱匹配仍固定以保证可归因,但事件帧由当前 `.env` 中配置的真实 LangExtract API 生成;该层才用于评价 LangExtract 接入后的真实 Research 事件抽取质量。
- **当前覆盖**:
  - 初始 query 与 evidence gap 能否驱动 `research_run_loop` 继续搜索,例如单源媒体事件触发 official confirmation 查询。
  - URL canonicalization 与去重是否正确。
  - 多源同事件是否聚合并标为 `verified`,单源事件是否保持 `uncertain`。
  - 语义相同但标题改写较大的事件是否能通过 event frame 合并。
  - 标题相似但事件类型不同的来源是否避免误合并。
  - 与个人知识图谱相关的事件是否优先进入 digest。
- **指标**:

  | 层 | 指标 | 含义 |
  | --- | --- | --- |
  | Event quality | `source_count_exact` | URL 规范化与去重后的来源数量是否匹配 |
  | Event quality | `min_iterations_met` | evidence-driven loop 是否至少执行到期望轮次 |
  | Event quality | `query_coverage` | loop 是否执行了期望的初始查询或补证据查询 |
  | Event quality | `gap_coverage` | loop 是否产生期望的证据缺口类型 |
  | Event quality | `stop_reason_match` | 停止原因是否符合场景预期 |
  | Event quality | `event_recall` / `event_precision` | 基于 actor/action/object/event_type 事件帧的聚类是否命中人工期望事件,且没有额外拆分/误聚类 |
  | Event quality | `status_accuracy` | 多源 verified、单源 uncertain 等可信度状态是否校准 |
  | Event quality | `source_support_accuracy` | 事件是否满足期望来源数量和 primary source 要求 |
  | Event quality | `personal_relevance_accuracy` | 图谱相关事件是否被赋予足够个人相关性 |
  | Event quality | `digest_coverage` | digest 是否选中期望的高价值事件 |
  | Event quality | `primary_source_rate` | 产出事件中含 official/paper 来源的比例 |
  | Event quality | `overall_score` | 来源、事件、可信度、排序和 digest 选择的加权得分 |
- **门禁**:
  - `evals/research_quality/test_research_event_quality_gate.py`:使用固定搜索结果、固定 event frame 和固定 graph matches 执行真实 `ResearchService` evidence loop,属于确定性 Research 行为质量快测,不作为真实 LangExtract 质量结论。
  - `evals/research_quality/test_research_event_quality_real_gate.py`:使用固定搜索结果和固定 graph matches,但事件帧来自真实 LangExtract API,并启用生产 fallback;provider 抖动会体现为质量分下降,而不是让报告在打分前中断。`research-event-004` 覆盖“语义相同但标题改写较大”的多源事件,期望合并成 verified;`research-event-005` 覆盖“标题相似但事件类型不同”的反例,期望保持拆分,防止过度合并。

### 3.4 Conversation 多轮对话金标

- **为什么独立建集**:多轮质量不是把若干单轮 case 拼在一起。后续 turn 的正确行为依赖前序用户输入、助手输出、HITL 状态、会话内短期记忆和已经产生的副作用,评测对象是**整段会话轨迹及状态演化**。
- **口径**:

  ```json
  {
    "id": "conv-001",
    "description": "知识问答后用指代词固化上一轮结论",
    "expected_final_note_delta": 1,
    "turns": [
      {
        "kind": "entry",
        "user_input": "什么是 DNS？",
        "expected_outcome": "ready",
        "expected_intents": ["ask"]
      },
      {
        "kind": "entry",
        "user_input": "把刚才的结论固化下来",
        "expected_outcome": "ready",
        "expected_intents": ["solidify_conversation"],
        "expected_context_refs": [0]
      }
    ]
  }
  ```

- **runner 约束**:
  - 同一 case 的全部 turn 必须复用同一个 `session_id`/thread,按顺序真实执行,不能逐 turn 新建隔离 session。
  - runner 应保存每轮 assistant response、事件序列、interrupt/checkpoint、状态快照和可观察副作用,再投影为与 runtime 解耦的 `ConversationRunOutput`。
  - HITL case 必须执行“触发 interrupt → 用户补充信息 → resume → 抵达终态”的完整闭环,不能只以暂停作为成功。
  - case 之间必须隔离 session 和可变数据;涉及写入/删除时使用独立 fixture 或清理策略,避免前一 case 污染后一 case。
- **核心指标**:
  - `turn_outcome_accuracy` —— 每轮 ready/clarify/terminal 判定正确率。
  - `turn_intent_accuracy` —— 每轮意图及单轮多目标顺序是否正确。
  - `context_retention` —— 期望引用的历史 turn 是否仍存在于同一 thread checkpoint;它只证明上下文可用,不冒充语义理解正确。
  - `response_grounding` —— 对确需跨轮语义理解的 case,用人工标注的关键事实检查最终回答/产物是否真正使用了正确历史。
  - `resume_success_rate` —— HITL 补充后是否从原 checkpoint 恢复并完成,而非新开一条无关 run。
  - `side_effect_accuracy` —— note 创建/更新/删除等副作用是否发生且只发生一次。
  - `final_task_success` —— 整段会话最终目标是否完成。
- **首批覆盖矩阵**:
  - 指代与上下文继承:“这个”“刚才那个”“继续”。
  - 追问深化:首轮回答后要求解释、对比、举例,不得丢失主题。
  - clarify → 补充对象/范围/时间 → resume。
  - 话题切换后返回旧话题,以及不应串用旧上下文的反例。
  - ask → solidify、长对话 → summarize_thread 等依赖真实历史的能力。
  - 会话内写入后再次询问能够召回;跨 session 时只允许使用已持久化的长期记忆。
  - 执行失败 → 用户重试/修正,验证幂等性与副作用不重复。
- **测试分层**:离线 fixture 验证 scorer 与状态契约;集成测试验证真实 checkpoint/runtime 与确定性模型桩;Golden Test 使用真实 LLM、真实 session 连续执行全部 turn。只有最后一层产生 Golden 质量结果。

## 4. 目录结构

沿用 `evals/<capability>/` 的并列结构,每个能力一个自包含子包:

```
evals/
  _metrics_core.py    # 共享指标核心(见下)
  test_metrics_core.py
  rag_quality/        # §3.1
    cases.json        # 金标
    dataset.py        # Case / RunOutput 模型
    metrics.py        # 纯函数指标
    scorer.py         # Case×RunOutput → 报告
    baseline.json     # 回归地板
    runner.py         # 真实管线 → RunOutput 投影 + 回放 CLI
    test_*_gate.py    # 门禁测试
  router_quality/     # §3.2
    cases.json
    dataset.py        # RouterEvalCase / RouterRunOutput
    metrics.py
    scorer.py
    baseline.json
    runner.py
    test_router_gate.py
  orchestration_quality/   # §3.3
    cases.json
    ...(同形)
    test_orchestration_gate.py
  tool_quality/            # §3.3.2;工具治理义务
    cases.json
    execution_cases.json
    dataset.py             # ToolEvalCase / ToolRunOutput
    metrics.py
    scorer.py
    baseline.json
    execution_baseline.json
    test_tool_quality_gate.py
    test_tool_execution_contract_gate.py
  research_quality/        # §3.3.3;Research evidence loop 与事件质量
    event_quality_cases.json
    dataset.py             # ResearchEventQualityEvalCase / ResearchEventQualityRunOutput
    metrics.py             # research event/loop 质量指标
    scorer.py
    event_quality_baseline.json
    event_quality_real_baseline.json
    test_research_event_quality_gate.py
    test_research_event_quality_real_gate.py
  conversation_quality/    # §3.4;多轮会话轨迹与状态演化
    cases.json
    dataset.py             # ConversationEvalCase / TurnExpectation
    metrics.py
    scorer.py
    baseline.json
    runner.py              # 同 session 顺序执行 turns + 状态投影
    test_conversation_gate.py
    test_conversation_runtime_gate.py
    test_conversation_real_gate.py
```

**约定**:`cases.json` 一律 UTF-8;loader 用 `Path(...).read_text(encoding="utf-8")`(注意 Windows 默认 GBK,直接 `open()` 会炸中文)。

**共享指标核心(`evals/_metrics_core.py`)**:跨金标真正重复的纯函数只有三个,统一收在此模块,各能力 `metrics.py` 按自己的惯用名 re-export,保证 scorer/runner/test 的 `.metrics` 导入面不变:

| 核心函数 | 语义 | 被谁以何名复用 |
| --- | --- | --- |
| `exact_match(predicted, expected)` | 标量/列表相等判定 | Router & Orchestration 的 `outcome_correct`;Conversation 的 `exact_match`(逐轮 outcome/intent) |
| `ordered_subsequence(actual, expected)` | 有序子序列里程碑命中 | Orchestration 的 `event_subsequence_match`;Conversation 的 `ordered_subsequence` |
| `reached_terminal` / `TERMINAL_EVENTS` | 运行是否抵达终态(不挂死) | Orchestration 与 Conversation 的 runner/scorer |

边界原则:**只有"任何金标都会用到且逻辑完全一致"的指标才进核心**。带领域语义的指标(RAG 的 IR/忠实度、Router 的 intent F1、Conversation 的 thread/resume/side-effect、Orchestration 的 `forbidden_events`/`primary_intent_correct`)一律留在各自 `metrics.py`,不上提——避免核心沦为大杂烩。

## 5. 标注规范(手工标注)

每个能力的 `cases.json` 是手工标注真实场景的产物。统一规则:

1. **来源真实**:`question`/`input` 取自真实个人知识/笔记场景,不用合成模板;PII 用占位符。
2. **稳定 id**:`<cap>-NNN` 形如 `rq-001`/`router-001`,新增追加不复用。
3. **每条带 `description`**:一句话说明该 case 想测什么场景(loader 忽略未知键,可自由加人读注释)。
4. **金标可判定**:
   - RAG:`gold_evidence_ids` 必须能在对应 corpus 中定位;`gold_claim_verdicts` 按答案中 claim 出现顺序对齐。
   - Router:`expected_outcome` 二选一;clarify 判据固化为——"缺少执行目标所必需的信息(对象/范围/时间)"才标 clarify,语气模糊但意图明确不标。
   - Orchestration:`expected_step_sequence` 标步骤**类型**而非具体文案,避免脆性。
   - Conversation:每轮必须标注期望 outcome;只在确有上下文依赖时填写 `expected_context_refs`;涉及副作用时必须标明最终数量/目标对象或幂等约束,不能只写“成功”。
5. **覆盖矩阵**:每能力的金标必须覆盖正例 + 反例(矛盾/无答案/不该追问),不能全是 happy path。
6. **评审**:金标变更走 PR review;新增/修改 case 需在 PR 描述里说明覆盖的新场景。
7. **多轮边界**:Conversation case 的 turn 是不可拆分的最小评测序列。不得为了提高单轮指标而把后续 turn 单独运行;历史 assistant 输出若由 fixture 固定,必须显式标记 `history_mode: fixed`,不能冒充真实逐轮生成。

## 6. 测试与门禁策略

测试分三类,但只有真实环境测试称为 **Golden Test**:

- **Scorer/契约测试**:纯函数、序列化 fixture 或确定性桩,用于验证数据模型、指标算法和 baseline 比较逻辑。它们可以进入普通 CI,但结果不计作 Golden 分数。
- **系统集成测试**:使用真实 runtime、LangGraph、Postgres 与确定性模型桩,验证 checkpoint、事件顺序、终态和副作用等系统契约。它们不衡量真实模型质量。
- **Golden Test**:统一使用真实 LLM、真实运行管线、真实基础设施和人工 gold 标签。多轮 case 必须在同一 session 内连续执行全部 turn,包括 checkpoint resume 和副作用核验。
- **运行规则**:Golden Test 不设置额外的 nightly/opt-in 功能开关。真实环境配置齐全时直接执行;缺少 LLM、Postgres 等必要配置时明确 skip 或失败,由执行环境策略决定。
- **evals/ 默认在 testpaths 外**,显式运行。
- **baseline 规则**:`baseline_real.json` 是 Golden Test 的质量门禁;离线 `baseline.json` 只约束 fixture/契约回归。上调即棘轮提质;下调必须写明评审理由。
- **性能与成本门禁**:质量指标使用最小值地板;`*_max` 使用最大值天花板。真实层 Golden 应对 `latency_p95_ms` 与 `total_tokens_p95` 设置上限,避免平均值掩盖长尾请求或异常 token 消耗。

### 6.1 结果解释原则

1. **离线与集成测试全绿只证明评测契约和确定性路径没有回归**,不能称为 Golden 通过。
2. **Golden Test 聚合分数用于发现整体退化**,专项事故应另设精确回归 case,不能只依赖宽松平均分。
3. **安全不变式应保持严格**:例如进入执行的 run 必须到达 `run_completed`/`run_failed`,HITL resume 必须复用原 run/thread,副作用不得重复。
4. **模型偏好与系统错误分开处理**:歧义输入上的合理分歧可保留噪声裕度;挂死、越权、错误副作用等不可用模型非确定性解释。
5. **结果命名必须准确**:stub/fixture 的 1.0 只能报告为契约测试结果;Golden 结果只来自真实环境。

### 6.2 真实数据采集闭环

真实日志、trace 和 note 快照只能生成**待标注草稿**,不能直接成为 gold。闭环为:

`真实使用/事故 → 去重草稿 → 人工确认或修正 expected_* → 合入 cases.json → 离线与真实层回归`

采集时保留模型的 `observed_*` 作为标注参考,但不得用模型自己的输出自动填充 `expected_*`。Router 可从结构化决策日志采集;RAG 与 Orchestration/Conversation 应从 ask trace、entry events、checkpoint 和副作用快照中采集。

## 7. 当前结果说明

### 7.1 数据规模与测试状态

| 能力 | Case 数 | 主要覆盖 | Golden Test 结果(2026-06-23) |
| --- | ---: | --- | --- |
| RAG | 25(其中 22 条进入真实 seed-and-ask) | 单跳、多跳、图谱增强、同义改写、跨 note 聚合、矛盾、无答案 | 最近测量:recall@5 1.0000、ndcg@5 0.9964、图贡献率/命中率均为 0、平均 latency 16574.8ms、平均 token 3279.8。现已对 `rq-003` 增加严格图证据要求,当前 Graphiti 配置修复前 Golden 将失败 |
| Router | 24 | 全意图词表、clarify、删除/总结/采集边界 | 2/2 通过;outcome 0.9167、intent F1 0.8194、latency p95 5423.4ms、token p95 1008;DNS 专项通过 |
| Orchestration | 9 | clarify、步骤投影、事件顺序、高风险意图、终态不变式 | 终态 1.0000,但新增性能 Gate 失败:latency p95 69467.6ms > 60000ms;日志显示 Graphiti embedding 401 导致长尾 |
| Research | 4 workflow + 5 event quality | 一次性研究、订阅创建、已有 run 执行、订阅/简报管理的工作流契约;固定语料下基于事件帧的来源去重、事件聚类、可信度、个人相关性排序、digest 选择 | Workflow 契约 Gate 通过;固定 event-frame 契约 overall 1.0000;真实 LangExtract event quality 最近测量 overall 1.0000,real baseline 地板上调到 0.9600;真实外网 runner 待接入 |
| Conversation | 8 | 同 thread、多轮追问、clarify→resume/reject、总结、话题切换、写后即查、solidify | 质量/结构结果见 §7.2;latency/token 已接入 scorer 与 `baseline_real.json`,待 Graphiti 配置修复后重新校准真实 p95 |

### 7.2 Conversation 指标结果

Conversation 不能用 pytest 的通过数量代替质量分数。当前结果按运行层级拆分如下:

| 指标 | 含义 | Golden Test |
| --- | --- | ---: |
| `turn_outcome_accuracy` | 每轮 ready/clarify 判定是否符合金标 | 1.0000 |
| `turn_intent_accuracy` | 每轮有序 intent 是否符合金标 | 0.9375 |
| `event_sequence_match` | 每轮关键事件是否按期望顺序出现 | 1.0000 |
| `context_retention` | 标注引用的历史 turn 是否仍保留在同一 checkpoint | 1.0000 |
| `response_grounding` | 回答或产物是否包含金标要求的历史关键事实 | 1.0000 |
| `resume_success_rate` | 是否沿原 run/thread 恢复并抵达终态 | 1.0000 |
| `thread_continuity` | 同一 case 的全部 turn 是否使用同一 thread | 1.0000 |
| `side_effect_accuracy` | note 等副作用数量是否准确且不重复 | 1.0000 |
| `final_task_success` | 整段会话的所有必要条件是否同时满足 | 0.8750 |

结果解释:

- 8 条 Conversation case 全部在真实 Router LLM、真实 runtime、Postgres/checkpoint 和真实副作用环境中连续执行。
- 结构与状态指标全部为 1.0000,说明同 session/thread、HITL resume、上下文保留和副作用约束均满足。
- `turn_intent_accuracy=0.9375` 表示 16 个 turn 中有 1 个 intent 与当前 gold 不一致;该分歧使 `final_task_success` 降为 0.8750。

### 7.3 结果能够说明什么

- 多套能力已经具备统一的 `Case → RunOutput → scorer → baseline` 回归形状,可对数据、模型或编排改动进行可重复比较。
- Orchestration 的终态指标能够捕获“流程进入执行但未结束”的挂起风险。
- Conversation 的结果证明评测 runner 确实复用同一 thread,并通过原 `run_id/thread_id` 完成 HITL resume,而不是把补充信息降级成新单轮请求。
- 真实模型层曾出现与确定性桩不同的路由判断,说明真实层是必要的独立信号,不能由离线满分替代。
- RAG 检索层表现稳定,但生成与 claim 判定层明显弱于检索层;当前门禁不能把“整体通过”解释为回答质量良好。
- 新增效率指标已经捕获 Orchestration 的真实长尾:平均耗时看似可接受,但 p95 超过 60 秒并触发 Gate。
- 新增图检索指标证明原 RAG 结果没有图证据贡献;“管线支持 Graphiti”不等于 Golden 实际覆盖图检索。

### 7.4 结果不能说明什么

- RAG 离线 reference run 仍主要衡量评测口径与理想投影,不能代表真实捕获语料上的线上质量。
- Router 离线 case 以单目标为主,不能充分代表真实 LLM 的多目标分解稳定性。
- 真实 LLM 具有非确定性;一次通过不等于长期稳定,需要保留多次运行分布和 per-case 分歧。
- 当前数据规模仍偏小,尤其 Conversation 只有 8 条;尚不足以覆盖长对话、多次 HITL、失败重试幂等和跨 session 长期记忆。
- `context_retention=1.0` 只证明历史仍在 checkpoint 中,不单独证明模型理解了正确指代;需结合 `response_grounding` 和最终任务结果判断。
- RAG `claim_accuracy=0.0000` 当前未纳入 `baseline_real.json` 门禁,所以测试通过不代表 claim 判定可接受;这是本轮真实测试暴露出的门禁缺口。
- 当前 LLM 服务限制为 20 requests/minute;并发执行 Golden Test 会触发 429 并污染结果,测试必须串行或实现显式速率控制。
- RAG 与 Conversation 运行中出现 `Neo4jDriver._execute_index_query was never awaited` 警告;本轮未造成失败,但表明图存储异步调用存在资源管理风险。
- Token 指标统计项目直接发起且能返回 usage 的 LLM 调用;embedding token 与不返回 usage 的第三方调用不计入,因此它是可比较预算而非完整账单。

## 8. 设计决策与待确认问题

- RAG 金标的 corpus:是用 §3.1 提到的真实 note 快照,还是为金标单独维护一份小 corpus 固定下来?(影响 `gold_evidence_ids` 的稳定性)
- ~~Conversation 离线 fixture 的历史 assistant 输出如何保存?~~ **已确认**:保存人工评审后的确定性 `reference_runs.json` 投影,用于验证 scorer 与门禁语义;它不冒充 Golden 结果。真实逐轮行为由 Golden Test 测量。
- ~~Conversation case 的副作用如何隔离?~~ **已确认**:真实层每次 case invocation 使用独立 `user_id + session_id`,以用户作用域隔离 note 与 checkpoint;Postgres/stub 集成层继续使用测试 fixture 逐 test 清理业务表。
- ~~Router `intent` 顺序是否有语义?~~ **已确认**:有语义(`primary_intent = goals[-1]`,渲染为 `a → b`),故同时保留集合 F1 与有序 exact 两个指标。
- ~~Orchestration `expected_step_sequence` 的粒度?~~ **已确认**:event-type 有序子序列(非 node 级),避免与 LangGraph 内部实现耦合。
