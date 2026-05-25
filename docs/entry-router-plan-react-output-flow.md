# Entry 到输出的整体流程

本文梳理当前请求从 `entry` 进入系统后，经过 router、plan、ReAct、执行分支，最后输出到 API/SSE/前端的完整链路，并重点说明中间涉及的 model。

## 当前框架摘要

当前后端以 `AgentRuntime` 为核心，`AgentService` 只保留兼容性的 facade 职责。入口请求进入 runtime 后，会经过意图路由、可选任务规划、LangGraph 节点编排、工具调用、记忆读写、答案生成、verifier 校验与必要的自修正，最后返回给 Web、CLI 或飞书入口。

需要特别说明的是：`execute_entry()` 当前会进入 LangGraph entry 总编排。`route_intent` 先通过 `DefaultIntentRouter` 生成 `RouterDecision`；当 router 判定输入仍缺少必要信息时，`requires_clarification=True` 会将流程导向 `prepare_clarify_entry -> interrupt_clarify_entry`，补充完成后重新路由。只有 `requires_planning=True` 的任务（当前主要是 `delete_knowledge`、`solidify_conversation`）才会调用 `DefaultTaskPlanner` 生成结构化步骤，并经过 `PlanValidator` 校验后进入计划步骤执行；`capture / ask / summarize / direct_answer` 作为普通分支直接在 orchestration graph 内执行。

计划与执行路径现在通过以下方式可观测：

- `context_snapshot()` 会将 `plan_steps` 拼入 LLM prompt，让生成与校验阶段感知当前计划。
- `EntryResult.plan_steps` 随 API 响应和 SSE `plan_created` 事件返回。
- 前端在回答卡片中以可折叠面板形式展示“Agent 计划执行 N 步”，包括步骤类型、工具名和当前状态。
- 非计划驱动路径通过 `execution_trace` 返回，并由前端展示为“Agent 执行路径”。

`plan_steps` 与 `execution_trace` 已完成语义拆分：`requires_planning=True` 的意图（`delete_knowledge`、`solidify_conversation`）生成真实执行计划，步骤状态实时更新；其他意图改用轻量 `execution_trace` 记录执行路径，前端以不同面板展示，避免将不会被执行的步骤标记为计划。同一 `thread_id` 内的用户与助手消息通过 LangGraph `messages` reducer 跨 run 保留，路由与回答生成可读取历史对话；`answer`、路由决策和执行事件仍属于单轮状态。

典型 entry 执行链路：

```text
Entry
  -> LangGraph orchestration graph
  -> route_intent
  -> requires_clarification? -> checkpoint / interrupt -> supplemented input -> route_intent
  -> requires_planning?
     -> Planner / PlanValidator -> plan_steps -> step loop / ReAct / HITL
     -> capture / ask / summarize / direct_answer branch -> execution_trace
  -> EntryResult.plan_steps / execution_trace -> API / SSE / Frontend panels
  -> Tool Execution
  -> Memory Update
  -> Verifier / Retry
  -> Final Response
```

## 1. 总览

当前 Agent 的统一运行入口是 `AgentRuntime`，代码在 `src/personal_agent/agent/runtime.py`。`AgentRuntime` 初始化时组装了核心组件：

- `DefaultIntentRouter`：入口意图路由器。
- `DefaultTaskPlanner`：任务规划器。
- `PlanValidator`：计划校验器。
- `orchestration_graph`：entry 总编排图，负责 route、普通分支、plan、step、ReAct、HITL 和 finalize。
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
  -> AgentRuntime.execute_entry()
  -> build_entry_orchestration_graph()
     -> normalize_entry
     -> route_intent / DefaultIntentRouter.classify()
     -> requires_clarification? -> prepare_clarify_entry -> interrupt_clarify_entry -> route_intent
     -> capture / ask / summarize / direct_answer branch
        或 plan_task -> validate_plan -> step loop / ReAct / HITL
     -> finalize_entry_result
  -> API response 或 SSE events
