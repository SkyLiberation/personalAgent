# Entry 到输出的整体流程

本文梳理当前请求从 `entry` 进入系统后，经过 router、plan、ReAct、执行分支，最后输出到 API/SSE/前端的完整链路，并重点说明中间涉及的 model。

## 1. 总览

当前 Agent 的统一运行入口是 `AgentRuntime`，代码在 `src/personal_agent/agent/runtime.py`。`AgentRuntime` 初始化时组装了核心组件：

- `DefaultIntentRouter`：入口意图路由器。
- `DefaultTaskPlanner`：任务规划器。
- `PlanValidator`：计划校验器。
- `PlanExecutor`：计划执行器，在 `execute_entry()` 中按需创建。
- `ReActStepRunner`：受控 ReAct 单步执行器。
- `Replanner`：步骤失败后的重新规划器。
- `AnswerVerifier`：回答证据校验器。
- `ToolRegistry`：工具注册与执行入口。
- `MemoryFacade`：工作记忆、会话摘要、历史上下文。
- `GraphitiStore`：图谱写入、图谱检索和 Graphiti client 构建。

整体入口链路可以概括为：

```text
Web / Feishu / CLI
  -> AgentService.entry()
  -> AgentRuntime.entry()
  -> RuntimeEntryMixin.execute_entry()
  -> plan_for_entry()
     -> bind session / refresh memory
     -> DefaultIntentRouter.classify()
     -> requires_planning?
        -> DefaultTaskPlanner.plan()
        -> PlanValidator.validate()
        -> PlanExecutor.execute()
           -> deterministic step 或 ReActStepRunner
           -> optional Replanner
        -> EntryResult(plan_steps)
        -> LangGraph entry graph
           -> capture / ask / summarize / direct_answer / unknown branch
        -> EntryResult(execution_trace)
  -> API response 或 SSE events
```

需要注意：`execute_entry()` 当前会先调用 `plan_for_entry()` 做一次统一路由和可选规划。只有 `RouterDecision.requires_planning=True` 的意图进入 `PlanExecutor`。当前主要是：

- `delete_knowledge`
- `solidify_conversation`

其他意图仍走固定的 LangGraph entry graph：

- `capture_text`
- `capture_link`
- `capture_file`
- `ask`
- `summarize_thread`
- `direct_answer`
- `unknown`

## 2. Entry 入口层

主要入口在 `src/personal_agent/web/api.py`：

- `POST /api/entry`：同步入口，构造 `EntryInput` 后调用 `service.entry(entry_input)`。
- `GET /api/entry/stream`：SSE 入口，先快速分类并发送 `intent` 事件，再根据 intent 选择流式 ask 或完整 entry pipeline。
- `POST /api/entry/upload`：文件入口，保存上传文件，构造 `source_type="file"` 的 `EntryInput`，再进入 `service.entry()`。

`AgentService` 作为 facade，最终会调用 `AgentRuntime.entry()`，再进入 `RuntimeEntryMixin.execute_entry()`。

在 `execute_entry()` 内部，第一步是：

```text
decision, validated_steps, _plan_dicts = self.plan_for_entry(entry_input)
```

也就是说，所有 entry 请求都会先走 `plan_for_entry()`。这个函数负责：

1. 规范化 `user_id` 和 `session_id`。
2. `self.memory.bind_session()` 绑定会话。
3. `self.memory.refresh_conversation_summary()` 刷新会话摘要。
4. 调用 `self._intent_router.classify(entry_input)` 做意图识别。
5. 将目标写入 working memory。
6. 根据 `decision.requires_planning` 决定是否进入 planner。

## 3. Router 意图路由

路由器在 `src/personal_agent/agent/router.py`，核心类是 `DefaultIntentRouter`。

### 3.1 路由输入

输入是 `EntryInput`，主要字段包括：

- `text`：用户输入文本。
- `user_id`
- `session_id`
- `source_type`：例如 `text` / `file`。
- `source_platform`：例如 `web`。
- `source_ref`
- `metadata`

### 3.2 路由输出

输出是 `RouterDecision`：

- `route`：最终 intent。
- `confidence`：置信度。
- `requires_tools`：是否需要工具。
- `requires_retrieval`：是否需要检索。
- `requires_planning`：是否需要进入结构化计划执行。
- `risk_level`：`low` / `medium` / `high`。
- `requires_confirmation`：是否需要用户确认。
- `missing_information`
- `candidate_tools`
- `user_visible_message`

### 3.3 路由策略

