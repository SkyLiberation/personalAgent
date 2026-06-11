# 当前项目面试问答准备

这份文档总结面试中可能围绕当前 personal agent 项目追问的问题和参考回答。回答口径重点不是背概念，而是讲清楚项目里的真实边界：哪些已经落地，哪些是设计方向，为什么这样拆层，以及当前风险在哪里。

项目最核心的一句话：

> 这个项目不是简单让 LLM 多调用几个工具，而是把 Agent 的记忆、行动和规划都放进可恢复、可校验、可审计、可评测的系统边界里：LangGraph checkpoint 管短期执行现场，Postgres note/chunk 管长期事实，MemoryEpisode 管情景记忆（过往任务的意图与结果）、MemoryItem 管反思 / 程序经验，独立 planner LLM 管查询理解、Unstructured 管文档结构化（LangExtract 作为休眠的可选抽取层保留），Graphiti 做语义索引，Evidence 管回答依据，WorkflowSpec/WorkflowRegistry 管固定流程拓扑，PolicyEngine 管策略决策，ToolGateway 管副作用，WorkflowSpecValidator/PlanValidator 管 spec 与步骤投影安全，evals 模块验证检索、问答和规划策略是否真的有效。

## 它解决了什么问题

### 1. 这个 Agent 面向什么场景？

这是一个面向个人知识管理的 Agent。它帮助用户把零散文本、网页、上传文件和对话结论沉淀为长期知识，并在后续提问时基于这些知识进行检索、推理和回答。

它不是只做一次性聊天，而是围绕“知识从哪里来、怎么存、怎么找、怎么引用、怎么安全删除”形成闭环。

### 2. 用户为什么不用普通 ChatGPT，而要用这个 personal agent？

普通 ChatGPT 更擅长一次性对话，但默认不会稳定维护用户自己的长期知识库，也不一定能把回答依据和本地知识来源清楚绑定。

这个 Agent 的价值在于：

- 用户可以显式 capture 文本、链接、文件和对话结论。
- 知识会进入长期 note/chunk 存储，而不是只留在聊天窗口里。
- 回答时会从长期记忆、图谱和工具结果中组织 evidence。
- 删除等高风险动作有目标解析、确认、幂等和审计边界。
- 同一 thread 的复杂任务可以通过 checkpoint 暂停和恢复。

所以它解决的是“个人知识如何长期沉淀并被可靠使用”的问题，而不只是“让模型回答一句话”。

### 3. 它具体解决了哪些用户痛点？

第一是知识沉淀问题。用户平时输入的文本、网页、文件和多轮对话结论很容易散落在不同聊天里，事后很难找回。这个项目通过 `capture_text / capture_url / capture_upload / solidify_conversation` 把这些内容写入长期知识库。

第二是知识检索和回答问题。用户后续提问时，Agent 不只依赖模型参数记忆，而是从 Postgres note/chunk、Graphiti 语义关系和工具结果中取 evidence，再组织回答，降低凭空回答的风险。

第三是长会话连续性问题。LangGraph checkpoint 保存当前 thread 的 `messages`、计划状态、工具归属、pending confirmation 和事件，使多轮任务、确认暂停和恢复执行有稳定现场。

第四是高风险操作安全问题。删除知识不是用户一句话就直接删，而是经过 planning、retrieve、resolve、HITL confirmation、idempotency key 和工具审计，降低误删和重复执行风险。

第五是 Agent 工程边界问题。项目把模型决策和系统执行拆开：模型可以理解意图、生成草稿和做局部语义判断，但固定流程拓扑来自 `WorkflowSpec`，真正触碰长期存储、外部网络或删除动作前，必须经过 `PolicyEngine`、`PlanValidator`、`ToolGateway`、`ToolGovernance` 和 evidence 边界。

### 4. 它和普通 RAG Bot 的区别是什么？

普通 RAG Bot 通常重点是“上传文档后检索回答”。这个项目更像一个个人知识 Agent，除了 RAG 检索，还包含：

- 长期记忆写入：文本、链接、文件和对话固化都能进入知识库。
- 情景记忆沉淀：每次 entry run 自动记录意图、结果、决策和待办，支持"上次那个任务怎么样了"这类基于历史行为的检索。
- 结构化预处理：Unstructured 会在 capture 中把正文/文档 partition 成 Title、NarrativeText、ListItem、Table 等 typed elements，再通过 `chunk_by_title` 生成 child chunks；chunk 可携带 `title_path / page_number / element_ids / element metadata`。
- 短期执行现场：checkpoint 保存多轮任务和暂停恢复状态。
- 图谱语义索引：Graphiti 提供实体、关系和 episode 检索，但不替代 Postgres 真源。
- 工具治理：工具调用有 schema、gateway、timeout、retry、rate limit、HITL、幂等和审计。
- Workflow / step planning：ask、capture、delete、solidify 本质上都是 workflow；固定拓扑已下沉为 `WorkflowSpec / WorkflowStepSpec / WorkflowRegistry`，其中删除和固化会额外确定性投影成 `PlanStep`，用于步骤展示、HITL、checkpoint 和前端计划面板。
- 高风险恢复：删除知识支持确认、拒绝、resume 和依赖步骤跳过。
- 评测闭环：`evals/` 和 `docs/rag-eval-results.md` 用 Open RAGBench、MultiHopRAG、ask quality、plan/replan 等评测证明策略变化是否真的提升效果。

所以它不是单纯“检索文档回答”，而是围绕个人知识生命周期构建的 Agent。

### 5. 这是一个合格的 Agent 吗？

如果按“个人知识 Agent 原型 / 工程型 Agent”来看，它是合格的。因为它已经具备 Agent 的核心闭环：

- 能识别用户意图。
- 能调用工具完成真实动作。
- 能沉淀和检索长期知识。
- 能基于 evidence 回答。
- 能规划复杂流程。
- 能对高风险操作确认和恢复。
- 能把短期现场和长期事实分开。

但如果按完整生产级 SaaS Agent 来看，它还不能说完全成熟。当前 PolicyEngine 已落地基础规则和可配置覆盖，结构化 ThreadSummary 也已落地并随 checkpoint 持久化，但仍需补齐 workspace/tenant 级权限、审计落库、持久化幂等账本、知识冲突自动检测和专项 eval。

更稳的面试表述是：

> 它已经是一个具备核心闭环的个人知识 Agent：能采集、沉淀、检索、回答、固化和删除知识，并且对工具调用和高风险操作建立了工程边界。它目前更像一个生产化方向明确的 Agent 系统骨架，核心链路、Workflow 规划和基础 PolicyEngine 已经打通，但多租户权限、审计落库、知识冲突治理和专项 eval 还需要继续补齐。

## 高频总览问题

### 1. 这个 personal agent 的核心链路是什么？

