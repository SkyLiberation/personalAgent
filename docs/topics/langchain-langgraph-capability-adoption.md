# LangChain / LangGraph 能力接入评估

这份文档基于对当前代码的逐一核查（带 `file:line` 证据），盘点项目实际用了哪些 LangChain / LangGraph 能力、哪些没用，并评估"还有哪些能力值得接入"。

评估标准不是"框架还有什么没用就该补上"，而是：**某个能力能否解决项目已经承认的痛点，且不破坏"控制流与治理自研"这条架构原则。** 很多未使用的能力（`AgentExecutor`、LCEL、`with_structured_output`、`BaseRetriever`）是有意绕开的，接入反而是倒退。

## 架构前提

项目只依赖 `langchain_core`，刻意不用 `AgentExecutor` / `Chain` / `LCEL`，编排交给 LangGraph，治理（ToolGateway / PolicyEngine / StepProjectionValidator / HITL）全部自研。代码核对属实：

- `AgentExecutor` / `create_react_agent` / `create_tool_calling_agent`：全仓零命中。
- LCEL（`Runnable` / `|` 管道）：全仓零命中。
- ReAct 循环是自研 LangGraph 子图（`build_react_graph`，`orchestration_graph.py:150-187`）+ 直连 OpenAI `tools=` / `tool_choice=`（`orchestration_nodes/_helpers.py:113-114`），没有用 langchain 的 agent 封装，也没用预置 `ToolNode`（走自研 `ToolGateway.invoke_graph`，`tools/gateway.py:283`）。
- 唯一的 langchain_core 依赖面是 `BaseTool` / `@tool` + 消息类型。

## 能力使用面：已用 / 未用 / 自研替代

### LangGraph 已用能力

| 能力 | 证据 |
|---|---|
| `StateGraph` + `add_node` / `add_edge` / `add_conditional_edges` | `orchestration_graph.py:8,112-210` |
| 三层嵌套 subgraph（entry / react / plan_execution 互为节点） | `orchestration_graph.py:285,306,209` |
| `interrupt`（HITL，clarify + confirm 两处） | `orchestration_nodes/_steps.py:12`、`_entry.py:8` |
| `Command(resume=...)`（中断恢复） | `entry_orchestrator.py:13,403` |
| `PostgresSaver` checkpoint（硬要求，无内存/SQLite fallback） | `orchestration_graph.py:7,280,336-358` |
| `add_messages` reducer | `orchestration_models.py:17,276` |
| `stream(stream_mode="updates", subgraphs=True)` | `entry_orchestrator.py:267` |
| `get_state` | `entry_orchestrator.py:73,304` |
| `get_state_history` / `update_state`（checkpoint 时间旅行） | `entry_orchestrator.py:532-603` |
| checkpointer `list()`（快照导出） | `entry_orchestrator.py:455,476`、`scripts/export_thread_checkpoints.py:67` |

### LangGraph 明确未用能力

`langgraph.store` / `BaseStore` / `InMemoryStore`、`Send`、`RetryPolicy`、`CachePolicy`、`durability=`、`Pregel`；`stream_mode` 只用了 `updates`，未用 `values` / `messages` / `custom`。

### LangChain (langchain_core) 已用能力

- `BaseTool`（`tools/base.py:8`、`tools/registry.py:6`、`tools/gateway.py:12`）
- `@tool` 装饰器（各 tool 文件，如 `tools/capture_text.py:6`、`delete_note.py:5`）
- 消息类型 `AIMessage` / `HumanMessage` / `ToolMessage` / `AnyMessage`（`orchestration_models.py:15`、`_helpers.py:9` 等）

### LangChain 明确未用能力

`Runnable` / `RunnableConfig`、`callbacks`、`output_parsers`、`PromptTemplate` / `ChatPromptTemplate`、`with_structured_output`、`BaseRetriever`、`langchain_core.embeddings`（Embeddings 抽象）、`bind_tools`（生产代码用 OpenAI 原生 `tools=`）。

### 自研实现 vs 现成能力