路由策略是 LLM-first + heuristic fallback：

1. 如果 `entry_input.source_type == "file"`，直接路由到 `capture_file`。
2. 如果文本非空且 LLM 配置可用，调用小模型做 JSON 分类。
3. 如果 LLM 不可用、调用失败、或返回未知 intent，则回退到 `heuristic_entry_intent()`。

`_merge_with_defaults()` 会把 LLM 返回的意图与 `_default_router_decision()` 合并。这样即使 LLM 只返回 intent/reason/risk，也能补齐控制字段，例如：

- `ask` 默认 `requires_retrieval=True`，候选工具是 `graph_search`、`web_search`。
- `delete_knowledge` 默认 `requires_tools=True`、`requires_retrieval=True`、`requires_planning=True`、`risk_level=high`、`requires_confirmation=True`。
- `solidify_conversation` 默认 `requires_planning=True`。
- `direct_answer` 默认不检索、不调用工具。

### 3.4 Router 使用的 model

Router 使用 `settings.openai_small_model`，默认值在 `src/personal_agent/core/config.py` 中是：

```text
OPENAI_SMALL_MODEL -> openai_small_model -> gpt-4.1-nano
```

调用方式是 OpenAI-compatible Chat Completions：

- `model=self._settings.openai_small_model`
- `temperature=0`
- `max_tokens=200`
- `response_format={"type": "json_object"}`

如果缺少 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 或 `OPENAI_SMALL_MODEL`，Router 不调用模型，直接使用启发式规则。

## 4. Plan 规划阶段

规划器在 `src/personal_agent/agent/planner.py`，核心类是 `DefaultTaskPlanner`。

`plan_for_entry()` 只有在 `decision.requires_planning=True` 时才调用：

```text
steps = self._planner.plan(decision.route, entry_input.text)
validation = self._plan_validator.validate(steps, decision)
```

当前普通 `ask`、`capture`、`direct_answer` 虽然 planner 中有启发式计划模板，但在 entry 主流程里不会进入真实 `PlanExecutor`，而是走 LangGraph 固定分支，并只返回轻量 `execution_trace`。

### 4.1 Planner 输出

Planner 输出 `list[PlanStep]`。`PlanStep` 的关键字段包括：

- `step_id`
- `action_type`：`retrieve` / `resolve` / `tool_call` / `compose` / `verify`
- `description`
- `tool_name`
- `tool_input`
- `depends_on`
- `expected_output`
- `success_criteria`
- `risk_level`
- `requires_confirmation`
- `on_failure`：`skip` / `retry` / `abort`
- `status`
- `execution_mode`：`deterministic` / `react`
- `allowed_tools`
- `max_iterations`

### 4.2 Planner 策略

Planner 也是 LLM-first + heuristic fallback：

1. `_plan_with_llm()` 调小模型，让模型输出结构化 JSON steps。
2. 如果模型不可用、调用失败、JSON 不合法或没有有效 step，则使用 `_plan_heuristic()`。
3. `PlanValidator` 进行工具、风险、确认等校验。
4. 如果校验阻断且有 `corrected_steps`，使用修正后的步骤。
5. 如果没有可用修正，则使用 `fallback_plan()` 生成保守启发式计划。
6. 如果 fallback 仍被阻断，则降级为 `unknown`。

### 4.3 典型计划

`delete_knowledge` 的启发式计划是：

```text
del-1 retrieve  检索待删除候选笔记，execution_mode=react，allowed_tools=["graph_search"]
del-2 resolve   从候选中确定目标 note_id
del-3 verify    高风险安全校验，需要确认
del-4 tool_call 调用 delete_note，需要确认
del-5 compose   生成删除结果摘要
```

`solidify_conversation` 的启发式计划是：

```text
sol-1 retrieve  加载最近对话并抽取候选事实
sol-2 compose   整理成适合入库的知识文本
sol-3 verify    校验知识文本
sol-4 tool_call 调用 capture_text 写入知识库
```

### 4.4 Planner 使用的 model

Planner 使用 `settings.openai_small_model`，默认 `gpt-4.1-nano`。

调用参数：

- `temperature=0`
- `max_tokens=500`
- `response_format={"type": "json_object"}`

Planner prompt 会把可用工具列表一起传给模型。工具列表来自 `ToolRegistry.list_tools()`。

## 5. PlanExecutor 执行阶段

计划执行器在 `src/personal_agent/agent/plan_executor.py`，核心类是 `PlanExecutor`。

