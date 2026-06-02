# Agent 记忆层说明

本文说明当前项目的 Agent 记忆体系：哪些信息属于短期记忆，哪些信息会沉淀为长期记忆，以及这些记忆如何进入 prompt、checkpoint 和业务存储。对应代码主要位于 [src/personal_agent/memory/](../../src/personal_agent/memory/) 和 [src/personal_agent/storage/](../../src/personal_agent/storage/)。

## 设计目标

Agent 的记忆不等于"把所有历史都塞进上下文"。当前实现按生命周期和可信度拆分记忆：

- **短期记忆**：当前 thread 的对话、计划、执行状态和中断恢复现场，服务于本次或同一 thread 内的连续任务
- **长期记忆**：用户显式沉淀或系统固化的知识 note、chunk、复习卡，服务于长期检索和事实依据

这个分层的核心原则是：**执行现场用 checkpoint 恢复，正式知识用长期存储检索。** 不存在独立的"会话存档"层 —— LangGraph entry 是唯一对话入口，对话历史以 checkpoint `messages` 为唯一真源。

## 当前状态摘要

LangGraph entry 使用 Postgres checkpoint 持久化当前执行现场，用于审批中断、恢复和 run snapshot 查询。Graph 主流程直接读取 `AgentGraphState`，不再存在额外的进程内 working memory 层。

通过 `execute_entry()` 进入的多轮对话，以同一 `thread_id` 的 checkpoint `messages` 作为唯一会话真源。Graph 完成节点只把助手回复追加到 checkpoint。

待确认操作不写入业务审批表，而是保留在 LangGraph checkpoint 的 `pending_confirmation` 中。solidify 草稿同样不写入业务中间态表，而是保留在 checkpoint 的 `plan.results` 中，并通过 `draft_ready` 事件向前端展示。

## 记忆分层

### 1. 短期记忆：Thread 执行现场

短期记忆描述 Agent 正在做什么、做到哪一步、是否等待用户确认。它不是普通聊天历史缓存，而是可恢复的运行现场。

主要载体：

- LangGraph `AgentGraphState`
- Postgres checkpoint
- 同一 `thread_id` 下的 `state.messages`
- `plan / react / events / execution_trace / pending_confirmation`

作用：

- 承接同一 thread 内的连续对话
- 保存路由、规划、ReAct、步骤执行和输出状态
- 支持 `interrupt/resume`
- 支持 run snapshot 查询

典型字段位于 [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)，checkpoint 构建位于 [orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py)。

短期记忆的 prompt 使用规则：

- entry 各分支优先读取 checkpoint 中的 thread 对话和执行状态
- `direct_answer` 会把 thread 对话作为 chat messages 使用，不再同时把同一批内容塞进 system context
- 不存在历史问答表 fallback：thread 为空就是空，不会从其他存档补历史

#### 短期记忆的上下文管理

checkpoint `messages` 是同一 thread 内累积的全量真源，但不会原样进 prompt。进 prompt 前会经过窗口、过滤和压缩，这是当前唯一的短期记忆上下文管理层：

- **滑动窗口**：对话历史只取最近 12 条（[_helpers.py](../../src/personal_agent/agent/orchestration_nodes/_helpers.py) 的 `_dialogue_history` 用 `history[-12:]`，[runtime_ask.py](../../src/personal_agent/agent/runtime_ask.py) 用 `messages[-12:]`）。更早的轮次仍保留在 checkpoint，但不进当前 prompt。
- **角色过滤**：只保留 `human/ai`（用户/助手）消息（`message.type in {"human", "ai"}`），system/tool 等中间消息不进对话上下文。
- **排除当前轮**：entry 各分支以 `exclude_latest=True` 取历史（[_entry.py](../../src/personal_agent/agent/orchestration_nodes/_entry.py) 的 `_entry_conversation_messages`），把本轮用户输入从"对话线索"里剔除，避免与当前问题重复。
- **字符截断**：planner 的 query understanding 把拼接后的对话上下文截到 800 字符（[query_planner.py](../../src/personal_agent/agent/query_planner.py) 的 `conversation_context[:800]`），约束规划模型的输入预算。
- **群聊总结路径**：`summarize_thread` 分支最多加载 20 条（`load_thread_messages(..., 20)`），交给 LLM 压成主题要点，而不是逐条塞进 prompt。

进入 prompt 的对话线索还附带引用边界（`_DIALOGUE_CONTEXT_POLICY`）：只用于理解指代、用户目标和明确更正，不作为事实证据；与当前可追溯证据冲突时以证据为准。

