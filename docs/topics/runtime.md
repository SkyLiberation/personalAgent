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
  -> action phase: one or more compatible Provider action calls
  -> deterministic Admission / budget / concurrency checks
  -> governed Tool/Agent/Application action execution
  -> ActionObservation | DecisionFeedback
  -> model-selected prepare_final (within budget)
  -> exclusive typed FinalMessage phase
  -> Semantic Verification -> Completion -> send or continue
```

模型决定开放语义和下一步 Proposal；代码决定 schema、scope、policy、唯一推导、预算与不变量；执行系统产生 execution fact；Verifier 和 Completion Gate 分别判断语义满足与 required result contract。

ConversationService 提交模型决策产生的 `DecisionFeedback` 时绑定 `decision_turn`，同轮多个工具被拒绝只算一次尝试，完整反馈仍全部交给下一轮模型。相同动作种类、原因和计划版本在成功进展之后跨两个不同决策回合被拒绝，才触发既有重复错误停止保护；Journal 恢复保留回合归属。前置非决策反馈不计为模型重试。责任与证据边界见 [ADR 0019](../adr/0019-bind-feedback-to-decision-turn.md)。

终止计划没有可执行活动项，直接提交新工具仍会被拒绝。反馈明确允许模型提出后续计划，沿已有交互模式与唯一活动项准入继续执行；不把历史已完成工作项重新标为未完成，也不把计划终止等同于用户任务完成。

Conversation 把本轮 `EffectiveCapabilities` 物化为逐动作 `ModelActionDefinition`，服务提供方通过原生工具调用返回动作名和 typed 参数。Tool/Agent 动作 Schema 不暴露 `plan_step_id`；存在 Plan 时，模型通过独立 `control_working_plan` 选择唯一 `in_progress` 步骤，执行系统把随后动作事实关联到该 canonical 步骤。`Adapter` 只把调用解码为现有 Proposal；Admission、权限、预算和执行网关仍在模型之外决定是否执行。

当前原生引用候选由 `FinalMessage.segments` 唯一保存正文及引用，`message` 仅为按序拼接的只读属性；旧正文写字段已删除，外部 `ConversationMessage.content` 仍为字符串。代码检查已验证回执与该正文相同后交付。迁移与证据边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。

`FinalMessage` 不再是可以与普通 Tool Call 并列返回的 Provider action。模型在 action phase 通过无 payload 的 `prepare_final` 请求相位切换；兼容动作执行后，下一回合不暴露任何 action definitions，只生成 strict typed `FinalMessage`。Final Prompt 投影冻结审查条件、工作清单语义内容和剩余预算，但不暴露 Plan identity、执行绑定或动作定义。主模板和 request version 统一由 [Prompt Registry](../llm-prompts.md) 拥有。`StructuredModelResponse` 禁止同时携带 typed value 与 action invocations。普通只读工具仍可在一个 action phase 并行调用，这条互斥只约束最终交付。

当前工作树删除了“有验收标准就已有待改正文和充分材料”的指令，也删除了由此强制非 `answer` 继续迭代的分支。
验收条件只约束结果，不决定用户任务或证据是否齐全；任务语义与合法 disposition 由模型判断。
存在冻结标准且模型提交 `answer` 时，仍由运行系统调用语义验证；`clarification_required`、`limitation`、
`failed` 不因标准存在而改成成功答案。合法终态不等于满足原用户结果；真实 E2E 已运行，但尚未到达模型 Final，见
[评测记录](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)。

语义 verifier 注册为 `workflow_activity`：它不进入模型可见能力，也不能通过普通交互入口调用；运行系统通过独立固定流程校验与执行入口生成 `SemanticVerificationReceipt`。Verifier 只聚合 `passed|failed`；运行系统不解读逐判据的失败类别来选择工具相位。预算内的失败把完整 feedback 交还智能体决定修订或继续取证；下一轮已耗尽预算则直接停止。成功的个人知识 `Observation` 提交后，下一回合不再暴露已经完成的 `search_personal_knowledge`，但其他可见能力和最终交付入口保持可用。

当前代码在每个决策回合的系统 Prompt 中物化剩余 `model_turns`、`tool_calls`、`agent_calls` 和 `tokens`。下一决策调用前，`max_model_turns`、正数 `max_tool_calls` 或 `max_total_tokens` 任一耗尽即返回 typed 预算 `limitation`，保留已提交执行事实；即使模型已经请求 `prepare_final`，也不绕过该检查。预算分支不隐藏工具后追加强制 Final，不启动 Verifier，不生成替代答案；宽限状态与事件字段已删除。`max_tool_calls=0` 仍表示不使用工具，不会跳过正常的无工具回答。上限依据已提交用量检查，不承诺在途请求的最终 token 永不超过数值，也不把停止等同于研究完成。生产证据见[当前评测用例盘点](../evals/02-current-case-inventory.md)，取舍见 [ADR 0017](../adr/0017-separate-action-selection-from-final-delivery.md)。

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

模型 Port 只有一个 typed-operation retry owner。它重试 transport/5xx、malformed transport envelope 和 Provider 空 structured content；一般 schema/语义错误不作为 transient 重试，而由 typed repair、DecisionFeedback 或 fail closed 处理。required action phase 若收到零 action，Provider Adapter 使用完全相同的 action definitions 做一次协议修复，并明确禁止纯文本回答；第二次仍缺 action 即以 `provider_action_missing` 失败关闭。未知 action、无效 call ID、非法参数 JSON、非对象参数或不符合 Application action payload 不由 Adapter 猜测或改写。所有 retry 次数与稳定错误码进入模型 trace/usage。

当前 MiMo `StructuredModelClient` profile 为 `json_object`。Composition Root 统一选择 JSON Object Adapter；Adapter 使用版本化中文 system instruction 把调用方 Pydantic Schema 投影给模型，返回后仍由同一 Pydantic 类型校验，首次失败只允许一次完整重写。运行时不会根据失败切回 `json_schema` 或 plain text；通用 Strict Adapter 只由其他 deployment 的显式 capability profile 选择。

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