| 项目自研 | 现成对应 | 证据 |
|---|---|---|
| retriever 接口（local/structural/graph/hybrid，签名各异：`search_notes`/`ask`/`rank_note_ids`） | `BaseRetriever` | `structural_retriever/store.py:46-94`、`graphiti/search_strategies.py:54-83` |
| RRF 融合 / heuristic + LLM rerank | `EnsembleRetriever` / `ContextualCompressionRetriever` | `graphiti/search_strategies.py:54-71`、`core/rerankers.py:25-61` |
| embedding 直连 OpenAI SDK + 本地哈希 fallback | `Embeddings` 抽象 | `core/embedding_trace.py:120-125`、`storage/postgres_memory_store.py:164-167` |
| Postgres 工具幂等账本 / 审计表（`tool_idempotency_ledger` / `tool_audit_events`） | langgraph `BaseStore` | `storage/postgres_tool_governance_store.py`、`tools/gateway.py` |
| `PromptSpec` registry（version / output_contract / owner + `template.format()`） | `PromptTemplate` | `core/prompts.py:7-16` |
| `responses.parse` + Pydantic，或 strict `json_schema` | `with_structured_output` | `core/llm_trace.py`、`core/llm_schemas.py` |
| ToolGateway error-kind 分类重试 + 线性 backoff | langgraph `RetryPolicy` | `tools/gateway.py:149,189-224` |
| SSE：`StreamingResponse` + graph updates 流 + answer 直连 OpenAI token 流 | `stream_mode="messages"` | `web/api.py:218-371`、`runtime_llm.py:78-170` |

整体判断：项目对 LangGraph 的"控制流 + 持久化 + HITL + checkpoint 时间旅行"核心面用得很完整；对"store 长期记忆、动态扇出、节点级 policy、原生 token 流"基本未触及。工具治理侧已选择 Postgres 关系表承接幂等账本和审计，而不是接入 `langgraph.store`。

## 接入建议：剩余未落地能力

### 看场景，有条件才值得

**1. `Send` API（动态扇出）**

plan 执行当前严格顺序（`select_next_step` → `execute_step` 回环，`orchestration_graph.py:222-256`）。delete / solidify 的步骤有依赖、扇不开。唯一契合的是**子查询并行检索**（已承认的性能短板：子查询当前串行）。但该链路目前用 `ThreadPoolExecutor` 而非图节点，要用 Send 得先把子查询检索改造成图节点，改动不小。结论：将来若把检索并行纳入图编排，Send 是对的工具；现在用 ThreadPoolExecutor 解决同一问题成本更低。

**2. `stream_mode="messages"`（统一流式通道）**

answer token 流目前绕过 LangGraph、直连 OpenAI（`runtime_llm.generate_answer_stream`），与 graph 的 updates 流是两条独立通道。messages 模式能统一为单通道，但收益主要是架构整洁性，不是功能缺口。除非未来要在图里对 token 流做统一中间处理，否则优先级不高。

### 不建议接，接了是倒退

这些"没用"是正确的取舍：

- **`RetryPolicy` / `CachePolicy`（节点级）**：自研重试在 ToolGateway 里，绑定 error_kind 分类 + 幂等 + 审计。节点级 RetryPolicy 颗粒更粗、不懂幂等，对写副作用的工具反而危险。
- **`with_structured_output`**：项目统一使用 OpenAI 原生 `responses.parse` 或 strict
  `json_schema`，由基础设施层直接管理 Pydantic 类型、调用追踪和错误语义；不再维护
  `json_object` 兼容降级。
- **`BaseRetriever` / `EnsembleRetriever` / `Embeddings` 抽象**：检索融合是跨 provider 进同一个 ContextPack，融合逻辑（去重、按 source_type 打分、预算裁剪）是核心竞争力，套抽象只会加适配层、降控制力。
- **`PromptTemplate`**：PromptSpec 带 `version` / `output_contract` / `owner` 治理字段，比 PromptTemplate 更强，刚重构完，没理由退回。
- **`AgentExecutor` / LCEL**：架构立场的核心红线，接入等于推翻整个设计。

## 收口

当前剩余建议里，`Send`、`stream_mode="messages"` 属于场景未到；`RetryPolicy`、`with_structured_output`、各类抽象仍会削弱"治理自研"的立场。

核心口径：**评估一个能力要不要接，标准是"它解决哪个已承认的痛点"，而不是"框架提供了所以要用"——很多未使用的能力是主动取舍的结果。**
