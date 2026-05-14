# 记忆层说明

本文汇总当前项目记忆层的职责划分、读写路径、降级策略、已知限制和后续演进方向。对应代码主要位于 [src/personal_agent/memory/](../../src/personal_agent/memory/) 和 [src/personal_agent/storage/](../../src/personal_agent/storage/)。

## 设计目标

当前记忆层不追求“把所有历史都塞进模型上下文”，而是把不同生命周期的信息拆开管理：

- 当前活跃任务需要的短期上下文，放进 `WorkingMemory`
- 会话问答历史，放进 `Postgres.ask_history` 或本地降级文件
- 需要跨请求续接、但还不是正式知识的中间态，放进 `CrossSessionStore`
- 需要用户确认的高风险动作，放进 `PendingActionStore`
- 正式长期知识和复习卡，放进 `LocalMemoryStore`

## 当前状态摘要

`MemoryFacade` 已在 `ask` 链路中参与会话摘要、上下文拼接和问答历史写入。`execute_entry()` 会绑定 session、刷新摘要、写入 task goal 和 plan steps；`PlanExecutor` 也会把执行过程写入 `WorkingMemory.recent_steps`。

跨请求确认状态已从 `WorkingMemory` 中分离，由 `PendingActionStore` 持久化到 `data/pending_actions.json`。最近 citations、固化草稿和候选结论已由 `CrossSessionStore` 持久化到 `data/cross_session.json`，用于删除目标解析和固化续接。

当前仍未引入 LangGraph checkpoint。后续应继续保持 `WorkingMemory` 作为进程内 scratchpad，把更复杂的审批、恢复和续接语义放入明确的持久化模型。

## 组件分层

### 1. `WorkingMemory`

代码位置：[working_memory.py](../../src/personal_agent/memory/working_memory.py)

作用：

- 保存当前任务目标 `task_goal`
- 保存会话摘要 `conversation_summary`
- 保存最近执行/推理步骤 `recent_steps`
- 保存当前计划 `plan_steps`
- 预留工具结果缓存 `_tool_cache`

特点：

- 进程内内存对象
- 只服务当前活跃 session
- 服务重启会丢失
- 不承担跨请求恢复职责

`context_snapshot()` 会把 `task_goal / conversation_summary / plan_steps / recent_steps` 拼成一段上下文，供回答生成、校验和计划感知使用。

### 2. `MemoryFacade`

代码位置：[facade.py](../../src/personal_agent/memory/facade.py)

作用：

- 作为运行时统一的记忆层门面
- 绑定当前 `user_id:session_id`
- 从历史记录刷新 `conversation_summary`
- 记录 ask 链路中的问答历史
- 代理 cross-session 草稿、citations、候选结论读写

当前 runtime 不直接四处分散操作各个 store，而是优先通过 `MemoryFacade` 统一进入。

### 3. `AskHistoryStore`

代码位置：[ask_history_store.py](../../src/personal_agent/storage/ask_history_store.py)

作用：

- 作为问答历史主存储
- 持久化 `question / answer / citations / session_id / graph_enabled / created_at`
- 支持按用户、按会话读取历史
- 支持关键词搜索和删除

当 `Postgres` 可用时，问答历史优先读写这里。

### 4. `LocalMemoryStore`

代码位置：[memory_store.py](../../src/personal_agent/storage/memory_store.py)

作用：

- 保存 `notes.json` 中的长期知识 note（支持 parent note + chunk notes 模型，通过 `parent_note_id / chunk_index / source_span` 建立文档级关联）
- 保存 `reviews.json` 中的复习卡
- 保存 `conversations.json` 中的本地问答历史降级数据
- 提供本地相似检索（含按 parent 去重）、图谱 episode 到 note 的映射、chunk 查询（`get_chunks_for_parent` / `get_parent_note`）和级联删除

这里的 `notes/reviews` 是长期知识层；`conversations.json` 主要用于 ask history 的本地兜底。

### 5. `CrossSessionStore`

代码位置：[cross_session_store.py](../../src/personal_agent/storage/cross_session_store.py)

作用：

- 保存最近 ask 引用过的 `recent_citations`
- 保存 `solidify_conversation` 生成的 `solidify_drafts`
- 保存从会话中提炼出的 `candidate_conclusions`

它承载的是“跨请求保留，但还没进入正式知识库”的中间态信息。

这些数据会落到 `data/cross_session.json`，并带有 TTL 和数量上限，不是长期权威真源。

### 6. `PendingActionStore`

代码位置：[pending_action_store.py](../../src/personal_agent/storage/pending_action_store.py)

作用：

- 保存待确认删除等高风险动作
- 记录 token、状态、过期时间和审计日志
- 支持 `pending / confirmed / rejected / executed / expired`

这部分状态已经从 `WorkingMemory` 中拆出，避免会话切换或进程重启后丢失审批状态。