`execute_entry()` 中，如果需要计划执行，会创建：

```text
executor = PlanExecutor(
    self,
    self.memory,
    replanner=self._replanner,
    react_runner=self._react_runner,
)
```

然后构造 `AgentState(mode="entry", intent=decision.route, entry_input=...)` 并执行：

```text
result = executor.execute(validated_steps, state, on_progress=on_progress)
```

### 5.1 执行顺序

`PlanExecutor` 会先对 steps 做拓扑排序，确保依赖步骤先执行。每个 step 的状态变化为：

```text
planned -> running -> completed / failed / skipped
```

每一步都会通过 `on_progress` 发事件，例如：

- `plan_step_started`
- `plan_step_completed`
- `plan_step_failed`
- `plan_step_retry`
- `plan_replan_attempt`
- `plan_replanned`
- `plan_execution_complete`

这些事件在 `/api/entry/stream` 中被转成 SSE。

### 5.2 action_type 分发

`_dispatch_step()` 根据 `action_type` 分发：

- `retrieve`：调用 `_execute_retrieve()`，当前直接走 `runtime.graph_store.ask()`。
- `resolve`：调用 `_execute_resolve()`，把模糊删除目标解析成具体 `note_id`。
- `tool_call`：调用 `_execute_tool_call()`，通过 `ToolRegistry.execute()` 执行工具。
- `compose`：调用 `_execute_compose()`，生成自然语言结果。
- `verify`：调用 `_execute_verify()`，使用 `AnswerVerifier` 做校验。

如果 `step.execution_mode == "react"` 且存在 `ReActStepRunner`，则先走 ReAct 分支，而不是 deterministic 分支。

### 5.3 失败与重规划

如果 step 失败：

1. `on_failure == "retry"` 时会最多重试 `MAX_RETRIES=3`。
2. 重试耗尽后，如果配置了 `Replanner`，调用 `Replanner.replan()`。
3. Replanner 返回 revised steps 后，会跳过依赖失败步骤的旧步骤，并把新步骤加入执行列表重新拓扑排序。
4. 如果无法重规划，则按 `skip` 或 `abort` 语义继续或中断。

### 5.4 PlanExecutor 自身使用的 model

`PlanExecutor` 本身不直接持有模型调用逻辑。它会间接触发：

- `ReActStepRunner`：用 `openai_small_model` 做工具选择和观察迭代。
- `Replanner`：用 `openai_small_model` 生成替代计划。
- `_execute_compose()` 中调用 `runtime.execute_ask()`，最终可能用 `openai_model` 生成回答。
- `_execute_retrieve()` 中调用 `graph_store.ask()`，Graphiti client 使用 `openai_model` 和 embedding model。

## 6. ReAct 单步推理

ReAct 执行器在 `src/personal_agent/agent/react_runner.py`，核心类是 `ReActStepRunner`。

它不是全局 agent loop，而是嵌在某一个 `PlanStep` 里的受控 Thought/Action/Observation loop。只有 step 明确设置：

```text
execution_mode="react"
```

才会进入 ReAct。

### 6.1 ReAct 的约束

ReAct 被刻意限制在低风险场景：

- 默认允许工具：`graph_search`、`web_search`。
- 如果 step 配置了 `allowed_tools`，则取配置与已注册工具的交集。
- 高风险工具、需要确认的工具、写长期记忆的工具都会被阻断。
- 工具名前缀 `delete_`、`capture_` 被阻断。
- 最大轮数受 `step.max_iterations` 和全局 `MAX_ITERATIONS_CAP=5` 双重限制。

因此 ReAct 当前主要用于检索类步骤，例如：

- 删除前检索候选笔记。
- ask 计划模板中的图谱/网络检索探索。

### 6.2 ReAct 循环

每一轮：

1. 构造包含步骤描述、已有上下文、可用工具的 prompt。
2. 调用小模型，要求只输出 JSON。
3. 如果 JSON 中有 `done=true`，返回 `result`。
4. 否则读取 `tool` 和 `input`。
5. 校验工具是否允许。
6. 通过 `ToolRegistry.execute(tool_name, **tool_input)` 执行工具。
7. 将 observation 追加回 prompt，进入下一轮。
8. 每轮发送 `react_iteration` 事件。

如果达到最大轮数仍未 `done`，返回所有 observations 和 evidence。

### 6.3 ReAct 使用的 model

ReAct 使用 `settings.openai_small_model`，默认 `gpt-4.1-nano`。

调用参数：

