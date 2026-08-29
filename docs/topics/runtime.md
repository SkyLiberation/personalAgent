# 当前 Runtime

**Runtime 负责装配和执行机械事实，不拥有用户目标、领域状态或最终完成语义。** 当前普通交互是一个基于 typed Observation 的 Conversation loop；固定事务由各自 Application/Domain 拥有。

## 依赖与 owner

```text
HTTP / CLI / Message Adapter
  -> AgentService
  -> AgentRuntime (composition root)
       -> ConversationService
       -> KnowledgeService / KnowledgeLifecycleService
       -> ResearchService
       -> ToolExecutor / AgentGateway / Model ports
       -> persistence adapters
```

`AgentRuntime` 只集中创建依赖和 Adapter，不成为第二事实源。Application 只依赖 Port；PostgreSQL、Provider SDK、MCP、A2A 与 Artifact Store 位于外层实现。

## Conversation loop

```text
messages + authenticated principal
  -> scoped context/capability materialization
  -> Model: FinalMessage | ContinueTurnProposal(actions)
  -> deterministic Admission / budget / concurrency checks
  -> governed Tool/Agent/Application action execution
  -> ActionObservation | DecisionFeedback
  -> next model turn or FinalMessage
```

模型决定开放语义和下一步 Proposal；代码决定 schema、scope、policy、唯一推导、预算与不变量；执行系统产生 execution fact；Verifier 和 Completion Gate 分别判断语义满足与 required result contract。

Conversation 把本轮 `EffectiveCapabilities` 物化为逐动作 `ModelActionDefinition`，服务提供方通过原生工具调用返回动作名和 typed 参数。没有当前 working plan 时，Tool/Agent 动作 Schema 不暴露 `plan_step_id`；模型若创建新 Plan，必须先单独提交 `working_plan`，Admission 接受后下一模型回合才会暴露待完成步骤并要求动作绑定。`Adapter` 只把调用解码为现有 Proposal；Admission、权限、预算和执行网关仍在模型之外决定是否执行。语义 verifier 注册为 `workflow_activity`：它不进入模型可见能力，也不能通过普通交互入口调用；只有 Runtime 在冻结审查标准后通过独立 workflow 校验与执行入口生成 Verification Receipt。成功的个人知识 `Observation` 提交后，下一回合不再暴露已经完成的 `search_personal_knowledge`，但其他可见能力和 `FinalMessage` 保持可用。

## Context materialization

每次模型调用按以下顺序构造输入：

1. visibility/scope 过滤；
2. 模型已经选择的 personal evidence；
3. capability/tool schema 投影；
4. committed Observation/Feedback；
5. budget materialization。

Personal Knowledge 只有在模型选择 `search_personal_knowledge` 后，才通过有界 `tool_result` 进入。该投影不复制 canonical facts，也不成为写入口。

## Durable execution

- Conversation journal 保存 committed messages、typed inputs、usage、execution order、final message 及工作清单；
- Knowledge save/delete 分别由自己的 Command/operation/Receipt owner 恢复；
- 周期研究、投递和 Agent 运行按各自 Store 与 provider task identity 恢复；
- replay 复用冻结 Command 和已提交副作用，不重新调用模型生成它们。当前不提供响应结束后继续运行的动态调查能力。

## Model retry

模型 Port 只有一个 typed-operation retry owner。它只重试 transport/5xx、malformed transport envelope 和 Provider 空 structured content；一般 schema/语义错误不作为 transient 重试，而由 typed repair、DecisionFeedback 或 fail closed 处理。retry 次数与错误进入模型 trace/usage。Provider 接受请求但没有返回 action、返回未知 action、无效 call ID、非法参数 JSON、非对象参数或不符合 Application action payload 时，边界保留稳定 `reason_code` 和失败阶段；这些事实不改变重试资格，也不触发猜测或自动修补。

## Grounded answer

产品没有平行 Ask runtime。Conversation 是唯一 FinalMessage owner：模型按当前目标选择 `search_personal_knowledge`，外部事实由受治理只读工具返回，模型在同一循环内综合。回答本身不写长期知识；显式保存必须另走确认写路径。

## 可观测与评测

- `InteractionTrace` 记录 typed inputs、usage、context composition、执行顺序和 final message；
- `conversation.model_failure` 记录脱敏的 component、stage、operation、reason code、Provider host/status 和 retryable；不记录 Prompt、Provider 原文或 action 参数；
- E2E archive 记录 `MeasurementProfile` 与 `CaseMeasurement`；
- `metrics_report` 生成同 profile 的完成率、token、调用、延迟与恢复指标；
- `release_gate` 独立判断 archive 能否用于目标 revision 发布。

## 不变量

- Runtime 不从关键词猜 intent、payload 或业务 plan；
- Proposal、Observation、Receipt、Verification 与 Completion 互不冒充；
- Tool schema 不是权限，Gateway 才产生受治理执行事实；
- 一个业务事实只有一个 owner 和写入口；
- 没有失败 baseline 与生产消费者时，不增加 Planner、Workflow、checkpoint、Registry 或兼容层。