## 当前读写路径

### ask 链路

1. `MemoryFacade.bind_session()` 绑定 `user_id:session_id`
2. `refresh_conversation_summary()` 读取最近问答历史
3. `WorkingMemory.context_snapshot()` 生成当前上下文
4. runtime 基于上下文生成回答
5. `record_turn()` 持久化本轮问答
6. 如有 citations，同时写入 `CrossSessionStore.recent_citations`

### entry / planner 链路

1. `execute_entry()` 先绑定 session 并刷新摘要
2. planner 生成结构化步骤
3. `WorkingMemory.plan_steps` 保存当前计划
4. `PlanExecutor` 执行中持续写入 `WorkingMemory.recent_steps`

### `delete_knowledge`

- `resolve` 步骤会优先参考图谱 episode 映射
- 若不足，再回退到本地相似检索、关键词匹配和 `recent_citations`
- 真正删除前会创建 `PendingActionStore` 中的待确认动作

### `solidify_conversation`

1. `compose` 步骤生成草稿答案
2. 草稿先写入 `CrossSessionStore.solidify_drafts`
3. `draft_ready` 事件可供前端展示
4. 后续 `capture_text` 工具把草稿正式写入 `KnowledgeNote`

注意：

- `CrossSessionStore` 本身不是最终固化点
- 它更像固化前后的中间持久层
- 当前“草稿入库成功后回写为已固化状态”的闭环能力已预留接口，但还未完全接完

## 会话摘要

当前“会话摘要”并不是单独调用 LLM 做抽象总结，而是把最近最多 6 轮问答历史按下面的格式拼成字符串：

```text
Q: ...
A: ...

Q: ...
A: ...
```

这段内容会写入 `WorkingMemory.conversation_summary`，再通过 `context_snapshot()` 传给后续回答生成逻辑。

设计取舍：

- 原始问答记录会持久化保存
- 给模型使用的是压缩后的最近上下文
- 目标是控制 token 成本并保留多轮承接能力

## 问答历史降级策略

当前问答历史采用 `Postgres` 主存储 + 本地文件降级缓冲：

- 正常情况下优先读写 `Postgres.ask_history`
- 若 `Postgres` 未配置或连接失败，则回退到 `data/conversations.json`

这套设计的优点是：

- 本地开发零依赖
- 主库故障时 ask 链路仍可继续
- 实现简单，便于排障

当前局限也很明确：

- `Postgres` 与本地 JSON 之间没有自动回补
- 历史数据可能分散在两个来源
- 本地 JSON 更偏单机兜底，不适合作为长期权威真源

后续如果走多实例或更强一致性部署，更合理的方向是：

- 用 `SQLite` 或本地队列替代 JSON 兜底
- 为主库恢复后的回补提供明确机制

## 已知限制

### 1. `WorkingMemory` 只支持单个当前活跃 session

当前 `MemoryFacade.bind_session()` 在切换到不同 `user_id:session_id` 时会直接 `reset()` 当前 `WorkingMemory`。这意味着：

- 切换对话窗口时，旧会话的 `task_goal / plan_steps / recent_steps / tool_cache` 会丢失
- 重新进入旧会话时，只能依赖已持久化的问答历史重建 `conversation_summary`
- 当前实现更适合单活跃会话或短事务式 ask/capture 请求

如果未来需要“切回旧窗口后继续保留执行态上下文”，更合理的方向是：

- 改为 `session_key -> WorkingMemory` 的会话级缓存
- 配合 TTL / LRU 控制内存占用

### 2. `_tool_cache` 目前是预留能力

`WorkingMemory` 中的 `_tool_cache` 已有 `cache_tool_result()` / `get_cached_result()` 接口和测试，但当前生产代码中还没有实际接入工具结果复用链路。

现状更像：

- 能力接口已建好
- 但还没有真正被 ask / planner / executor 使用

### 3. `CrossSessionStore` 是中间态，不是正式知识库

`recent_citations / solidify_drafts / candidate_conclusions` 都带 TTL 和数量上限。它的目标是支撑删除解析、草稿续接和候选结论沉淀，而不是替代长期 note 存储。

## 当前数据落点

- `data/notes.json`：长期知识 note
- `data/reviews.json`：复习卡
- `data/conversations.json`：本地问答历史降级文件
- `data/cross_session.json`：跨请求中间态
- `data/pending_actions.json`：待确认操作
- `Postgres.ask_history`：服务端问答历史主存储

## 演进方向

- 继续保持 `WorkingMemory` 作为轻量 scratchpad
- 需要跨请求恢复的审批/续接语义，继续显式放入持久化模型
- 为 ask history 降级层增加更可靠的缓冲与回补机制
- 为 `solidify_conversation` 补齐草稿状态闭环
- 当多段审批或更复杂恢复流增多后，再评估是否引入 LangGraph checkpoint
