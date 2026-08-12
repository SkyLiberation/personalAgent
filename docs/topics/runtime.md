# 当前 Runtime

**Runtime 负责装配和执行机械事实，不拥有用户目标、领域状态或最终完成语义。** 当前普通交互是一个基于 typed Observation 的 Conversation loop；固定事务与 durable Project 继续由各自 Application/Aggregate 拥有。

## 依赖与 owner

```text
HTTP / CLI / Message Adapter
  -> AgentService
  -> AgentRuntime (composition root)
       -> ConversationService
       -> KnowledgeService / KnowledgeLifecycleService
       -> InvestigationProjectService / ResearchService
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

## Context materialization

每次模型调用按以下顺序构造输入：

1. visibility/scope 过滤；
2. 当前问题所需的 personal evidence 与 linked Project projection；
3. capability/tool schema 投影；
4. committed Observation/Feedback；
5. budget materialization。

Personal Knowledge 通过 `personal_knowledge_context` 只读 Observation 进入；linked durable investigation 通过 `investigation_project_context` 进入。两者都不复制 canonical facts，也不成为写入口。

## Durable execution

- Conversation journal 保存 committed messages、typed inputs、usage、execution order、final message 及业务 reference；
- Knowledge save/delete 分别由自己的 Command/operation/Receipt owner 恢复；
- InvestigationProject journal 保存 definition、accepted plan、subgoal、evidence、verification 与 completion；Conversation 只保存 scoped `ProjectReference`；
- replay 复用冻结 Command 和已提交副作用，不重新调用模型生成它们。

## Model retry

模型 Port 只有一个 typed-operation retry owner。它只重试 transport/5xx、malformed transport envelope 和 Provider 空 structured content；一般 schema/语义错误不作为 transient 重试，而由 typed repair、DecisionFeedback 或 fail closed 处理。retry 次数与错误进入模型 trace/usage。

## Grounded answer

产品没有平行 Ask runtime。Conversation 是唯一 FinalMessage owner：个人证据由 `KnowledgeService.select_evidence()` 预取，外部事实由受治理只读 Tool 返回，模型在同一 loop 内综合。回答本身不写长期知识；显式保存必须另走确认写路径。

## 可观测与评测

- `InteractionTrace` 记录 typed inputs、usage、context composition、执行顺序和 final message；
- E2E archive 记录 `MeasurementProfile` 与 `CaseMeasurement`；
- `metrics_report` 生成同 profile 的完成率、token、调用、延迟与恢复指标；
- `release_gate` 独立判断 archive 能否用于目标 revision 发布。

## 不变量

- Runtime 不从关键词猜 intent、payload 或业务 plan；
- Proposal、Observation、Receipt、Verification 与 Completion 互不冒充；
- Tool schema 不是权限，Gateway 才产生受治理执行事实；
- 一个业务事实只有一个 owner 和写入口；
- 没有失败 baseline 与生产消费者时，不增加 Planner、Workflow、checkpoint、Registry 或兼容层。