```

需要注意：只有 `RouterDecision.requires_planning=True` 的意图进入计划步骤执行。当前主要是：

- `delete_knowledge`
- `solidify_conversation`

其他意图走 orchestration graph 内置普通分支：

- `capture_text`
- `capture_link`
- `capture_file`
- `ask`
- `summarize_thread`
- `direct_answer`

`unknown` 不再对应独立执行分支。当 router 同时标记 `requires_clarification=True` 时会进入可恢复的澄清流程；计划校验失败等未要求中断的兜底状态仍可进入 `direct_answer_branch` 生成提示。

## 2. Entry 入口层

主要入口在 `src/personal_agent/web/api.py`：

- `POST /api/entry`：同步入口，构造 `EntryInput` 后调用 `service.entry(entry_input)`。
- `GET /api/entry/stream`：SSE 入口，统一进入完整 LangGraph entry pipeline，并根据图内实际路由事件输出 `intent`。
- `POST /api/entry/upload`：文件入口，保存上传文件，构造 `source_type="file"` 的 `EntryInput`，再进入 `service.entry()`。

`AgentService` 作为 facade，最终会调用 `AgentRuntime.entry()`，再进入 `AgentRuntime.execute_entry()`，由 LangGraph orchestration graph 接管后续流程。

在 `execute_entry()` 内部，第一步是构造 `AgentGraphState` 并调用：

```text
graph.invoke(initial_state, {"configurable": {"thread_id": thread_id}})
```

所有 entry 请求都会先进入 `normalize_entry` 和 `route_intent`。Router 使用 LLM 优先、规则兜底的方式判断意图与信息是否充分：当输出 `requires_clarification=True` 时，图先在 `prepare_clarify_entry` 保存待补充 payload，再由 `interrupt_clarify_entry` 暂停，让用户选择补充“记录内容 / 提出问题 / 总结内容 / 执行操作”。补充文本写回 `entry_text` 后重新进入 `route_intent`。

`normalize_entry` 和 `route_intent` 负责：

1. 规范化 `user_id` 和 `session_id`。
2. `self.memory.bind_session()` 绑定会话。
3. `self.memory.refresh_conversation_summary()` 刷新会话摘要。
4. 调用 `self._intent_router.classify(entry_input)` 做意图识别。
5. 将目标写入 working memory。
6. 根据 `decision.requires_planning` 和 `decision.route` 决定进入计划路径或普通分支。

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
- `requires_clarification`：是否需要先中断并让用户补充内容。
- `missing_information`
- `clarification_prompt`
- `candidate_tools`
- `user_visible_message`

### 3.3 路由策略

路由策略是 LLM-first + heuristic fallback：

1. 如果 `entry_input.source_type == "file"`，直接路由到 `capture_file`。
2. 如果文本非空且 LLM 配置可用，调用小模型同时判断 intent 与是否需要澄清。
3. 如果 LLM 不可用或调用失败，则回退到 `heuristic_entry_intent()`；兜底层仅对“帮我”“删除”等明确不完整片段要求澄清，不再按文本长度拦截正常短问句。

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

`plan_task` 只有在 `decision.requires_planning=True` 时才调用：

```text
steps = self._planner.plan(decision.route, entry_input.text)
validation = self._plan_validator.validate(steps, decision)
```

当前普通 `ask`、`capture`、`direct_answer` 虽然 planner 中有启发式计划模板，但在 entry 主流程里不会进入计划步骤执行，而是走 orchestration graph 内置普通分支，并只返回轻量 `execution_trace`。

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

`solidify_conversation` 的固化计划模板是：

```text
sol-1 retrieve  检索可供固化判断参考的知识上下文
sol-2 compose   由 LLM 从候选对话中语义选择依据并整理成入库文本
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

## 7. LangGraph 普通分支

非计划驱动路径已经并入 `src/personal_agent/agent/orchestration_graph.py` 和 `src/personal_agent/agent/orchestration_nodes.py`，不再维护单独的 entry 子图。

当前普通分支结构是：

```text
START
  -> normalize_entry
  -> route_intent
  -> conditional_edges by RouterDecision
     requires_clarification                  -> prepare_clarify_entry -> interrupt_clarify_entry -> route_intent / finalize_entry_result
     capture_text / capture_link / capture_file -> capture_branch
     ask                                    -> ask_branch
     summarize_thread                       -> summarize_branch
     direct_answer                          -> direct_answer_branch
     unknown                                -> direct_answer_branch
     delete_knowledge / solidify_conversation -> plan_task
  -> finalize_entry_result
  -> END
```