**当前限制**：这是固定条数加固定字符上限的静态窗口，没有基于 token 预算的动态裁剪，也没有把超出窗口的旧消息滚动摘要回上下文。超过 12 条的历史在 prompt 层面直接丢弃（数据仍留在 checkpoint，可在后续 thread 恢复时重新进入窗口）。

### 2. 长期记忆：正式知识和复习材料

长期记忆保存用户希望 Agent 长期记住、可反复检索和引用的知识。

主要载体：

- [postgres_memory_store.py](../../src/personal_agent/storage/postgres_memory_store.py)
- `Postgres.knowledge_notes`
- `Postgres.review_cards`

长期知识模型：

- parent note 表达文档级或主题级知识
- chunk note 保存原文片段、证据定位和 citation 单元
- `parent_note_id / chunk_index / source_span` 用于建立文档和片段关系
- 复习卡独立保存，用于后续记忆巩固和回顾

长期记忆的职责：

- 作为事实检索和引用的主要来源之一
- 支持相似检索、关键词检索、按 parent 去重
- 支持 chunk 查询、父 note 查询和级联删除
- 与 Graphiti episode 映射配合，支撑图谱语义检索和原文回溯

`knowledge_notes` 记录"系统正式沉淀并可检索引用的知识"；Graph entry 的对话历史属于 checkpoint 短期记忆，不进入长期记忆，除非通过 solidify 流程显式沉淀。

## 数据库表与保存内容

当前记忆相关数据都保存在 `PERSONAL_AGENT_POSTGRES_URL` 指向的 Postgres 中。不同表保存的不是同一种"记忆"，而是不同生命周期的数据。

| 表 | 记忆类型 | 保存内容 | 主要写入来源 | 生命周期 |
| --- | --- | --- | --- | --- |
| `checkpoints` / `checkpoint_blobs` / `checkpoint_writes` | 短期记忆 / 可恢复执行现场 | LangGraph checkpoint，包括 `AgentGraphState.messages`、`plan`、`react`、`events`、`execution_trace`、`pending_confirmation`、当前 `answer` 等 | `execute_entry()` 的 LangGraph 编排 | 同一 `thread_id` 的对话与运行恢复周期 |
| `knowledge_notes` | 长期记忆 | 正式知识 note 和 chunk。核心字段在 `payload` JSONB 中，表层索引字段包括 `id`、`user_id`、`parent_note_id`、`graph_episode_uuid`、`created_at`、`updated_at` | `capture_text`、`capture_link`、`capture_file`、`solidify_conversation` 后续入库 | 长期保存，除非用户删除 |
| `review_cards` | 长期复习记忆 | 复习卡 `payload`，关联 `note_id`，并保存 `due_at` | capture / digest 相关流程 | 长期保存，随 note 删除级联清理 |

### `checkpoints`：Graph 短期记忆真源

LangGraph 的 Postgres checkpointer 会维护 `checkpoints`、`checkpoint_blobs` 和 `checkpoint_writes`。这些表不是业务 store 手写 schema，而是由 `PostgresSaver.setup()` 创建。

这里保存的是可恢复的 graph state。对 Agent 记忆最关键的是：

- `messages`：同一 `thread_id` 下跨 run 累积的用户/助手对话
- `plan`：计划步骤、当前步骤、步骤结果
- `react`：ReAct 单步推理状态、迭代结果和停止原因
- `events`：前端和 run snapshot 可见的运行事件
- `execution_trace`：非计划分支的轻量执行路径
- `pending_confirmation`：等待用户确认或补充的信息
- `answer / answer_completed`：当前 run 的最终输出状态

同一会话的短期上下文以 checkpoint `messages` 为唯一真源。

### `knowledge_notes`：正式长期知识

`knowledge_notes` 保存用户明确采集或固化后的知识。表结构将可检索索引字段放在外层，将完整 note 放在 `payload` JSONB 中。

外层字段：

- `id`：note 或 chunk id
- `user_id`：所属用户
- `parent_note_id`：chunk 指向 parent note；parent note 为空
- `graph_episode_uuid`：与 Graphiti episode 的映射
- `payload`：完整 `KnowledgeNote`
- `created_at / updated_at`

`payload` 中通常包含标题、摘要、正文、source 信息、chunk 信息、entity/relation、citation 定位、图谱同步状态等。它是当前系统中最接近"长期事实记忆"的业务真源。