- `temperature=0`
- `max_tokens=400`
- `response_format={"type": "json_object"}`

## 7. LangGraph 固定分支

非计划驱动路径在 `src/personal_agent/agent/graph.py` 和 `src/personal_agent/agent/entry_nodes.py`。

`build_entry_graph()` 构造的图是：

```text
START
  -> route
  -> conditional_edges by state.intent
     capture_text / capture_link / capture_file -> capture_branch
     ask                                    -> ask_branch
     summarize_thread                       -> summarize_branch
     direct_answer                          -> direct_answer_branch
     unknown                                -> unknown_branch
     delete_knowledge / solidify_conversation -> unknown_branch
  -> END
```

虽然 `delete_knowledge` 和 `solidify_conversation` 在图中会映射到 `unknown_branch`，但正常情况下它们已经在 `execute_entry()` 中被 `PlanExecutor` 截获执行，不会走到 LangGraph 的 unknown 分支。

### 7.1 capture 分支

`capture_entry_branch_node()` 会根据 intent 处理：

- `capture_file`：读取上传文件路径，调用 `CaptureService.capture_text_from_upload()` 解析文本，再调用 `execute_capture()`。
- `capture_link`：提取 URL，调用 `CaptureService.capture_text_from_url()` 抓取正文，再调用 `execute_capture()`。
- `capture_text`：直接调用 `execute_capture()`。

`execute_capture()` 继续走 capture graph：

```text
capture -> enrich -> link -> schedule_review
```

然后尝试调用 `graph_store.ingest_note()` 写入 Graphiti。如果成功，会把 episode、entity、relation、node/edge/fact refs 合并回 note；如果失败，会记录 `graph_sync_status="failed"`。

### 7.2 ask 分支

`ask_entry_branch_node()` 调用 `execute_ask()`。

`execute_ask()` 的问答链路是三层：

```text
Graphiti graph ask
  -> 如果证据充分，直接返回
  -> 否则合并本地检索
Local memory ask graph
  -> build_ask_graph(answer_node)
  -> 本地笔记 matches/citations
Web search fallback
  -> 证据不足且 web_search 可用时触发
```

每一层回答生成后都会经过 `AnswerVerifier` 校验；如果校验不足，最多按 `settings.max_verify_retries` 进行修正重试。

### 7.3 direct_answer 分支

`direct_answer_entry_branch_node()` 用于问候、感谢、澄清、简单说明等低风险场景。

如果 LLM 配置可用，会直接调用小模型生成简短回复；否则使用 `_simple_direct_answer()` 规则回复。

### 7.4 summarize 分支

`summarize_entry_branch_node()` 如果 `metadata.thread_messages` 中带有群聊消息，会调用 `RuntimeEntryMixin._summarize_thread()`。

`_summarize_thread()` 内部调用 `_generate_answer()`，因此使用主回答模型 `openai_model`。

## 8. 最终回答生成与校验

最终回答相关逻辑主要在：

- `src/personal_agent/agent/runtime_ask.py`
- `src/personal_agent/agent/runtime_llm.py`
- `src/personal_agent/agent/verifier.py`

### 8.1 主模型回答生成

`RuntimeLlmMixin._generate_answer()` 使用 `settings.openai_model`，默认：

```text
OPENAI_MODEL -> openai_model -> gpt-4.1-mini
```

它用于：

- 图谱问答回答合成：`_compose_graph_answer()`。
- 本地笔记问答回答合成：`_compose_local_answer()`。
- 网络搜索回答合成：`_compose_web_answer()`。
- verifier 不通过后的修正回答：`_retry_if_needed()`。
- 群聊总结：`_summarize_thread()`。

调用参数：

- `temperature=0.3`
- `max_tokens=600`

### 8.2 流式回答

`RuntimeLlmMixin._generate_answer_stream()` 也使用 `settings.openai_model`。

它用于：

- `/api/ask/stream`
- `/api/entry/stream` 中 ask intent 的快速流式路径

SSE 事件包括：

- `answer_delta`
- `answer_complete`
- `answer_error`
- `done`

### 8.3 AnswerVerifier

`AnswerVerifier` 当前不直接调用模型。它基于 answer、citations、matches、evidence 做规则型证据校验，输出：

- `ok`
- `sufficient`
- `evidence_score`
- `issues`
- `warnings`

如果校验不足，`RuntimeAskMixin._retry_if_needed()` 会用主模型重新生成修正版回答。

## 9. Graphiti 与 Embedding 模型