澄清节点处理“router 已判断仍缺少执行所需信息”的场景，其中 `prepare_clarify_entry` 使 payload 可被 checkpoint 观测，`interrupt_clarify_entry` 完成暂停和恢复。`unknown` 不再是独立 branch；未进入中断的兜底结果由 `direct_answer_branch` 生成提示。

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
- `/api/entry/stream` 中由 LangGraph 完成路由与分支执行后的 SSE 输出

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
model       = settings.graphiti_llm_model       or settings.openai_model
small_model = settings.graphiti_llm_small_model or settings.openai_small_model
base_url    = settings.graphiti_llm_base_url    or settings.openai_base_url
api_key     = settings.graphiti_llm_api_key     or settings.openai_api_key
```

自定义的 `GraphitiOpenAIClient` 会使用：

- OpenAI-compatible Chat Completions
- 带 Graphiti `response_model` 的请求发送 `response_format={"type": "json_schema", ...}`
- 不带响应模型的请求发送 `response_format={"type": "json_object"}`
- Kimi 请求参数 `thinking.type=disabled`
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

`GET /api/entry/stream` 的所有意图统一进入 `service.entry()` 承载的 LangGraph orchestration graph，`intent` 事件来自图内实际路由结果。

#### ask intent

`ask` 会进入 graph 的 `ask_branch`，调用 `execute_ask()` 后将 answer、citations、events 与 checkpoint 一并保存在共享 thread 中。Web 层随后将完整答案分块输出：

```text
intent
status
metadata
answer_delta*
done
execution_trace
```

该路径优先保证 entry 的统一编排、事件与 checkpoint 一致性。需要原生模型 token 流时，独立的 `/api/ask/stream` 仍提供 `execute_ask_stream()` 路径。

#### 非 ask intent

非 ask 同样调用完整 `service.entry(entry_input, on_progress=...)`。

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
| ReAct 单步循环 | `agent/orchestration_nodes.py` | `openai_small_model` | `gpt-4.1-nano` | 在受控工具集合内做 Thought/Action/Observation |
| Replanner 失败重规划 | `agent/replanner.py` | `openai_small_model` | `gpt-4.1-nano` | 步骤失败且重试耗尽后生成替代步骤 |
| Direct Answer | `agent/orchestration_nodes.py` | `openai_small_model` | `gpt-4.1-nano` | 简单问题、问候、无法识别时的澄清等无需检索的短回复 |
| 最终问答合成 | `agent/runtime_llm.py`, `agent/runtime_ask.py` | `openai_model` | `gpt-4.1-mini` | 基于图谱/本地/网络证据生成自然语言回答 |
| 流式回答 | `agent/runtime_llm.py` | `openai_model` | `gpt-4.1-mini` | SSE token streaming |
| 群聊总结 | `agent/runtime_entry.py` | `openai_model` | `gpt-4.1-mini` | 对 thread messages 生成总结 |
| 回答修正重试 | `agent/runtime_ask.py` | `openai_model` | `gpt-4.1-mini` | verifier 不通过时重新生成回答 |
| Graphiti 实体/关系抽取 | `graphiti/llm_strategies.py` | `graphiti_llm_model` + `graphiti_llm_small_model`，回退 `openai_*` | 与 `openai_*` 一致 | Graphiti 内部 LLM client，生成结构化实体和关系 |
| Graphiti embedding | `graphiti/store.py`, `graphiti/dashscope_compatible_embedder.py` | `openai_embedding_model` | `text-embedding-3-small` | 图谱检索和 episode embedding |

## 12. 一条典型请求如何流动

### 12.1 普通知识问答

```text
POST /api/entry
  -> EntryInput(text="xxx 是什么？")
  -> AgentRuntime.execute_entry()
  -> orchestration graph
     -> route_intent: ask
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
  -> orchestration graph
     -> route_intent: delete_knowledge
     -> plan_task: 生成 del-1..del-5
     -> validate_plan
  -> step loop
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
  -> route_intent: solidify_conversation
  -> plan_task: sol-1..sol-4
  -> step loop
     -> retrieve 可供固化判断参考的知识上下文
     -> compose 将带轮次标识的候选对话交给 LLM 选择并生成草稿
        -> save_draft()
        -> emit draft_ready
        -> 模型未给出合格正文时终止写入
     -> verify
     -> tool_call capture_text
        -> 复用 capture 链路写入 KnowledgeNote
        -> 标记 draft/conclusion 已固化
  -> EntryResult(plan_steps=[...])
```

## 13. 当前设计上的几个关键点

1. Router 是所有 entry 的共同入口，但 Planner 不是所有 entry 都会用。
2. `requires_planning` 是决定进入计划步骤执行还是普通分支的关键开关。
3. ReAct 只存在于某个 plan step 内，不是全局主循环。
4. 小模型负责“控制流决策”：路由、规划、ReAct、重规划、直接短答。
5. 主模型负责“内容生成”：最终回答、总结、修正。
6. Graphiti 同时依赖主模型和 embedding model：主模型用于实体/关系抽取，embedding model 用于语义检索。
7. 输出层区分 `plan_steps` 和 `execution_trace`，避免把普通分支误展示成真实计划执行。