用户请求先进入 LangGraph entry，经过 router（`DefaultIntentRouter`，LLM 分类）判断 intent。普通问答、capture、direct answer、summarize 会走各自分支；需要明确步骤边界的高风险或复杂任务，例如 `delete_knowledge` 和 `solidify_conversation`，会进入 planning。其中 capture 按来源细分为 `capture_text / capture_link / capture_file` 三个意图，summarize 实际意图名是 `summarize_thread`，另有 `unknown` 作为无法判定时的澄清兜底。

问答路径会从长期记忆、图谱或外部工具中检索证据，统一成 `EvidenceItem`，再由 `ContextPack` 做去重、排序和预算裁剪，最后进入 prompt。写入路径通过 capture 工具把内容沉淀到 Postgres `knowledge_notes`，并可同步 Graphiti。删除路径会先规划、解析目标、生成确认，再通过 HITL resume 真正执行。

### 2. 你为什么采用多层 Agent 架构？

README 里当前工程不是只拆成 memory、tools、planning，而是分成入口层、意图识别 / 路由层、规划层、运行时 / 编排层、工具层、记忆层、检索与推理层、执行与反馈层、观测与治理层；此外 `evals/` 作为评测模块，用来验证检索、问答和规划策略。

这样拆是因为一个 Agent 从用户请求到真实行动，中间不只是“模型回答”这一件事，而是包含入口适配、意图判断、上下文组织、计划生成、工具执行、状态恢复、证据检索、结果反馈和治理审计等多个职责。每一层都应该有清楚边界：

- 入口层统一 Web API、前端、CLI、飞书等来源。
- 路由层判断请求应该走 ask、capture（细分 text/link/file 三种来源）、delete_knowledge、solidify_conversation、direct_answer 还是 summarize_thread，无法判定时走 unknown 澄清分支。
- 运行时 / 编排层用 LangGraph 管理 entry 总流程、checkpoint、interrupt/resume 和状态流转。
- Workflow / step planning 层通过 `WorkflowRegistry` 选择 `WorkflowSpec`；只有需要步骤执行的 workflow 由 planner 把 `WorkflowStepSpec` 确定性投影成 `PlanStep`，例如删除和固化会把关键步骤变成可展示、可恢复、可确认的运行时步骤视图。
- 工具层把模型意图转换为受治理的系统动作。
- 记忆层区分短期执行现场和长期知识。
- 检索与推理层用独立的 planner LLM 做 query understanding，再把图谱、本地知识和网络搜索组织成 evidence。
- 执行与反馈层通过 SSE、run snapshot、事件和前端确认面板暴露过程。
- 观测与治理层提供日志、鉴权、限流、用户隔离和测试基础。
- 评测模块用 Open RAGBench、MultiHopRAG 和项目自定义用例评估检索、问答、rerank、plan/replan 等策略。

所以 `memory / tools / planning` 是其中最关键的三条工程边界，但不是全部架构。它们分别解决“什么能作为知识”、“动作如何安全执行”、“复杂任务如何可恢复编排”。如果这些职责全部塞进一个 Agent loop，短期对话、长期事实、工具副作用、计划状态和审计反馈会混在一起，很容易出现历史回答被当事实、工具结果归属错误、删除动作绕过确认、checkpoint 恢复后状态不一致等问题。

### 3. LangChain 在这里承担什么价值？

LangChain 在本项目里是**底层原语层**，不是编排框架。项目只依赖 `langchain_core`，用到的就两类东西：

- **工具抽象**：`BaseTool` 和 `@tool` 装饰器（`tools/` 下的 `delete_note`、`graph_search`、`web_search`、`capture_text`、`capture_upload` 等），让工具有统一的 schema、描述和调用协议，能直接被模型 tool-calling 识别。
- **消息类型**：`AnyMessage`、`AIMessage`、`ToolMessage`（`orchestration_models.py`、`gateway.py`），作为 LangGraph state 里对话历史的标准载体。

关键取舍是：项目**没有用** LangChain 的 `AgentExecutor`、Chain、`LCEL` 那套高层编排。原因是高层链路封装会把控制流藏进框架内部，而本项目恰恰要把控制流握在自己手里（ToolGateway 治理、PlanValidator 校验、HITL interrupt）。所以只取 LangChain 最稳定的工具/消息原语，编排交给 LangGraph，治理交给自研网关。这样既复用生态（任何 LangChain 工具都能接），又不被框架绑架控制流。

### 4. LangGraph 在这里承担什么价值？

LangGraph 承担**可恢复的状态机和 checkpoint** 能力，是项目真正的编排核心。具体用到：

- `StateGraph`（`orchestration_graph.py`）把入口路由、planning、ReAct、工具执行、确认、生成等节点组织成图。
- `PostgresSaver` 把同一 `thread_id` 下的对话、计划步骤、工具归属、pending confirmation、执行事件都持久化到 Postgres checkpoint。
- `add_messages` reducer 管理 `AgentGraphState` 里消息的累积。
- `interrupt()` / `Command` 实现 HITL：删除知识时在确认节点中断，用户确认后用**同一 checkpoint resume**，而不需要重新规划。

它的价值不是“让 Agent 更智能”，而是让多轮任务、高风险确认、暂停恢复和步骤状态变成可控、可持久化、可恢复的流程。这也是为什么选 LangGraph 而非 LangChain AgentExecutor：后者没有原生的 checkpoint + interrupt-resume 模型，做不了 crash 后从中断点续跑。

### 5. LangExtract 在这里承担什么价值？

需要先澄清一个常见误解：LangExtract 在当前生产链路里其实是**休眠的可选层**。`extract/` 模块代码仍在，但 `PreExtractService` 只被 scripts 和 tests 引用，capture 和 ask 主链路都不调用它。

它原本设想的位置是 capture 流水线的语义预抽取，但当前已改成 Unstructured 主导结构化处理：原始内容先经 Unstructured partition 成 typed elements，再由 `chunk_by_title` 生成结构化 chunk。LangExtract 不再作为 Graphiti 的默认前置步骤，因为二者在语义抽取层更像可替代 provider，串联会造成重复抽取、schema 冲突和成本叠加。所以现在 LangExtract 的定位是“保留的可选 semantic extraction provider”，而不是任何主链路的必经步骤。

注意 ask 前的 query understanding **不属于 LangExtract**。它由独立的 planner 配置 `settings.planner`（env 前缀 `PERSONAL_AGENT_PLANNER_*`）驱动：`query_planner.py` 用 `qwen3-coder-flash` 和 strict `json_schema` 生成 `QueryUnderstanding / RetrievalPlan`，做 query rewrite、子查询拆分、filters 抽取和检索源路由。早期它曾借用 `settings.langextract` 配置，容易让人误以为查询理解依赖抽取层，现在已拆成独立配置。