图谱层在 `src/personal_agent/graphiti/store.py`。

`GraphitiStore.configured()` 要求：

- `graphiti_uri`
- `graphiti_user`
- `graphiti_password`
- `openai_api_key`
- `openai_base_url`
- `openai_model`
- embedding API key/base URL
- `openai_embedding_model`

### 9.1 Graphiti LLM client

`GraphitiStore._build_client()` 调用 `build_graphiti_llm_client(settings)`，位于 `src/personal_agent/graphiti/llm_strategies.py`。

Graphiti LLM 配置：

```text
model       = settings.openai_model
small_model = settings.openai_small_model
base_url    = settings.openai_base_url
api_key     = settings.openai_api_key
```

自定义的 `GraphitiOpenAIClient` 会强制使用：

- OpenAI-compatible Chat Completions
- `response_format={"type": "json_object"}`
- `temperature=0.6`
- `max_tokens=self.max_tokens`

它还会做两类兼容处理：

- 将模型输出中的 `entities` / `facts` 等非标准字段规范化成 Graphiti 期望结构。
- 对实体类型、边字段做容错映射。

### 9.2 Embedding model

Graphiti embedder 使用 `DashScopeCompatibleEmbedder`，配置来自：

```text
OPENAI_EMBEDDING_MODEL -> openai_embedding_model -> text-embedding-3-small
EMBEDDING_API_KEY      -> embedding_api_key，缺省回退 OPENAI_API_KEY
EMBEDDING_BASE_URL     -> embedding_base_url，缺省回退 OPENAI_BASE_URL
```

`DashScopeCompatibleEmbedder` 继承 Graphiti 的 `OpenAIEmbedder`，主要调整是 batch 限制，避免一次 embedding batch 太大。

### 9.3 Graphiti 在流程中的位置

Graphiti 被两个主要路径调用：

1. Capture 写入：

```text
execute_capture()
  -> graph_store.ingest_note(note)
  -> Graphiti.add_episode()
  -> Graphiti.search_() 找相关 episode
  -> 更新 note.graph_episode_uuid / entity_names / relation_facts / refs
```

2. Ask 检索：

```text
execute_ask()
  -> graph_store.ask(question, user_id)
  -> Graphiti.search_()
  -> node / edge / fact refs
  -> relation_facts / citation_hits
  -> 回查本地 note
  -> 主模型合成自然语言回答
```

## 10. 输出层

### 10.1 同步 entry 输出

`POST /api/entry` 返回 `EntryResponse`：

- `intent`
- `reason`
- `reply_text`
- `capture_result`
- `ask_result`
- `plan_steps`
- `execution_trace`

计划驱动路径返回真实 `plan_steps`，普通 LangGraph 路径返回轻量 `execution_trace`。

### 10.2 SSE entry 输出

`GET /api/entry/stream` 的行为分两类。

#### ask intent

SSE 入口会先快速分类，然后如果是 `ask`，直接调用 `runtime.execute_ask_stream()`，让回答 token 流式输出：

```text
intent
status
metadata
answer_delta*
answer_complete / answer_error
done
execution_trace
```

这个路径不会等待完整 `execute_entry()`，因此 ask 的用户体验更像实时生成。

#### 非 ask intent

非 ask 会在线程中调用完整 `service.entry(entry_input, on_progress=...)`。

可能输出：

- `intent`
- `plan_created`
- `execution_trace`
- `plan_step_started`
- `react_iteration`
- `plan_step_completed`
- `pending_action_created`
- `draft_ready`
- `plan_execution_complete`
- `capture_result`
- `status`
- `done`

### 10.3 plan_steps 与 execution_trace

当前有一个明确拆分：

- `plan_steps`：真实计划执行步骤，只用于 `requires_planning=True` 的意图。
- `execution_trace`：非计划路径的轻量说明，用于 ask/capture/direct/summarize 等固定分支。

这样前端可以区分“真实执行过的计划”和“用于解释流程的执行轨迹”。

## 11. Model 使用总表

