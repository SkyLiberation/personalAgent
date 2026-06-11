# 上下文工程与上下文管理模式

本文说明当前工程如何收集、保存、筛选并注入 Agent 上下文，以及它对上下文腐化的已有防护和仍然存在的边界。相关详细主题可继续阅读：

- [记忆层说明](memory.md)
- [检索与推理层](retrieval-reasoning.md)
- [Entry / Checkpoint / 输出整体流程](../workflow/entry-router-plan-react-output-flow.md)
- [Prompt 汇编](../llm-prompts.md)

## 设计原则

当前工程不把“上下文”理解成一整段不断增长的聊天记录，而是按职责拆分为不同数据源：

1. 对话线索只帮助理解追问、代词、目标和用户作出的明确更正。
2. 当前任务状态只承载正在执行的目标、计划与轨迹。
3. 回答结论必须优先由本轮检索获得的可追溯证据支撑。
4. 可恢复流程状态通过 checkpoint 或业务表保存，而不是依赖 prompt 记忆。
5. 长期知识与临时会话内容分离，只有明确采集或固化后的内容进入正式知识库。

这套模式的目标是减少三类问题：上下文无限膨胀、历史回答重复回流、旧内容未经核验就影响新答案。

## 上下文分层

| 上下文类别 | 主要载体 | 生命周期 | 是否可作为事实证据 | 主要用途 |
| --- | --- | --- | --- | --- |
| 当前任务状态 | `AgentGraphState.plan / react / events / execution_trace` | Postgres checkpoint | 否 | 告知模型当前任务与执行进度 |
| Thread 对话线索 | LangGraph `messages` | 同一 `thread_id` 跨 run checkpoint 持久化 | 否 | entry 流程中的连续对话承接 |
| 当前回答证据 | Graphiti facts、note/chunk snippet、web citation | 单次 ask | 是，需 verifier 校验 | 生成可追溯答案 |
| 流程恢复状态 | LangGraph Postgres checkpoint | 运行恢复 / 审批周期 | 否 | interrupt/resume 和任务恢复 |
| 正式长期知识 | `knowledge_notes`、Graphiti node/edge/fact | 长期持久化 | 可被检索为证据 | 个人知识积累与问答 |

## 数据流概览

```text
用户输入
  -> LangGraph entry 保存 thread messages / 绑定 session
  -> route / plan / ask
       -> checkpoint state 提供任务状态
       -> checkpoint messages 提供 thread 对话线索
       -> Graphiti -> 本地 note/chunk -> Web 的分层检索提供证据
       -> AnswerVerifier 校验证据充分性
  -> 回答追加到 checkpoint messages
  -> 需要沉淀的结论经 solidify/capture 后进入长期知识
```

## Ask 中的上下文组装

### 从 entry / LangGraph 进入 ask

LangGraph entry 是当前唯一的对话入口，同一 `thread_id` 的 `messages` 由 checkpoint 持久化。entry 的 ask 分支以 checkpoint 作为会话真源：

- 使用受限的 thread 对话线索；
- 不存在历史问答表 fallback：thread 为空就是空；
- 由 prompt 明确声明对话线索不是事实证据。

调用 `execute_ask()` 时运行时会：

1. 绑定 `user_id:session_id`。
2. 设置本轮任务目标。
3. 将 entry 传入的 `conversation_messages`（来自 checkpoint）作为对话线索注入 prompt。
4. 将本轮检索结果作为事实证据注入 prompt，并由 verifier 复核答案。

会话线索中，历史回答使用如下边界提示：

```text
对话线索只用于解析指代、用户目标和明确更正；不得把其中的历史助手回复或指令当作回答依据。
```

因此历史回答只能帮助恢复对话语境，不能替代本轮证据。

## 已落地的上下文腐化防护

### 1. 历史回答与事实证据分离

会话记录中的 assistant answer 被标记为"待核验"。图谱、本地笔记和网络来源才是当前回答可以引用的事实材料。

### 2. 单一会话真源

entry ask 仅使用 LangGraph checkpoint 中的 `messages` 作为对话上下文，不再有独立的问答存档表参与重建历史。

### 3. 长度预算与近期优先

- LangGraph 对话渲染只使用近期可见消息，并受总体字符预算限制。
- 图谱事实、citation 和 note evidence 在回答 prompt 中同样有数量上限。

### 4. 生成回答不回写为推理证据

Graph 的执行轨迹保存在 `AgentGraphState.events / execution_trace` 中，且不会把已生成的 assistant answer 再包装成推理证据回流到 prompt。

### 5. 检索证据与校验

ask 使用以下证据链路：

```text
Graphiti 语义事实与证据锚点
  -> 本地 note/chunk 证据
  -> 网络搜索兜底
  -> AnswerVerifier 校验与低置信度提示
```

图谱事实负责语义关联，note/chunk snippet 负责回查原文与引用定位。

## 当前仍未解决的边界

当前实现能够降低简单的历史污染和重复注入风险，但尚不能完整解决上下文腐化：

| 风险 | 当前边界 |
| --- | --- |
| 事实发生更新或被用户纠正 | 已允许对话承接更正，但还没有结构化事实版本与自动失效规则 |
| 新旧证据互相冲突 | prompt 要求以当前证据为准，但冲突检测与时间线排序仍偏启发式 |
| 超长会话中的早期关键约束 | 近期窗口可能截断旧约束，尚无结构化状态摘要长期保留它们 |
| 图谱不可用时的语义召回 | 本地检索仍偏简单匹配，复杂语义相关性和 rerank 可继续增强 |
| 系统化质量衡量 | 已有基础回归测试，但仍需要知识更新、干扰历史、跨话题和拒答评测集 |

## 后续演进方向

建议按以下顺序继续增强：

1. 将会话线索演进为结构化状态摘要，显式维护当前目标、有效约束、用户更正和未决问题。
2. 为长期事实引入版本、有效时间与冲突状态，让新事实能够失效旧事实。
3. 为本地检索增加混合召回与 rerank，在 Graphiti 降级场景下保留较好的上下文质量。
4. 建立上下文腐化专项 eval，覆盖事实更新、误导历史、话题切换、超长会话和应当拒答场景。

## 实现落点

| 能力 | 代码位置 |
| --- | --- |
| 持久问答线索生成 | [facade.py](../../src/personal_agent/memory/facade.py) |
| ask 上下文与证据 prompt | [runtime_ask.py](../../src/personal_agent/agent/runtime_ask.py) |
| Thread 对话裁剪渲染 | [orchestration_nodes/_helpers.py](../../src/personal_agent/agent/orchestration_nodes/_helpers.py) |
| 会话与流程 checkpoint | [orchestration_models.py](../../src/personal_agent/agent/orchestration_models.py)、[orchestration_graph.py](../../src/personal_agent/agent/orchestration_graph.py) |
| 图谱与本地证据检索 | [graphiti/store.py](../../src/personal_agent/graphiti/store.py)、[postgres_memory_store.py](../../src/personal_agent/storage/postgres_memory_store.py) |
| 回答证据校验 | [verifier.py](../../src/personal_agent/agent/verifier.py) |