### 6. LangSmith 在这里承担什么价值？

LangSmith 承担**可观测性 / tracing**，是治理层的一部分，且设计成“可选且永不影响主链路”。具体接入（`core/langsmith_tracing.py` + `core/llm_trace.py` + `core/embedding_trace.py`）：

- **配置桥接**：`configure_langsmith_environment` 把项目的 `LangSmithConfig`（`settings.langsmith`）翻译成 LangSmith 标准的 `LANGSMITH_*` 环境变量，统一开关。
- **trace 上下文**：`entry_orchestrator` 在 entry / ask 入口用 `langsmith_trace_context` 包住整条链路，把 user/session/intent 等 metadata 挂上 run。
- **LLM / embedding span**：LLM 和 embedding 调用用 `traceable` 和手写 span 上报，并通过 `report_usage_metadata` 把 token usage 汇总，让成本能在 trace 树上 roll up。
- **采样 + 降级**：`sample_rate` 控制采样；未命中采样时显式 `tracing_context(enabled=False)`，避免全局 tracer 继续发 run。所有 tracing 代码都包在 try/except 和 `nullcontext()` 里，**tracing 失败绝不能让业务调用挂掉**。

价值是：多层 Agent + 多路检索 + 工具链很难靠日志排查，LangSmith 给了一条端到端的可视化 trace（哪一步慢、哪一次 LLM 调用 token 暴涨、哪路检索没召回），且通过 `upload_inputs` 等开关控制敏感数据是否上传。它解决的是“线上为什么这次回答慢 / 贵 / 错”的可观测问题，不参与业务决策。

### 7. LangChain / LangGraph / LangExtract / LangSmith 各自的边界是什么？

四者职责完全不同，可以按“原语 / 编排 / 抽取 / 观测”四层来记：

```text
LangChain：提供工具与消息原语（BaseTool/@tool、AnyMessage/ToolMessage）
LangGraph：把任务流程变可恢复状态机（StateGraph + Postgres checkpoint + interrupt）
LangExtract：把文本变结构（可选 provider，当前主链路休眠）
LangSmith：把运行过程变可观测 trace（tracing + token 成本 + 采样，永不阻塞主链路）
planner LLM：把用户 query 变结构化检索计划（独立 settings.planner）
Graphiti：把知识关系变语义图谱
```

一句话区分：LangChain 给“积木”，LangGraph 决定“积木怎么拼、怎么暂停恢复”，LangExtract 是可选的“文本结构化积木”，LangSmith 在旁边“录像”，planner 和 Graphiti 各管查询理解和图谱。本项目的核心立场是只借用这些框架最稳定的部分，控制流和治理（ToolGateway / PlanValidator / HITL）始终自研掌握。

### 8. 为什么查询理解 / 抽取要独立配置模型？

因为它们需要稳定的结构化输出，而这和主对话模型的诉求不同。ask 侧的查询理解用独立的 planner 配置（`settings.planner`，默认 `qwen3-coder-flash + DashScope OpenAI-compatible endpoint`），关键原因是它支持 OpenAI 风格的 `response_format=json_schema` strict 输出；可选的 LangExtract 抽取层（`settings.langextract`）同理也单独配置。

主对话模型、Graphiti 抽取模型、planner 模型和 LangExtract 模型相互解耦，可以让每条链路选最适合的模型：主对话关注回答质量，Graphiti 关注实体关系抽取，planner 关注查询理解的 schema 稳定性和低成本，LangExtract 关注抽取 schema 稳定性。这里特别要强调 planner 和 LangExtract 是**两套独立配置**——查询理解是 ask 侧关注点，和 capture 侧的抽取层没有依赖关系，早期共用配置是实现便利，现已拆开避免误会。

如果 planner 未配置或调用失败，ask query planner 会 fallback 到默认 plan 和启发式 filters。capture 侧由 Unstructured 负责结构化 partition/chunk，不依赖 LangExtract 作为入库前置；这样也避免了 LangExtract 和 Graphiti 在语义抽取层重复工作。

### 9. 这个项目最体现 Agent 工程能力的点是什么？

最值得讲的是“边界设计”：短期 checkpoint 和长期 note/chunk 分离，Unstructured 做结构化 chunk、独立 planner LLM 做查询理解，Graphiti 只做语义索引，回答前统一 evidence；工具不是裸函数，而是通过 ToolGateway 执行 timeout、retry、rate limit、HITL、幂等和审计；规划不是普通 Todo，而是通过 PlanValidator 校验后进入 checkpoint-safe 的步骤执行。

也就是说，项目的重点不是 prompt 写得多复杂，而是把 LLM 的不确定输出放进了系统级安全边界里。

### 10. evals 模块在这里承担什么价值？

`evals/` 是项目的评测闭环，作用是回答一个很关键的问题：这些检索、图谱、rerank、planning 改动到底有没有让 Agent 变好。

当前评测分几类：

- `evals/open_ragbench/`：基于 Open RAGBench 做单跳 RAG 检索评估，关注 MRR、Recall@k、NDCG@k。
- `evals/multihoprag/`：基于 MultiHopRAG 做多跳检索评估，关注跨文档 evidence set 是否被召回。
- `evals/test_ask_quality.py`：验证 Ask 质量和回答链路。
- `evals/test_retrieval_strategies.py`：对比本地、图谱、hybrid、rerank 等检索策略。
- `evals/test_plan_replan.py`：评估 plan / replan 行为是否符合预期。

配套的 [docs/rag-eval-results.md](rag-eval-results.md) 记录了关键结果，例如 Open RAGBench 上 optimized hybrid 的 MRR、Recall，MultiHopRAG 上 graphiti / structural / hybrid 的对照，以及 Microsoft GraphRAG CLI provider 的实验结论。

evals 最大的价值不是产出好看的数字，而是**证伪直觉**。几个真实例子：原以为"窄预算丢证据"是多跳召回低的主因，放宽 ContextPack 到 24/12000 后所有指标反而下降（MRR 0.375 → 0.283），证明瓶颈在排序质量而非预算大小；原以为"多开一路 structural 一定更好"，结果 hybrid 在多跳上只微升 MRR、却拉低了 R@5/NDCG@5，证明召回数量不等于效果；原以为 Microsoft GraphRAG 这种重型方案会更强，实测在本项目的 note-id 评价口径下低于 Structural + Graphiti hybrid。这些结论都是先有假设、再被数据推翻或修正，而不是靠感觉选策略。这是 evals 在这个项目里真正承担的角色。

### 11. evals 和普通单元测试有什么区别？

单元测试主要证明代码边界是对的，例如 schema 校验、工具确认、PlanValidator 阻断危险计划、checkpoint 状态转移。它回答的是“代码有没有按预期运行”。