### `review_cards`：复习材料

`review_cards` 保存与 note 关联的复习卡：

- `id`
- `note_id`
- `payload`：完整 `ReviewCard`
- `due_at`：下次复习时间

它依附于长期知识，不保存对话上下文。capture 流程生成 note 之后会自动派生一张到期提醒卡，`digest` 接口把到期卡返回前端用于复习提醒。

### `pending_confirmation`：Graph HITL 暂停状态

高风险动作的确认状态保存在 checkpoint 的 `AgentGraphState.pending_confirmation` 中。以删除笔记为例，`delete_note` 第一次被调用时不会删除数据，而是返回确认 payload；Graph 将其写入 `pending_confirmation` 并通过 `interrupt()` 暂停：

```json
{
  "step_id": "del-3",
  "action_type": "delete_note",
  "note_id": "note-123",
  "title": "DNS",
  "summary": "DNS 是域名系统...",
  "description": "将删除笔记「DNS」及其关联的复习卡片和图谱映射。"
}
```

用户确认时，前端通过 Graph resume 传入 `{"decision": "confirm"}`。Graph 从 checkpoint 恢复暂停点，把当前步骤的工具输入补上 `confirmed=true`，再次调用 `delete_note`，这次才真正删除 note、chunk、review card 和可用的图谱 episode。

用户拒绝时，Graph 将当前步骤标记为 `skipped`，递归跳过依赖它的后续步骤，清空 `pending_confirmation`，并返回取消说明。

## 读写路径

### LangGraph entry（唯一对话入口）

1. `execute_entry()` 绑定 session，并用 `thread_id` 从 Postgres checkpoint 恢复当前 state
2. 路由、规划、direct answer、summarize、ReAct 和 compose/solidify 优先使用 checkpoint 中的 thread 对话和执行状态
3. `AgentGraphState.messages / plan / react / events / execution_trace` 写入 checkpoint
4. 所有成功形成用户可见回复的完成分支在 `finalize_entry_result` 统一追加 assistant message 到 checkpoint

### solidify conversation

1. `compose` 生成草稿答案
2. 草稿保存在 checkpoint 的 `plan.results` 中
3. `draft_ready` 事件供前端展示
4. 后续 `capture_text` 从上游 compose 结果接收草稿，并正式写入 `knowledge_notes`

### delete knowledge

1. 解析删除目标时优先参考图谱 episode 映射
2. 不足时回退到本地相似检索和关键词匹配
3. `delete_note` 首次执行时返回 `pending_confirmation`，不删除数据
4. Graph 通过 checkpoint 暂停并等待用户确认
5. resume 确认后再次调用 `delete_note(confirmed=true)` 执行删除；拒绝则跳过后续依赖步骤

## 当前数据落点

| 类型 | 数据载体 | 生命周期 | 是否事实来源 |
| --- | --- | --- | --- |
| 当前执行现场 | Postgres checkpoint / `AgentGraphState` | thread/run 周期 | 否 |
| Thread 对话 | checkpoint 中的 `state.messages` | 同一 thread | 否 |
| 长期知识 | `Postgres.knowledge_notes` | 长期 | 是 |
| 复习材料 | `Postgres.review_cards` | 长期 | 是，取决于来源 |
| 待确认动作 | checkpoint 中的 `pending_confirmation` | thread/run 周期 | 否 |

## 与 prompt 的关系

Agent 构造 prompt 时遵循两个边界：

1. **短期状态优先**：同一 thread 内优先使用 checkpoint 中的 `messages / plan / react / events`
2. **事实证据另算**：事实结论必须依赖长期知识、工具结果或本轮检索，历史助手回复不直接作为事实依据

这可以避免：历史回答过期或错误，却被模型当成事实继续传播。

## 已知限制

### 1. 中间态不是长期知识

solidify 草稿只是当前 Graph 运行中的中间结果。只有写入 `knowledge_notes` 后，才进入正式长期记忆。

### 2. 跨 session 的对话上下文需手动迁移

不同 `session_id` 拥有独立 checkpoint thread。如果需要在新会话里引用旧会话的结论，需要先 solidify 进 `knowledge_notes`，再在新会话里检索。

## 演进方向

- 为事实更新、冲突消解和长会话干扰建立专项评测
- 明确长期知识的双层定位：Graphiti node/edge/fact 是语义推理单元，Postgres parent/chunk note 是原文证据与回溯单元
- 基于 Postgres checkpoint 扩展多段审批和复杂恢复流