| 阶段 | 代码位置 | model 配置 | 默认值 | 作用 |
| --- | --- | --- | --- | --- |
| Router 意图识别 | `agent/router.py` | `openai_small_model` | `gpt-4.1-nano` | 将 entry 文本分类成 intent，并输出 risk/confirmation/missing info |
| Planner 任务规划 | `agent/planner.py` | `openai_small_model` | `gpt-4.1-nano` | 为计划型任务生成结构化 `PlanStep` |
| ReAct 单步循环 | `agent/react_runner.py` | `openai_small_model` | `gpt-4.1-nano` | 在受控工具集合内做 Thought/Action/Observation |
| Replanner 失败重规划 | `agent/replanner.py` | `openai_small_model` | `gpt-4.1-nano` | 步骤失败且重试耗尽后生成替代步骤 |
| Direct Answer | `agent/entry_nodes.py` | `openai_small_model` | `gpt-4.1-nano` | 简单问题、问候等无需检索的短回复 |
| 最终问答合成 | `agent/runtime_llm.py`, `agent/runtime_ask.py` | `openai_model` | `gpt-4.1-mini` | 基于图谱/本地/网络证据生成自然语言回答 |
| 流式回答 | `agent/runtime_llm.py` | `openai_model` | `gpt-4.1-mini` | SSE token streaming |
| 群聊总结 | `agent/runtime_entry.py` | `openai_model` | `gpt-4.1-mini` | 对 thread messages 生成总结 |
| 回答修正重试 | `agent/runtime_ask.py` | `openai_model` | `gpt-4.1-mini` | verifier 不通过时重新生成回答 |
| Graphiti 实体/关系抽取 | `graphiti/llm_strategies.py` | `openai_model` + `openai_small_model` | `gpt-4.1-mini` / `gpt-4.1-nano` | Graphiti 内部 LLM client，生成结构化实体和关系 |
| Graphiti embedding | `graphiti/store.py`, `graphiti/dashscope_compatible_embedder.py` | `openai_embedding_model` | `text-embedding-3-small` | 图谱检索和 episode embedding |

## 12. 一条典型请求如何流动

### 12.1 普通知识问答

```text
POST /api/entry
  -> EntryInput(text="xxx 是什么？")
  -> AgentRuntime.execute_entry()
  -> plan_for_entry()
     -> Router: ask
     -> requires_planning=False
  -> build_entry_graph()
     -> route
     -> ask_branch
  -> execute_ask()
     -> graph_store.ask()
     -> 回查本地 note/citations
     -> _compose_graph_answer() 使用 openai_model
     -> AnswerVerifier
     -> 不足则 local fallback
     -> 仍不足则 web_search fallback
  -> EntryResult(
       intent="ask",
       reply_text=answer,
       ask_result=...,
       execution_trace=[...]
     )
  -> EntryResponse
```

### 12.2 删除知识

```text
POST /api/entry
  -> EntryInput(text="删除那条关于 xxx 的笔记")
  -> AgentRuntime.execute_entry()
  -> plan_for_entry()
     -> Router: delete_knowledge
     -> requires_planning=True
     -> Planner: 生成 del-1..del-5
     -> PlanValidator
  -> PlanExecutor
     -> del-1 retrieve, execution_mode=react
        -> ReActStepRunner 使用 graph_search
     -> del-2 resolve
        -> graph episode -> local note
        -> local similarity fallback
        -> keyword fallback
        -> recent citations fallback
     -> del-3 verify
     -> del-4 tool_call delete_note
        -> 创建 pending action
        -> 发 pending_action_created
     -> del-5 compose
  -> EntryResult(plan_steps=[...])
  -> API/SSE 输出，等待用户二次确认
```

### 12.3 固化对话

```text
POST /api/entry
  -> EntryInput(text="把刚才结论沉淀成知识")
  -> Router: solidify_conversation
  -> Planner: sol-1..sol-4
  -> PlanExecutor
     -> retrieve 最近对话/候选事实
     -> compose 草稿
        -> save_draft()
        -> emit draft_ready
     -> verify
     -> tool_call capture_text
        -> 复用 capture 链路写入 KnowledgeNote
        -> 标记 draft/conclusion 已固化
  -> EntryResult(plan_steps=[...])
```

## 13. 当前设计上的几个关键点

1. Router 是所有 entry 的共同入口，但 Planner 不是所有 entry 都会用。
2. `requires_planning` 是决定进入 `PlanExecutor` 还是 LangGraph 固定分支的关键开关。
3. ReAct 只存在于某个 plan step 内，不是全局主循环。
4. 小模型负责“控制流决策”：路由、规划、ReAct、重规划、直接短答。
5. 主模型负责“内容生成”：最终回答、总结、修正。
6. Graphiti 同时依赖主模型和 embedding model：主模型用于实体/关系抽取，embedding model 用于语义检索。
7. 输出层区分 `plan_steps` 和 `execution_trace`，避免把普通固定分支误展示成真实计划执行。