evals 证明策略效果，例如 query rewrite 有没有提升召回，Graphiti 是否改善多跳 top-k，LLM rerank 是否优于 heuristic，hybrid provider 是否比单一路径更稳。它回答的是“这个 Agent 是否真的更会找证据、更会回答、更会规划”。

所以 evals 是 Agent 工程里很重要的一层：没有评测，很多改动只是看起来更高级；有了 MRR、Recall、NDCG、按 question_type 的拆分和结果文件，才能判断策略是否值得保留。

## 记忆层

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

ask 前的 query understanding 会判断 `needs_episodic_context`。除了 LLM 理解，`query_planner.py` 还内置 `_looks_like_episodic_query` 启发式作为兜底（命中"上次/之前/做过/继续/那个任务"等历史行为标记词时置真）。当问题指向用户自己的历史行为时，系统才会把 `MemoryEpisode` 转成 `episode` evidence 进入排序。

这样设计是为了避免情景记忆污染事实类回答：问"光合作用原理"不应该把"上周你帮我整理过笔记"这种轨迹翻出来。情景记忆只在与历史行为相关时才作为证据，且在 evidence 排序里和 note/chunk 一起按相关度竞争预算。

## Prompt 工程

### 1. 项目里的 prompt 是怎么组织的？集中管理还是散落？

诚实讲：**没有中心化 prompt 仓库**，prompt 都是代码内的字符串拼接（f-string / 模块级常量），就近定义在使用它的模块里。比如答案生成的 system prompt 是 `runtime_llm.py` 的 `_ANSWER_SYSTEM_PROMPT`，几个 answer prompt 在 `runtime_ask.py` 的 `_build_unified_answer_prompt / _build_graph_answer_prompt / _build_local_answer_prompt / _build_web_answer_prompt`，router prompt 在 `router.py`，planner 在 `query_planner.py` 的 `_PLANNER_SYSTEM`，rerank 在 `rerankers.py`，摘要在 `thread_summarizer.py`，ReAct 在 `orchestration_nodes/`。

这是"够用、跟代码走"的风格。为了缓解散落带来的措辞漂移，把会被多处复用的约束抽成了共享常量——最典型的是 `_DIALOGUE_CONTEXT_POLICY`（`runtime_ask.py`），被 unified/graph/local/web 四个 answer prompt 共用，避免"对话线索不是事实证据"这句 grounding 约束在四个地方各写一遍、改一处漏三处。

面试可以坦诚的不足：prompt 散落、无模板引擎、无中心治理；改一处全局 grounding 措辞仍可能要跨文件同步。

### 2. 结构化输出怎么约束？为什么不是所有 LLM 调用都用 json_schema？

按链路分级，是有意识的设计，不是一刀切：

- **strict json_schema + Pydantic 双保险**（最强）：用在内部决策链路。query planner 用 `_PLANNER_SCHEMA`（`additionalProperties:false` + 全字段 required）+ 解析成 `QueryUnderstanding`；LLM rerank 用 strict schema 返回 `ranked_ids`；LangExtract 预抽取也是 strict。这些环节的输出要被代码消费，格式错一点下游就崩，所以约束到最强。
- **json_object（弱约束，只保证合法 JSON）**：用在 router、replanner、ReAct。它们结构相对简单，再用 Pydantic（如 `RouterDecision`）在解析侧兜底。
- **自由文本（无 response_format）**：四个面向用户的 answer prompt 全部是自由文本输出。

关键取舍是：**内部决策要确定性、面向用户的生成要表达自由**。如果给 answer 也套 schema，回答会变得机械、像填表，所以生成环节放开格式，citation 编号用"软要求"+ 下游 verifier 校验来兜，而不是硬 schema。

### 3. evidence 是怎么注入 prompt 的？怎么防止模型引用没给它的证据？

统一证据池注入时，每条 `EvidenceItem` 按 `[E1] [E2] …` 编号，source_type 映射成中文标签（图谱事实 / 笔记 / 原文片段 / 网络搜索 / 工具结果 / 历史执行记录），带上 title、URL、source_span、score、rank_reason，内容截断到约 700 字。grounding 指令明确三条："只基于下面统一证据池回答""每个关键结论尽量标注证据编号如 [E1]""证据不足或冲突要明确说明，不要补空白"。

最值得讲的一个细节是 **hint gating**（`runtime_ask.py` 约 824 行）：注入 prompt 的 citation_hint / match_hint 只包含 `ContextPack.selected` 里幸存下来的 source_id，也就是说**只有过了 rerank + 字符预算筛选的证据**才能进 prompt 提示。这防止了被裁掉的低分证据"偷渡"进模型视野，保证"模型看见的"和"用户最终看到的引用"一致。这条有专门的测试 `tests/test_unified_prompt_gating.py` 守着——是项目里唯一直接断言 prompt 字符串内容的测试。

### 4. prompt 里有哪些防幻觉 / 安全边界指令？

安全约束是 **prompt 里说 + 控制流里拦** 双保险，不只靠 prompt：

- **对话/摘要不是事实**：`_DIALOGUE_CONTEXT_POLICY` 明确"对话线索只用于理解指代，不是事实证据，不得把历史助手回复当回答依据，与当前证据冲突以当前证据为准"。ThreadSummary 压缩 prompt 还要求助手推测只能进 `assistant_assumptions`、无证据判断进 `unverified_claims`。
- **不能编造 note_id**：delete 候选定位 prompt 写"不要执行删除，也不要生成不存在的 ID"。
- **resolve 只能从候选选**：写"只在目标与候选明显对应时选一条，不确定或多候选返回 null"。
- **删除要确认**：不是靠 prompt 自觉，而是 router 强制 `delete_knowledge` 默认 `requires_confirmation=true, risk_level=high`，ReAct 节点还显式拦截写操作工具。

这里的口径是：prompt 指令是"软约束"，真正不可绕过的是控制流里的 PlanValidator / PolicyEngine / HITL。prompt 负责让模型"通常照做"，代码负责"绝不越界"。

### 5. 为什么 thread 摘要要拆成两个不同的 prompt？

因为两个目标会打架。`thread_summarizer.py` 里 `summarize_chat`（`_CHAT_DIGEST_PROMPT`）产出的是**面向用户的群聊纪要**，要可读、像人写的总结；`compress_context`（`_CONTEXT_COMPRESSION_PROMPT`）产出的是**面向上下文窗口压缩的结构化 ThreadSummary JSON**，要分桶（user_goals / confirmed_decisions / assistant_assumptions / unverified_claims …）、要机器可消费。

如果共用一个 prompt，要么纪要被 JSON 结构带得不像话，要么结构化摘要被"写得好看"的要求污染了字段边界。所以刻意拆开，文件 docstring 里也写明"不能共用 prompt"。这是个小但能体现"prompt 要按消费方设计"的点。

