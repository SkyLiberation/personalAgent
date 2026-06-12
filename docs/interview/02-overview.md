# 高频总览问题

### 1. 这个 personal agent 的核心链路是什么？

用户请求先进入 LangGraph entry，经过 router（`DefaultIntentRouter`，LLM 分类）判断 intent。普通问答、capture、direct answer、summarize 会走各自分支；需要明确步骤边界的高风险或复杂任务，例如 `delete_knowledge` 和 `solidify_conversation`，会进入 workflow step projection。其中 capture 按来源细分为 `capture_text / capture_link / capture_file` 三个意图，summarize 实际意图名是 `summarize_thread`，另有 `unknown` 作为无法判定时的澄清兜底。

问答路径会从长期记忆、图谱或外部工具中检索证据，统一成 `EvidenceItem`，再由 `ContextPack` 做去重、排序和预算裁剪，最后进入 prompt。写入路径通过 capture 工具把内容沉淀到 Postgres `knowledge_notes`，并可同步 Graphiti。删除路径会先从固定 `WorkflowSpec` 投影步骤、解析目标、生成确认，再通过 HITL resume 真正执行。

### 2. 你为什么采用多层 Agent 架构？

README 里当前工程不是只拆成 memory、tools、planning，而是分成入口层、意图识别 / 路由层、Workflow / 步骤投影层、运行时 / 编排层、工具层、记忆层、检索与推理层、执行与反馈层、观测与治理层；此外 `evals/` 作为评测模块，用来验证检索、问答和 workflow projection 策略。

这样拆是因为一个 Agent 从用户请求到真实行动，中间不只是“模型回答”这一件事，而是包含入口适配、意图判断、上下文组织、workflow 步骤投影、工具执行、状态恢复、证据检索、结果反馈和治理审计等多个职责。每一层都应该有清楚边界：

- 入口层统一 Web API、前端、CLI、飞书等来源。
- 路由层判断请求应该走 ask、capture（细分 text/link/file 三种来源）、delete_knowledge、solidify_conversation、direct_answer 还是 summarize_thread，无法判定时走 unknown 澄清分支。
- 运行时 / 编排层用 LangGraph 管理 entry 总流程、checkpoint、interrupt/resume 和状态流转。
- Workflow / step planning 层通过 `WorkflowRegistry` 选择 `WorkflowSpec`；只有需要步骤执行的 workflow 由 planner 把 `WorkflowStepSpec` 确定性投影成 `ExecutionStep`，例如删除和固化会把关键步骤变成可展示、可恢复、可确认的运行时步骤视图。
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

关键取舍是：项目**没有用** LangChain 的 `AgentExecutor`、Chain、`LCEL` 那套高层编排。原因是高层链路封装会把控制流藏进框架内部，而本项目恰恰要把控制流握在自己手里（ToolGateway 治理、StepProjectionValidator 校验、HITL interrupt）。所以只取 LangChain 最稳定的工具/消息原语，编排交给 LangGraph，治理交给自研网关。这样既复用生态（任何 LangChain 工具都能接），又不被框架绑架控制流。

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

注意 ask 前的 query understanding **不属于 LangExtract**。它由独立的 planner 配置 `settings.planner`（env 前缀 `PERSONAL_AGENT_PLANNER_*`）驱动：`query_step_projector.py` 用 `qwen3-coder-flash` 和 strict `json_schema` 生成 `QueryUnderstanding / RetrievalPlan`，做 query rewrite、子查询拆分、filters 抽取和检索源路由。早期它曾借用 `settings.langextract` 配置，容易让人误以为查询理解依赖抽取层，现在已拆成独立配置。

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

一句话区分：LangChain 给“积木”，LangGraph 决定“积木怎么拼、怎么暂停恢复”，LangExtract 是可选的“文本结构化积木”，LangSmith 在旁边“录像”，planner 和 Graphiti 各管查询理解和图谱。本项目的核心立场是只借用这些框架最稳定的部分，控制流和治理（ToolGateway / StepProjectionValidator / HITL）始终自研掌握。

### 8. 为什么查询理解 / 抽取要独立配置模型？

因为它们需要稳定的结构化输出，而这和主对话模型的诉求不同。ask 侧的查询理解用独立的 planner 配置（`settings.planner`，默认 `qwen3-coder-flash + DashScope OpenAI-compatible endpoint`），关键原因是它支持 OpenAI 风格的 `response_format=json_schema` strict 输出；可选的 LangExtract 抽取层（`settings.langextract`）同理也单独配置。

主对话模型、Graphiti 抽取模型、planner 模型和 LangExtract 模型相互解耦，可以让每条链路选最适合的模型：主对话关注回答质量，Graphiti 关注实体关系抽取，planner 关注查询理解的 schema 稳定性和低成本，LangExtract 关注抽取 schema 稳定性。这里特别要强调 planner 和 LangExtract 是**两套独立配置**——查询理解是 ask 侧关注点，和 capture 侧的抽取层没有依赖关系，早期共用配置是实现便利，现已拆开避免误会。

如果 planner 未配置或调用失败，ask query planner 会 fallback 到默认 plan 和启发式 filters。capture 侧由 Unstructured 负责结构化 partition/chunk，不依赖 LangExtract 作为入库前置；这样也避免了 LangExtract 和 Graphiti 在语义抽取层重复工作。

### 9. 这个项目最体现 Agent 工程能力的点是什么？

最值得讲的是“边界设计”：短期 checkpoint 和长期 note/chunk 分离，Unstructured 做结构化 chunk、独立 planner LLM 做查询理解，Graphiti 只做语义索引，回答前统一 evidence；工具不是裸函数，而是通过 ToolGateway 执行 timeout、retry、rate limit、HITL、幂等和审计；规划不是普通 Todo，而是通过 StepProjectionValidator 校验后进入 checkpoint-safe 的步骤执行。

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

单元测试主要证明代码边界是对的，例如 schema 校验、工具确认、StepProjectionValidator 阻断危险计划、checkpoint 状态转移。它回答的是“代码有没有按预期运行”。

evals 证明策略效果，例如 query rewrite 有没有提升召回，Graphiti 是否改善多跳 top-k，LLM rerank 是否优于 heuristic，hybrid provider 是否比单一路径更稳。它回答的是“这个 Agent 是否真的更会找证据、更会回答、更会规划”。

所以 evals 是 Agent 工程里很重要的一层：没有评测，很多改动只是看起来更高级；有了 MRR、Recall、NDCG、按 question_type 的拆分和结果文件，才能判断策略是否值得保留。

---

[← 返回索引 INDEX.md](INDEX.md)
