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

`AgentRuntime` 集中创建依赖和 Adapter，当前仍保留部分业务协调方法；业务事实继续由对应用例拥有。实际包布局和边界由[代码地图](../architecture/code-map.md)解释，不能把装配现状描述为已完全纯化。Application 通过 Port 消费外部依赖，具体存储和服务提供方实现由组合根注入。

## Conversation loop

进入动作相位前，`derive_interaction_intent` 通过注册的 `conversation.interaction_intent` 识别交互相位、显式验收条件及响应后的后台要求。当前指令明确区分本轮自主推进、系统向用户询问信息和用户稍后查询后台任务。模型提出语义判断，Admission 校验确切来源及互斥关系；真实后台要求仍按现有 capability_missing 边界拒绝，未创建后台任务。已有一轮背景来源修复与 requirements 冻结保持，真实阶段资格及正式入口剩余条件见[主循环 Spec §3.16](../optimization/to_verify/conversation-loop-boundaries.md#316-当前轮自主推进与响应后后台生命周期)。原始用户消息继续拥有完整目标，提取的条件不替代它。

决策输入的剩余额度由 `interaction_prompt` 的 `RemainingInteractionBudget` 唯一物化。存在既有 `run_deadline_at` 时，ConversationService 从同一 Trace 截止与当前 UTC 派生 `wall_seconds_at_input`，action／ordinary final 同时收到快照说明；生成和执行持续计时，快照不是新的权限或保证时长。无截止时省略字段和说明，原四项额度保持。研究 writer 继续使用原独立输入；硬停止、恢复后的原截止及未知消费规则不变。研究部署的任务墙钟和累计实验执行额度分别显式配置，不再默认统一900秒；当前预算切片及工程验证见[研究Spec](../optimization/to_verify/knowledge-decision-delivery.md#长任务预算与诊断范围)。接入与结果边界见[主循环 Spec §3.17](../optimization/to_verify/conversation-loop-boundaries.md#317-已有运行截止的模型可见投影)。

```text
messages + authenticated principal
  -> scoped context/capability materialization
  -> action phase: one or more compatible Provider action calls
  -> deterministic Admission / budget / concurrency checks
  -> governed Tool/Agent/Application action execution
  -> ActionObservation | DecisionFeedback
  -> returned source text opens research submission / model-selected prepare_final (within budget)
  -> 普通外部研究：同版本 claims 与 final_answer -> 统一核验 -> Completion
  -> 绑定检索实验：FinalSubmission -> SubmittedFinal -> 引用及实验文件检查 -> 发布与 Completion
  -> 普通：FinalSubmission -> 冻结标准要求时执行整稿核验 -> Completion
  -> 交付确切通过的回答，或继续修订
```

普通外部研究的 claims 与最终回答由同一版本和原 Interaction Journal 保存；模型自主取证和编辑，统一核验通过后直接经 Completion 交付确切回答。全部调用计入原预算，不再构造独立汇总或研究 Final。当前生产接入、例外范围及正式验收状态见 [ADR 0032](../adr/0032-conversation-research-claims.md)。

部署绑定的检索实验首轮不进入claim／选证／语义verifier。模型通过prepare_final进入FinalSubmission，SubmittedFinal与用量先持久；引用、实际执行、冻结/test及权限检查通过后直接返回同一Final。提交后恢复和已完成返回沿相同完成校验，不发布清单、ZIP或报告Artifact，不收集用户下载资源。原工具数据仍供模型读取和恢复，范围与验证边界见[ADR 0037](../adr/0037-experiment-submission-first-delivery.md)。

当前主循环仍直接编排研究局部步骤，代码职责混合见[架构现状](../architecture/core-architecture-current-state.md#31-当前主循环的职责混合)。[主循环边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md)拥有待验证整理方案；本页只说明现行行为。

模型决定开放语义和下一步 Proposal；代码决定 schema、scope、policy、唯一推导、预算与不变量；执行系统产生 execution fact；Verifier 和 Completion Gate 分别判断语义满足与 required result contract。

ConversationService 提交模型决策产生的 `DecisionFeedback` 时绑定 `decision_turn`，同轮多个工具被拒绝只算一次尝试，完整反馈仍全部交给下一轮模型。相同动作种类、原因和计划版本在成功进展之后跨两个不同决策回合被拒绝，才触发既有重复错误停止保护；Journal 恢复保留回合归属。前置非决策反馈不计为模型重试。责任与证据边界见 [ADR 0019](../adr/0019-bind-feedback-to-decision-turn.md)。

终止计划没有可执行活动项，直接提交新工具仍会被拒绝。反馈明确允许模型提出后续计划，沿已有交互模式与唯一活动项准入继续执行；不把历史已完成工作项重新标为未完成，也不把计划终止等同于用户任务完成。

Conversation 把本轮 `EffectiveCapabilities` 物化为逐动作 `ModelActionDefinition`，服务提供方通过原生工具调用返回动作名和 typed 参数。Tool/Agent 动作 Schema 不暴露 `plan_step_id`；模型通过独立 `control_working_plan` 修订进度，最多一个 `in_progress`；执行系统有活动项时关联它，没有时记录空关联，不用进度完成禁止工具。completed 可因新证据重开，历史执行事实不可改写。Provider Adapter 返回结构化原调用，Conversation 的模型接口 decoder 再将合法 wire 解码为现有 Proposal；Admission、权限、预算和执行网关仍在模型之外决定是否执行。

原生动作统一采用 `arguments: object` 外层，具体模型接口由同轮 Definition 同时提供 Schema、精确调用名与解码绑定。完整声明校验先于 Proposal；控制只去外层，实验工具按明确 descriptor 恢复原 `action` 字段，其他业务参数保持。结构错误反馈使用模型实际 wire 坐标并保留整批原调用；required错误由原Schema及当前对象推导到具体缺失属性，不解析英文报错或自动填值。该迁移不改变原 accepted request 的恢复、Command 或完成契约，见[工具模型接口](tools.md#当前生产链路)与 [ADR 0036](../adr/0036-explicit-native-action-payload.md)。

内部 `action_choice=required` 表达必须取得合法动作，不能推定所有服务端支持同名强制参数。DeepSeek思考模式实际拒绝required，Adapter的最小修正及验收由[主循环Spec §3.18](../optimization/to_verify/conversation-loop-boundaries.md#318-deepseek-思考模式的原生动作编码)拥有：只对该端点编码auto，内部动作检查和一次协议修复保持，纯文本不当Final或执行事实；真实接受及用户交付按实际证据记录。

当前原生引用候选由 `FinalMessage.segments` 唯一保存正文及引用，`message` 仅为按序拼接的只读属性；旧正文写字段已删除，外部 `ConversationMessage.content` 仍为字符串。代码检查已验证回执与该正文相同后交付。最新完整提交与原子修订契约见 [ADR 0031](../adr/0031-complete-final-revisions.md)，完整交接检查点已成立，局部合并仅有 Offline 消费证据，完整 E2E 未通过。原生分段迁移与证据边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。

Plan 是否开始新一轮以同一会话和身份下 Journal 已接纳的 answer 为边界，不能从全部步骤 completed 推导；未交付任务的修订保持 Plan 身份。跨轮恢复按同一边界保留该 Plan 的成功执行资料，包括无活动项时的结果。新计划仍遵守 default/auto 审阅规则。整体候选、证据和限制见 [ADR 0025](../adr/0025-revisable-plan-progress.md)。

`FinalMessage` 不再是可以与普通 Tool Call 并列返回的 Provider action。模型在 action phase 可通过无 payload 的 `prepare_final` 请求相位切换；需要核验且非计划审阅的研究任务，在已有真实可引用正文后也由运行时进入研究提交，模型仍可决定继续取证；兼容动作执行后，下一回合不暴露任何 action definitions，研究提交生成 typed `InitialResearchSubmission` / `ResearchSubmission`，由同一模型携带 claims 与可选最终回答；统一核验通过后 Runtime 从该字段恢复 `FinalMessage`。普通交付生成 strict typed `FinalSubmission`，完整稿或局部修订均还原为 `FinalMessage`。Final Prompt 投影冻结审查条件、工作清单语义内容和剩余预算，但不暴露 Plan identity、执行绑定或动作定义。主模板和 request version 统一由 [Prompt Registry](../llm-prompts.md) 拥有。`StructuredModelResponse` 禁止同时携带 typed value 与 action invocations。普通只读工具仍可在一个 action phase 并行调用，这条互斥只约束最终交付。

当前工作树删除了“有验收标准就已有待改正文和充分材料”的指令，也删除了由此强制非 `answer` 继续迭代的分支。
验收条件只约束结果，不决定用户任务或证据是否齐全；任务语义与合法 disposition 由模型判断。
普通交互存在冻结标准且模型提交 `answer` 时，仍由运行系统调用语义验证；`clarification_required`、`limitation`、
`failed` 不因标准存在而改成成功答案。合法终态不等于满足原用户结果；真实 E2E 已运行，但尚未到达模型 Final，见
[评测记录](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)。

普通整稿 verifier 注册为 `workflow_activity`，由运行系统调用并生成 `SemanticVerificationReceipt`，不进入模型可见能力。研究统一核验沿 Model Port 返回绑定当前版本的 `ResearchReview`，Completion 不再追加语义调用。Verifier 只聚合 `passed|failed`；运行系统不解读逐判据的失败类别来选择工具相位。预算内的失败把完整 feedback 交还智能体决定修订或继续取证；下一轮已耗尽预算则直接停止。成功的个人知识 `Observation` 提交后，下一回合不再暴露已经完成的 `search_personal_knowledge`，但其他可见能力和最终交付入口保持可用。

当前代码在每个决策回合的系统 Prompt 中物化剩余 `model_turns`、`tool_calls`、`agent_calls` 和 `tokens`。下一决策调用前，`max_model_turns`、正数 `max_tool_calls` 或 `max_total_tokens` 任一耗尽即返回 typed 预算 `limitation`，保留已提交执行事实；即使模型已经请求 `prepare_final`，也不绕过该检查。预算分支不隐藏工具后追加强制 Final，不启动 Verifier，不生成替代答案；宽限状态与事件字段已删除。`max_tool_calls=0` 仍表示不使用工具，不会跳过正常的无工具回答。上限依据已提交用量检查，不承诺在途请求的最终 token 永不超过数值，也不把停止等同于研究完成。生产证据见[当前评测用例盘点](../evals/02-current-case-inventory.md)，取舍见 [ADR 0017](../adr/0017-separate-action-selection-from-final-delivery.md)。

正常动作批次在 Plan／continue 准入后、工具持久接受前，先由现有 Journal 提交本批已发生的模型费用、Context 和已接纳 Plan。后续提交写完整用量并保留 latest 业务事实，两个动作不重复累加同一响应费用；提交失败不继续派发。该顺序的真实阶段反事实已验收，完整重启与交付仍独立验收，见[研究 Spec](../optimization/to_verify/knowledge-decision-delivery.md#决策状态先于持久接受)与 [ADR 0035](../adr/0035-research-experiment-artifact-delivery.md)。

## Context materialization

每次模型调用按以下顺序构造输入：

1. visibility/scope 过滤；
2. 模型已经选择的 personal evidence；
3. capability/tool schema 投影；
4. committed Observation/Feedback；
5. budget materialization。

Personal Knowledge 只有在模型选择 `search_personal_knowledge` 后，才通过有界 `tool_result` 进入。该投影不复制 canonical facts，也不成为写入口。

Conversation 的查询执行说明与可引用来源由[Context 专题](context-engineering.md#查询执行事实与来源证据)统一定义；原 Context 路径消费带查询说明的引用投影，不增加查询缓存或新循环。整体 Context 候选的撤回边界见 [ADR 0026](../adr/0026-separate-query-facts-from-cited-evidence.md)。

## Durable execution

- Conversation journal 保存 committed messages、typed inputs、usage、execution order、final message 及工作清单；
- Knowledge save/delete 分别由自己的 Command/operation/Receipt owner 恢复；
- 周期研究、投递和 Agent 运行按各自 Store 与 provider task identity 恢复；
- replay 复用冻结 Command 和已提交副作用，不重新调用模型生成它们。当前不提供响应结束后继续运行的动态调查能力。

## Model retry

模型 Port 只有一个 typed-operation retry owner。它重试 transport/5xx、malformed transport envelope 和 Provider 空 structured content；一般 schema/语义错误不作为 transient 重试，而由 typed repair、DecisionFeedback 或 fail closed 处理。required action phase 若收到零 action 或非法参数 JSON，Provider Adapter 使用完全相同的 action definitions 做一次协议修复，由注册的 `action.repair.system` 模板传入原始调用及错误数据，并明确禁止纯文本回答；第二次仍不满足协议即按原错误码失败关闭。Adapter 只校验调用身份、名称形状和参数对象等传输结构；结构合法但未声明的动作由 Application 的 `decode_model_action_invocations` 统一拒绝，并经 `DecisionFeedback` 交回下一轮，整批动作均不执行。这样保留响应用量及既有重复错误停止边界，不在 Adapter 提前抛出异常绕过恢复。无效 call ID、非法参数 JSON、非对象参数或不符合 Application action payload 不由 Adapter 猜测或改写。所有 retry 次数与稳定错误码进入模型 trace/usage。

当前 MiMo `StructuredModelClient` profile 为 `json_object`。Composition Root 统一选择 JSON Object Adapter；Adapter 使用版本化中文 system instruction 把调用方 Pydantic Schema 投影给模型，返回后仍由同一 Pydantic 类型校验，首次失败只允许一次完整重写。运行时不会根据失败切回 `json_schema` 或 plain text；通用 Strict Adapter 只由其他 deployment 的显式 capability profile 选择。

2026-10-01：非流式 structured 修复耗尽时，Adapter 将全部已完成响应的聚合用量附在 typed 失败上；外层唯一重试累计失败与恢复响应，成功及最终耗尽均由现行用量记录器消费一次。修复阶段的后续传输失败保留先前已知消耗。输入或输出用量不完整时对应字段保持未知，total_tokens 记录已知下界；重试次数包含有界结构修复与外层重试，latency 包含整个操作及等待。真实历史响应回放从 200,590 补齐至 224,770 tokens，与 Provider 汇总一致，详见[责任边界回放](../../.tmp/research-convergence-integration-20261001/usage-replay.json)。

## Grounded answer

产品没有平行 Ask runtime。Conversation 是唯一 FinalMessage owner：模型按当前目标选择 `search_personal_knowledge`，外部事实由受治理只读工具返回，模型在同一循环内综合。回答本身不写长期知识；显式保存必须另走确认写路径。

## 可观测与评测

- `InteractionTrace` 记录 typed inputs、usage、context composition、执行顺序和 final message；
- `conversation.model_failure` 记录 component、stage、operation、reason code、Provider host/status、retryable，以及同一 typed `ProviderFailureDiagnostics`；其中服务方业务错误码、错误类型、信息、请求 ID 和 `Retry-After` 在 Adapter 中按白名单提取，逐字段最多 512 字符，密钥、认证值和 URL 脱敏。现行 retry 的每次 scheduled/exhausted 日志沿用该对象；缺失仍未知，完整错误响应体、Prompt 和 action 参数不进入这些诊断日志；
- E2E archive 记录 `MeasurementProfile` 与 `CaseMeasurement`；
- `metrics_report` 生成同 profile 的完成率、token、调用、延迟与恢复指标；
- `release_gate` 独立判断 archive 能否用于目标 revision 发布。

## 不变量

- Runtime 不从关键词猜 intent、payload 或业务 plan；
- Proposal、Observation、Receipt、Verification 与 Completion 互不冒充；
- Tool schema 不是权限，Gateway 才产生受治理执行事实；
- 一个业务事实只有一个 owner 和写入口；
- 没有失败 baseline 与生产消费者时，不增加 Planner、Workflow、checkpoint、Registry 或兼容层。

2026-09-28 非法动作协议交接：Adapter 的一次有界重生成仍失败时，动作集合保持零准入，并将真实响应聚合用量随 `StructuredOutputFailure` 交回 Conversation。主循环记录原 typed 拒绝并允许预算内重新决策，不把这类已有响应的协议错误伪装成服务不可用。网络故障、结构化语义输出失败及重复错误保护保持各自边界；证据见 [ADR 0032](../adr/0032-conversation-research-claims.md#非法工具参数的错误交接)。