### 6. 回答语言和口吻是怎么控制的？

口吻在 system prompt 里定义：`_ANSWER_SYSTEM_PROMPT` 要求"严谨、善于归纳，首要任务不是复述检索片段"；direct_answer 分支要求"友好、简洁、保持简短"。回答语言目前**硬编码中文**（多个 answer prompt 直接写"用自然中文回答"），内部 prompt（planner / rerank）用英文。

诚实的不足：没有根据用户输入语言动态切换回答语言的逻辑，多语言适配是待补项。

### 7. prompt 有没有版本管理和测试？

基本没有，这是要正视的短板：

- **版本号形同虚设**：observability 的 LLM trace 有个 `prompt_version` 参数，但默认 `"v1"`，除了 graphiti 抽取显式传过，其余调用点都吃默认值，没有真正的版本演进、灰度或 A/B 能力。
- **测试偏行为不偏文本**：router / planner / replanner / verifier 等测试验证的是分类、解析、降级行为，不是 prompt 文本快照。唯一直接断言 prompt 内容的是 `test_unified_prompt_gating.py`（守 hint gating）。没有 prompt 快照测试、没有 golden 文件、没有系统化 prompt eval，prompt 质量回归目前主要靠人。

如果继续生产化，这块要补：把高频 prompt 抽到可版本化的位置、给关键 grounding 约束加快照测试、把 prompt 变更纳入 evals 回归。

## 工具层

### 1. 你的工具层和直接把函数暴露给 LLM 有什么区别？

项目里的工具不是裸函数，而是受治理的系统能力。每个工具通过 LangChain `@tool` 生成 `BaseTool`，同时绑定显式 Pydantic args schema、`ToolGovernance`、统一 `ToolArtifact` 返回契约，并通过 `ToolGateway` 执行。

模型可以提出工具意图，但真正执行前会经过参数校验、风险判断、ReAct allowlist、确认机制、幂等、timeout、retry、rate limit 和审计。

### 2. 为什么需要 ToolGateway？

ToolGateway 是模型意图和真实系统副作用之间的执行边界。业务工具只负责业务动作，权限、确认、限流、超时、重试、幂等、审计这些系统能力集中在 Gateway。

比如 `delete_note` 不能因为模型生成了调用就直接删除。Gateway 会检查它是高风险工具、需要确认、确认执行时必须有 idempotency key，并记录结构化审计事件。

### 3. `risk_level`、`side_effects`、`permission_scope` 区别是什么？

`risk_level` 表示危险程度，例如 low、medium、high。`side_effects` 表示工具会造成什么类型的系统影响，例如本地读、外部网络、写长期记忆、删除长期记忆。`permission_scope` 表示执行这个动作需要什么权限域，例如 `memory:read`、`memory:write`、`memory:delete`。

三者一起描述工具治理：风险决定是否允许自主调用，副作用决定执行保护和审计重点，权限域进入当前已落地的 `PolicyEngine`，用于输出 allow / deny / require confirmation / require escalation。

这里的 policy engine 属于观测与治理层的横切能力，但会被不同业务层消费。落到工具层，它会判断某次工具调用是否 allow / deny / require confirmation / require escalation；落到记忆层，它负责长期知识的 capture、search、delete、graph sync 等访问策略。

当前项目已经落地统一 `PolicyEngine`，核心代码在 `src/personal_agent/policy/`。它接收归一化的 `PolicyInput`（action、user_id、session_id、source_platform、tool_name、resource、risk_level、side_effects、permission_scope、requires_confirmation、confirmed、react_allowed_tools、resource_owner、workspace、execution_mode 等），输出 `PolicyDecision`。决策结果用单一 `effect` 枚举表达（`allow / deny / require_confirmation / require_escalation`），并带 `rule`、`reason`、`audit_required`，外加派生的 `allowed / needs_confirmation / needs_escalation` 便捷属性。

实际接入点包括：

- `ToolGateway`：统一处理 ReAct 自主守卫、高风险确认门、deny override，并把非放行决策写入 policy audit。
- `MemoryFacade`：长期记忆 add/update/delete 进入 owner 校验和删除确认策略。
- `AgentRuntime`：从 `Settings.policy` 构造 `PolicyRules`，把同一个 engine 注入工具层和记忆层。

所以现在不再只是治理元数据，而是已有可执行的策略层；后续要补的是 workspace/tenant/RBAC/ABAC、更细粒度来源策略和持久化审计。

### 4. 为什么 `delete_note` 不能被 ReAct 自主调用？

ReAct 是探索式循环，适合低风险只读工具，比如 graph search 或 web search。删除长期知识是高风险副作用，必须经过确定性计划、目标解析、用户确认和幂等保护。

如果允许 ReAct 自主删除，模型可能在没有充分确认目标的情况下执行不可逆动作，所以 Gateway 和 PlanValidator 都会阻止高风险或需确认工具进入 ReAct 自主路径。

### 5. 那 ReAct 还有什么使用场景？

有。当前项目不是不用 ReAct，而是把它限制在**单个计划步骤内部的低风险探索**。

典型场景是检索类步骤：planner 可以生成 `execution_mode="react"` 的 `retrieve` 步骤，让模型在有限轮次内根据观察结果决定是否继续调用 `graph_search` 或 `web_search`。比如删除知识前，系统需要先找候选笔记；这一步可以用 ReAct 探索图谱或网络线索，但最终删除目标仍必须经过 `resolve` 映射到真实 `note_id`，再进入 `delete_note` 的确认流程。

当前 ReAct 的边界是：

- 只在 planning 的单步内部使用，不替代整体计划执行器。
- 步骤的 `allowed_tools` 默认为空（read-only），低风险只读工具如 `graph_search / web_search` 是在具体 `WorkflowStepSpec` 上显式声明的，例如 ask 检索步骤显式放行 `graph_search / web_search`，delete 的 retrieve 步骤只放行 `graph_search`，没有全局自动白名单。
- 受 `allowed_tools` 和 `max_iterations` 限制（硬上限 5 轮）。
- 高风险、写入、删除、需要确认的工具不能进入 ReAct（PlanValidator 强制 `risk_level=high` 和 `requires_confirmation=true` 的工具不允许出现在 react 步骤）。
- 每轮 thought/action/observation 会进入事件流和 checkpoint 状态。

所以 ReAct 的价值是“受控探索”，不是“自主执行所有动作”。它适合证据不明确、需要迭代检索的场景；不适合删除、写入、外发这类副作用动作。

### 6. ToolArtifact 为什么统一成 `ok / data / error / error_kind / evidence`？

