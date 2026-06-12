# 工具层

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

如果允许 ReAct 自主删除，模型可能在没有充分确认目标的情况下执行不可逆动作，所以 Gateway 和 StepProjectionValidator 都会阻止高风险或需确认工具进入 ReAct 自主路径。

### 5. 那 ReAct 还有什么使用场景？

有。当前项目不是不用 ReAct，而是把它限制在**单个计划步骤内部的低风险探索**。

典型场景是检索类步骤：planner 可以生成 `execution_mode="react"` 的 `retrieve` 步骤，让模型在有限轮次内根据观察结果决定是否继续调用 `graph_search` 或 `web_search`。比如删除知识前，系统需要先找候选笔记；这一步可以用 ReAct 探索图谱或网络线索，但最终删除目标仍必须经过 `resolve` 映射到真实 `note_id`，再进入 `delete_note` 的确认流程。

当前 ReAct 的边界是：

- 只在 planning 的单步内部使用，不替代整体计划执行器。
- 步骤的 `allowed_tools` 默认为空（read-only），低风险只读工具如 `graph_search / web_search` 是在具体 `WorkflowStepSpec` 上显式声明的，例如 ask 检索步骤显式放行 `graph_search / web_search`，delete 的 retrieve 步骤只放行 `graph_search`，没有全局自动白名单。
- 受 `allowed_tools` 和 `max_iterations` 限制（硬上限 5 轮）。
- 高风险、写入、删除、需要确认的工具不能进入 ReAct（StepProjectionValidator 强制 `risk_level=high` 和 `requires_confirmation=true` 的工具不允许出现在 react 步骤）。
- 每轮 thought/action/observation 会进入事件流和 checkpoint 状态。

所以 ReAct 的价值是“受控探索”，不是“自主执行所有动作”。它适合证据不明确、需要迭代检索的场景；不适合删除、写入、外发这类副作用动作。

### 6. ToolArtifact 为什么统一成 `ok / data / error / error_kind / evidence`？

统一 artifact 可以让编排层不理解每个工具的私有返回结构。成功、失败、证据和待确认状态都走同一种机器可读结构。失败时除了 `error` 自然语言文本，还带 `error_kind`（transient / invalid_param / permission / unrecoverable）机器可读分类，Gateway 据此决定是否重试（见后面 retry 那题）。

这对计划进度、错误恢复、HITL、审计和 evidence 组装都很重要。尤其是工具返回失败时，系统应该看 `ok=false` 和结构化 error / error_kind，而不是猜 content 里的自然语言。

### 7. 工具结果为什么不直接写入用户 messages？

工具结果属于内部执行通道，不一定适合用户直接看，也不应该污染对话历史。项目用 `tool_messages` 保存内部工具交换，并通过 `ToolTrackingSubState` 记录 pending step id、tool call id、工具名、输入和 ReAct iteration。

这样 checkpoint 恢复后能做归属校验，避免把旧工具结果消费到新的步骤里。

### 8. 当前工具层最大不足是什么？

主要有三个：PolicyEngine 已落地基础规则和可配置 allow/deny 覆盖，但还缺 workspace/tenant/RBAC/ABAC 等更完整权限模型；工具审计和幂等账本虽然已经落到 Postgres，但还缺审计查询、脱敏、告警和确认人/确认时间等产品化能力；删除恢复还没有通用的软删除、删除前快照或补偿模型。

这意味着当前已经有统一策略引擎、轻量 Tool Runtime、治理契约、Postgres 审计表和持久幂等账本，但还不能说完整生产级多租户权限、审计产品和高风险回滚体系都落地了。

---

[← 返回索引 INDEX.md](INDEX.md)
