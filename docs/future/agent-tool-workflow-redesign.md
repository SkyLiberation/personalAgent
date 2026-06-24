# Agent Tool / Workflow 改造说明

本次改造的目标不是简单增加工具数量，而是让 Agent 在业务边界内拥有真实的工具决策空间，同时继续接受 workflow、policy、ToolGateway 的治理。

## 核心原则

1. 公共工具面补“业务动作”和“状态观察”，不补算法碎片。
2. 全局 Agent 看到高阶业务能力；具体 workflow 内部通过 scoped allowed tools 做局部决策。
3. 所有真实工具调用继续经过 ToolGateway，保留审计、policy、超时、重试、限流和幂等。
4. ReAct 不再一刀切禁止所有长期写入；在局部 allowed tools 内，非 high-risk、非 confirmation-required 的 medium 写入可以执行。删除、外发、不可逆动作仍被禁止。

## 新增业务工具面

### Knowledge lifecycle

- `list_recent_notes`
- `get_note`
- `find_similar_notes`
- `update_note`
- `supersede_note`
- `mark_note_deprecated`
- `mark_notes_conflicted`

这些工具让 Agent 能维护知识生命周期，而不是只能写入和删除。

### Research management

- `list_research_subscriptions`
- `update_research_subscription`
- `pause_research_subscription`
- `resume_research_subscription`
- `run_research_subscription_now`
- `list_research_runs`
- `get_research_digest`
- `submit_research_feedback`
- `save_research_event`

这些工具覆盖订阅管理、运行诊断、反馈学习和事件入库。

### Operations / workflow diagnostics

- `inspect_worker_queue`
- `retry_worker_task`
- `inspect_workflow_run`

这些工具让 Agent 能解释“为什么没跑”“哪一步失败”“能否重试”。

## 新增 workflow intent

### `manage_research`

用于查看、暂停、恢复、修改、立即运行 Research 订阅，或查看简报、反馈、入库。内部使用 scoped ReAct allowed tools：

- Research 订阅管理工具
- Research run / digest 查询工具
- Research feedback / save 工具

### `maintain_knowledge`

用于查看、修正、替换、标记过期或标记冲突的已有知识。内部使用 scoped ReAct allowed tools：

- 最近笔记 / 单笔记 / 相似笔记查询
- 更新、替换、过期、冲突标记工具

### `inspect_operations`

用于诊断 worker 队列、失败任务和可重试任务。内部使用：

- `inspect_worker_queue`
- `retry_worker_task`

### `inspect_workflow`

用于查看或解释某个 workflow run 的步骤、状态、历史和失败原因。内部使用：

- `inspect_workflow_run`

## 为什么不是把所有内部步骤都工具化

内部算法步骤，例如 URL 归一化、相似度计算、source priority，不应进入公共工具面。它们只是领域函数。

公共工具应该满足至少一个条件：

- Agent 需要在多个业务场景中主动选择它；
- 它代表一个用户可理解的业务动作；
- 它提供决策所需的系统状态；
- 它有明确的治理边界和审计价值。

## Research workflow 化状态

Research 主运行链路已从 `research_once` 大工具拆为 workflow-native pipeline：

- `research_prepare_run`
- `research_plan_queries`
- `research_collect_sources`
- `research_cluster_events`
- `research_rank_events`
- `research_compose_digest`

手动入口使用 `research_once` workflow 创建新的 `ResearchRun` 并逐步执行；外部 cron 入队后的 scheduled run 使用内部 `execute_research_run` workflow 复用已有 `run_id`，避免重复创建 run。

后续仍可继续增强：

- 增加 strategy decision node，动态决定查询预算、来源策略和是否继续搜索。
- 将 evidence evaluation 从启发式进一步升级为 LLM/规则混合判断。
- 将 delivery/save 纳入可配置的 workflow 分支和 HITL 策略。