统一 artifact 可以让编排层不理解每个工具的私有返回结构。成功、失败、证据和待确认状态都走同一种机器可读结构。失败时除了 `error` 自然语言文本，还带 `error_kind`（transient / invalid_param / permission / unrecoverable）机器可读分类，Gateway 据此决定是否重试（见后面 retry 那题）。

这对计划进度、错误恢复、HITL、审计和 evidence 组装都很重要。尤其是工具返回失败时，系统应该看 `ok=false` 和结构化 error / error_kind，而不是猜 content 里的自然语言。

### 7. 工具结果为什么不直接写入用户 messages？

工具结果属于内部执行通道，不一定适合用户直接看，也不应该污染对话历史。项目用 `tool_messages` 保存内部工具交换，并通过 `ToolTrackingSubState` 记录 pending step id、tool call id、工具名、输入和 ReAct iteration。

这样 checkpoint 恢复后能做归属校验，避免把旧工具结果消费到新的步骤里。

### 8. 当前工具层最大不足是什么？

主要有三个：PolicyEngine 已落地基础规则和可配置 allow/deny 覆盖，但还缺 workspace/tenant/RBAC/ABAC 等更完整权限模型；审计事件还没有独立落库；幂等账本还是进程内实现。

这意味着当前已经有统一策略引擎、轻量 Tool Runtime 和治理契约，但还不能说完整生产级多租户权限、审计查询和跨进程幂等都落地了。

## 规划层

### 1. 当前 planning 是怎么落地的？

当前 planning 已经落地为 **Workflow / Step Planning Layer**，不是开放式自主 planner。`ask_branch / capture_branch / delete_knowledge / solidify_conversation` 本质上都是 workflow；固定拓扑已下沉为声明式 `WorkflowSpec / WorkflowStepSpec`，由 `WorkflowRegistry` 按 intent 选择；只有 `delete_knowledge`、`solidify_conversation` 这类需要步骤状态、HITL 或 checkpoint 恢复的 workflow，才由 `DefaultTaskPlanner` 确定性投影成 `PlanStep`。

其中 ask、capture、direct answer、summarize 有自己的普通 workflow 分支，不需要进入计划执行图；delete 和 solidify 会额外投影成 `PlanStep / PlanStepState / plan.results / step events`，再接入 PolicyEngine、ToolGateway、LangGraph checkpoint、HITL 和前端计划面板。

这个判断很重要：如果面试官追问“这些步骤不都是固定的吗”，应该坦诚回答“是的，固定流程就是系统维护的 WorkflowSpec，不让 LLM 自由发明控制流”。这样比强行包装成通用 planner 更可信。

### 2. WorkflowSpec / WorkflowRegistry 解决了什么？

它把“流程拓扑”和“局部语义判断”拆开。

当前执行链路是：

```text
Router 识别 intent
  -> WorkflowRegistry 选择 WorkflowSpec
  -> projection_policy="step_projection" 时 DefaultTaskPlanner 确定性投影 PlanStep
  -> PlanValidator 校验步骤结构、依赖、工具和风险
  -> LangGraph 计划执行图推进 PlanStepState
  -> ToolGateway / PolicyEngine / HITL 执行副作用
  -> DecisionNode 只处理局部 LLM 语义判断
```

几个关键点：

- `WorkflowSpec` 是业务流程真源，`WorkflowStepSpec` 定义固定节点、步骤依赖、LLM decision node、工具、风险等级、副作用、HITL、恢复策略，以及分支控制字段 `branch_policy` 和 `conditional_edges`（用于 human_select / clarify / abort 这类条件跳转，target 可为 `END / clarify / abort` 哨兵）。
- `WorkflowRegistry` 负责按 intent 选择 spec，避免 LLM 临场设计流程。
- `DefaultTaskPlanner` 的 planning 路径不再调用 LLM，而是对需要步骤执行的 workflow 做确定性投影。
- LLM 只在执行期真正需要语义判断的节点出现，例如 query understanding、删除候选选择、solidify 草稿、evidence rerank、低风险 ReAct 检索。
- 真正 autonomous planner 只作为未来能力，用于无法映射到已有 workflow、需要多个低风险工具组合、且有 eval 和 guardrail 覆盖的开放式任务。

这样更符合生产 Agent 的常见取舍：确定流程用 workflow，不确定局部用 LLM decision node，开放式 planner 只在确实需要时启用。

### 3. 规划层和普通 Todo list 的区别是什么？

普通 Todo list 只是自然语言步骤，本身不参与系统执行。项目里的规划层更准确地说是**步骤化编排层**：它不独占校验、恢复和审计能力，而是把这些能力接到同一个执行流程里。

具体来说：

- 规划层负责把需要步骤执行的 `WorkflowStepSpec` 确定性投影成结构化 `PlanStep`，表达步骤类型、依赖关系、工具意图、风险等级和失败策略，并保留 `workflow_id / workflow_version / workflow_step_id / projection_kind` 来源字段。
- 执行期把 `PlanStep` 转成 `PlanStepState`，把每一步状态和结果放进 `AgentGraphState.plan`。
- 校验分两层：① **spec 契约层**由 `WorkflowSpecValidator`（`workflow_validator.py`）在声明期校验 WorkflowSpec 自洽性（step_id 唯一、依赖可解析无环、conditional_edges target 合法、projection_policy 枚举、delete_longterm 必须 high+confirmation+hitl 等不变式），并由 `validate_registry_against_capabilities` 做 spec↔真实工具能力的一致性闸门；② **运行时投影层**由 `StepProjectionValidator`（当前兼容入口仍叫 `PlanValidator`）校验投影出的 `PlanStep` 结构、依赖图和 intent 规则；工具参数、风险治理和执行策略则依赖工具层的 args schema、`ToolGovernance`、`PolicyEngine` 和 `ToolGateway`。
- 可恢复能力来自 LangGraph checkpoint；规划层的作用是把 step status、`plan.results`、pending step 和依赖关系保存成 checkpoint-safe 状态，让恢复后知道从哪一步继续。
- 审计和事件也不是 planning 独有，工具调用审计来自工具层，运行事件来自 `AgentEvent`；规划层负责把 `plan_created / step_started / step_completed / step_failed` 等步骤事件串起来。

所以更准确的表述是：规划层不是单独实现所有安全能力，而是把 workflow 的关键步骤投影成可被工具层校验、可被 checkpoint 恢复、可被事件系统观察的步骤图。它的价值是“组织和约束执行顺序”，不是替代 PolicyEngine、ToolGateway、checkpoint 或审计系统。

### 4. 哪些任务会进入 planning？哪些不会？

当前真正进入 planning 的主要是 `delete_knowledge` 和 `solidify_conversation`。

普通 ask、capture、direct answer、summarize 不进入规划层，因为它们有直接 Graph 分支和 `execution_trace`，不需要额外步骤状态。这样可以避免所有请求都被过度规划。

需要注意的是，当前这里的 planning 不是完全开放式的自主规划，而是已经落地的 **intent-specific workflow planner**。`delete_knowledge` 和 `solidify_conversation` 的主干由 `WorkflowSpec` 固定声明：

```text
delete_knowledge: retrieve -> resolve -> delete_note -> compose
solidify_conversation: compose -> capture_text
```

它们进入 planning 的原因不是“需要 LLM 自由编排步骤”，而是需要复用统一的 `PlanStep / PlanStepState / PlanValidator / plan.results / HITL / step events / checkpoint resume` 这一套执行壳。也就是说，当前 planning 的价值是“把固定 workflow 表达成可校验、可观察、可恢复的步骤图”，而不是让模型随意设计流程。

面试里可以坦诚讲：这不是“通用自主 planner 已经成熟”，而是“固定 workflow 已经下沉为 WorkflowSpec，只有需要步骤执行的 workflow 才通过 planner 确定性投影成可执行步骤”。如果继续生产化，planner 可以进一步扩展到选择 workflow、填充目标、解释步骤，或在有 eval 和 guardrail 的低风险场景生成局部检索子步骤。

### 5. `delete_knowledge` 为什么是 `retrieve -> resolve -> delete_note -> compose`？

删除的关键风险是目标不明确。`retrieve` 先找候选线索，比如 graph episode uuid；`resolve` 再把线索映射成本地真实 `note_id`；`delete_note` 首次调用只生成确认 payload，用户确认后才真正删除；`compose` 最后生成用户可见结果。

这个流程保证删除不是 planner 直接拍脑袋决定，而是先从真实知识库候选中解析目标，再通过 HITL 执行。

### 6. 为什么 `delete_note.note_id` 不能由 planner 直接填？

因为 planner 是 LLM 输出，可能编造 ID、误解用户指代或选错对象。`note_id` 必须来自运行时 `resolve` 步骤，从 graph episode 映射或本地 note 候选中选择。

后续 `delete_note.tool_input.note_id` 通过 `plan.results` 动态注入，避免把模型臆造参数直接传给高风险工具。

### 7. `resolve` 如何防止 LLM 编造 note id？

`resolve` 给 LLM 的输入只包含已有候选的 `note_id / title / summary`，要求它只能从候选 ID 中选择；不确定或多候选时返回 null。系统不接受 LLM 生成的新 ID。

如果图谱 episode 能映射回 note，就优先用真实映射；如果仍然没有明确候选，就失败并要求用户提供更具体描述。

### 8. `PlanValidator` 具体防住了什么？

它会检查步骤类型是否合法、依赖是否存在、依赖图是否有环、工具是否注册、工具参数是否满足 args schema、风险等级和失败策略是否合法、ReAct 是否越权调用高风险工具，以及 intent 特定规则是否满足。

比如 `delete_knowledge` 必须包含 `delete_note`，且 `delete_note` 必须依赖 `resolve`；`solidify_conversation` 的 `capture_text` 必须依赖 `compose`。校验不通过就不会执行危险工具。

### 9. `PlanStep` 和 `PlanStepState` 区别是什么？

`WorkflowStepSpec` 是 workflow 源契约，描述固定节点、依赖、decision node、工具、副作用、HITL 和恢复策略。`PlanStep` 是需要步骤执行的 `WorkflowStepSpec` 经 planner 确定性投影后的运行时步骤视图，并携带 workflow 来源字段。`PlanStepState` 是进入 LangGraph 后的 checkpoint-safe 执行状态，描述做到了哪里、是否失败、重试几次、结果是什么。

一个偏静态计划，一个偏 checkpoint 中的可恢复运行现场。

### 10. ReAct 能不能替代 planning？

不能。ReAct 是单步内部的探索策略，适合低风险只读检索。Planning 是跨步骤的编排和恢复机制，负责依赖、状态、HITL 和高风险流程。

项目刻意把 ReAct 限制为 planning 的局部能力，而不是让它替代计划执行器。

## HITL 与删除恢复

### 1. 删除 note 的完整确认流程是什么？

用户提出删除请求后，router 进入 `delete_knowledge` planning。计划执行 `retrieve` 找候选，`resolve` 确认真实 `note_id`，然后调用 `delete_note`。

第一次 `delete_note` 不删除数据，只返回 pending confirmation。Graph 把 payload 写入 `AgentGraphState.pending_confirmation` 并 `interrupt()`。用户确认后，Graph 用同一 `thread_id` resume，把 `confirmed=true` 和 `idempotency_key` 注入工具输入，再次调用 `delete_note` 才真正删除 note、chunk、review card 和可用的 graph episode 映射。

### 2. 用户拒绝确认时会怎样？

Graph 会把当前步骤标记为 skipped，递归跳过依赖它的后续步骤，清空 `pending_confirmation`，并返回取消说明。不会执行真实删除。

### 3. 为什么确认后还需要 `idempotency_key`？

因为确认请求可能重复提交，checkpoint resume 可能重放，网络或服务异常也可能导致重复执行风险。`idempotency_key` 用 thread/run/step 等信息标识同一次确认动作，Gateway 用它阻断重复副作用。

当前幂等账本是进程内实现，所以能覆盖单进程重复确认，但服务重启或横向扩容后还需要持久化幂等账本。

### 4. pending confirmation 是长期审批表吗？

不是。它属于当前 thread/run 的短期执行现场，保存在 LangGraph checkpoint 里。它的作用是暂停和恢复当前执行流程，不是长期业务审批系统。

如果未来做生产级审批，应有独立审批表、确认人、确认时间、权限和审计记录。

## 测试与评测

### 1. 你会怎么测试规划层不会生成危险计划？

可以做几类测试：校验没有 `resolve` 的删除计划必须失败；`delete_note` 不允许出现在 ReAct 步骤中；`delete_note` 必须声明 high risk 和 requires confirmation；`capture_text` 在 solidify 中必须依赖 compose；工具参数不满足 args schema 时不能执行。

这些是 unit / contract tests，目标是证明危险计划不能越过校验。实际分两份：`tests/test_plan_validator.py` 测运行时投影层（PlanStep 危险计划拦截），`tests/test_workflow_validator.py` 测 spec 契约层（WorkflowSpec 自洽性 + spec↔工具能力一致性闸门，例如未注册工具、要求确认的工具但步骤没声明确认都会被拦）。

### 2. 怎么测试 `delete_note` 必须经过确认？

构造删除请求，让第一次工具调用返回 pending confirmation，并断言长期存储没有被删除。然后模拟用户确认 resume，断言带 `confirmed=true` 和 idempotency key 后才删除目标 note、chunk、review card 和 graph mapping。

还要测用户拒绝、重复确认、缺失 idempotency key、目标不存在等边界。

### 3. 怎么评估长期记忆召回质量？

可以建立 memory eval：准备一批已 capture 的文档和问题，标注应该命中的 note/chunk，评估召回率、引用正确率、chunk 命中率、parent 回溯准确率、错误引用率。

还要加冲突和过期知识样例，测试系统是否能发现证据冲突，而不是引用旧知识。

### 4. 怎么评估 solidify 有没有写入错误事实？

设计长会话干扰样例：用户提出方案后否定、助手做出猜测但用户未确认、用户纠正前文、多个主题混杂。然后让用户要求固化，检查写入的 note 是否只包含用户明确要求固化的内容。

指标可以包括错误写入率、遗漏率、助手假设污染率、废弃方案污染率。

### 5. 单元测试和 Agent eval 的区别是什么？

单元测试验证确定性代码边界，例如 schema 校验、Gateway 策略、HITL 状态转移。Agent eval 验证模型参与后的整体行为，例如是否选对工具、是否解析对目标、是否把错误对话固化、是否在证据不足时澄清。

两者都需要：单元测试防回归，eval 发现模型和 prompt 层面的行为问题。

## 工程取舍与不足

### 1. 为什么没有一开始就做完整权限系统？

当前项目优先把 Agent 的主链路和关键工程边界跑通：入口统一、router 分流、LangGraph 编排、短期/长期记忆分离、WorkflowSpec、PolicyEngine、ToolGateway、PlanValidator、HITL、evidence 出口和基础观测。

现在 `permission_scope` 已经进入治理契约和 `PolicyEngine`，基础策略判断已落地：工具调用、记忆访问和入口来源都能通过统一 `PolicyInput -> PolicyDecision` 做 allow / deny / require confirmation / require escalation。还不能说完整 SaaS 权限系统已落地，是因为 workspace/tenant 维度、角色/属性权限、长期审计查询和审批流仍需补齐。

### 2. 为什么 Graphiti 不直接替代 Postgres？

Graphiti 擅长语义关系和实体检索，但不适合作为业务事实真源。Postgres note/chunk 保存原文、摘要、source、chunk、review card、graph mapping 和可引用证据。

这样图谱抽取失败、关系不完整或 episode 残留时，系统仍然有可回溯的业务真源。

### 3. 为什么没有所有任务都用 ReAct？

ReAct 有探索能力，但也有不确定性和循环风险。普通任务有确定分支，高风险任务需要受控计划和 HITL，不适合让 ReAct 自主决定。

项目只把 ReAct 用在单步内部的低风险只读探索，并通过 allowlist、risk guard 和 max iterations 限制边界。

### 4. 如果只能优化一周，你会优先做哪三件事？

第一，为删除 `resolve` 增加候选确认 UI，降低误删风险。第二，把工具审计和 policy decision 落到独立审计表，并关联 step id、tool call id、side effect、policy rule 和 decision effect。第三，建立 memory/planning eval 的最小集，覆盖删除目标解析、solidify 长会话干扰和 evidence 引用正确率。

这三件事直接提升生产安全性和可验证性。

### 5. 当前项目最大的生产风险是什么？

主要风险有：PolicyEngine 还缺 workspace/tenant/RBAC/ABAC 等生产级权限模型；审计未独立落库（当前只走日志和内存 sink）；幂等账本不是持久化（进程内 `InMemoryIdempotencyStore`）；结构化 ThreadSummary 虽已落地并随 checkpoint 持久化，但 solidify 还没强制只消费其已确认字段，长会话噪声仍可能渗入；知识冲突虽然已有版本链和 conflicted 标记，但缺少自动冲突检测和置信度模型。

这些不是概念缺失，而是从原型走向生产时需要补齐的治理能力。

## 深入追问（检索 / 编排 / 治理 / 可靠性）

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

## 情景判断追问（冲突 / 边界 / 取舍）

这一节是"如果……怎么办"式的情景题，考察在证据冲突、跨存储不一致、用户施压等边界下的判断口径。

### 1. 用户刚刚说“我生日是 1 月 1 日”，这算事实吗？

在当前 thread 中，它可以作为用户刚刚声明的会话事实，用于理解当前对话。但如果要长期记住，应该通过 capture 或 solidify 写入 `knowledge_notes`。如果未来回答需要长期引用用户生日，应该从长期记忆或当前明确上下文取证，而不是从不受治理的历史摘要里直接认定。

### 2. 如果 graph search 找到了关系，但 note/chunk 已经被删了，怎么办？

这说明图谱和 Postgres 之间可能存在孤儿 episode 或 graph fact。回答时应该降低或屏蔽无法回溯到 note/chunk 的 graph fact，不能把它当强证据引用。后续需要图谱对账、孤儿检测和删除同步重试。

### 3. 如果 web search 和本地 memory 冲突，怎么处理？

先看问题类型。如果是用户自己的长期知识或项目内部知识，优先本地 memory 和当前工具结果。如果是外部世界的最新事实，应使用当前 web evidence，并提示与本地记忆存在差异。

关键是不要混在一起让模型自行猜，而是把证据来源、时间、可信度和冲突显式进入 evidence 排序或回答说明。

### 4. 如果工具返回 `ok=false` 但 content 看起来像成功，你信哪个？

信结构化 artifact。`ToolArtifact.ok / error / data` 是工具层契约，content 只是消息流中的观察文本。编排层和审计都应该以 artifact 为准。

### 5. 如果用户说“不要确认，直接删”，系统应该听吗？

不应该。高风险工具的确认要求来自工具治理契约和系统策略，不应该被用户一句话绕过。用户可以表达意图，但系统仍必须走 HITL、幂等和审计。

### 6. 如果做成多用户 SaaS，第一步改哪里？

第一步是在现有 PolicyEngine 之上补 workspace/tenant 权限和审计落库。`user_id/session_id` 隔离只是基础，多用户 SaaS 还需要 RBAC/ABAC、工具级权限、来源权限、敏感数据策略、审计查询、删除恢复和幂等持久化。

## 面试收尾口径

可以用这段话收尾：

> 我这个项目真正想解决的不是“让 Agent 看起来什么都会”，而是让 Agent 在记忆、工具、workflow 编排和评测几个关键位置都有系统边界。短期现场用 checkpoint，长期事实用 note/chunk，语义关系用 Graphiti，回答依据统一成 evidence；固定流程由 WorkflowSpec/WorkflowRegistry 管理，删除和固化这类 workflow 会被确定性投影成可展示、可恢复、可确认的步骤；工具和记忆访问必须经过 PolicyEngine 与 Gateway，并经过 PlanValidator、HITL 和 checkpoint。这样模型可以参与理解和局部决策，但不能绕过可恢复、可校验、可审计的工程边界。
