# 当前 Runtime

**Runtime 负责装配和执行机械事实，不拥有用户目标、领域状态或最终完成语义。** 当前普通交互是一个基于 typed Observation 的 Conversation loop；固定事务由各自 Application/Domain 拥有。

回答结果由 Runtime 显式注入 direct 或 claims 模块，核验由 required/none 独立配置；同一个 Conversation 循环继续拥有执行、计量和唯一 Final。Journal 冻结装配，恢复及同对话新 run 不允许更换配置。默认保持 claims+required；无核验仅用于当前授权的独立流程诊断，范围与退出见 [ADR 0041](../adr/0041-replaceable-answer-result-modules.md)。

主循环采用原生 assistant 消息与动作协议，实施决定见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。实际生成、完整任务结果及限制由[统一设计](../optimization/to_verify/conversation-loop-schema.md)与[评测盘点](../evals/02-current-case-inventory.md)维护。

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

进入主决策前，`derive_interaction_intent` 用注册 Prompt 和 `prompted_json` 提取交互相位、显式验收条件及响应后的后台要求。模型引用原消息索引和行坐标，Runtime 恢复原文；requirements 可引用历史用户消息，phase／background 只取最新用户。Admission 校验来源与互斥，后台来源允许一次修订，随后冻结 requirements。真实后台要求按 `capability_missing` 拒绝，不创建任务。提取条件辅助理解，完整目标仍由原消息拥有；具体契约见[统一设计 §5](../optimization/to_verify/conversation-loop-schema.md#5-能力内部的-typed-输出)。

`interaction_prompt.RemainingInteractionBudget` 向主决策物化剩余 model turns、tool calls、agent calls 和 tokens。存在 `run_deadline_at` 时，再由同一 Trace 截止与当前 UTC 派生 `wall_seconds_at_input`；无截止时省略。快照不暂停计时，恢复沿用原截止。任务墙钟和累计实验执行额度分别配置，参数与证据见[研究 Spec](../optimization/to_verify/verify_results/research-experiment.md#长任务预算与诊断范围)，快照契约见[主循环 Spec §3.17](../optimization/to_verify/conversation-loop-boundaries.md#317-已有运行截止的模型可见投影)。

通用 Python 分析可按显式主体／对话许可独立装配。Trace 保存该授权摘要；Journal 在对话锁内聚合原 run 消费，并投影成功程序及工作产物，后继 run 不复制 usage 或压缩 checkpoint。当前剩余 tokens 按已知消费受 per-run 和任务阈值约束；模型费用不完整时保留未知标记，仍可调用模型、压缩及跨用户轮继续，不以完整性标记判断任务完成。未决工具执行、授权和截止继续守原边界；原件读取经 Artifact 校验。通用授权不触发检索领域冻结／test；实现契约及尚未完成的真实验收见 [ADR 0040](../adr/0040-scoped-python-analysis-authorization.md)和 [Python Spec](../optimization/to_verify/python-data-analysis-tool.md#35-longds-用例的条件适配)。

```text
messages + authenticated principal
  -> scoped context/capability materialization
  -> action phase: one or more compatible Provider action calls
  -> deterministic Admission / budget / concurrency checks
  -> governed Tool/Agent/Application action execution
  -> ActionObservation | DecisionFeedback
  -> 模型继续选择动作，或以原生 assistant 正文／带属性提交形成完整候选
  -> 普通外部研究：同版本 claims 与 final_answer -> 统一核验 -> Completion
  -> 绑定检索实验：完整候选 -> SubmittedFinal -> 引用及实验文件检查 -> Completion
  -> 普通：完整候选 -> 冻结标准要求时执行整稿核验 -> Completion
  -> 交付确切通过的回答，或继续修订
```

普通外部研究的 claims 与最终回答由同一版本和原 Interaction Journal 保存，模型自主取证和编辑。同一研究版本提交的完整 `final_answer` 属于最终交付提议；Runtime 只将该字段的确切正文与引用恢复为 `FinalMessage`，按同版本统一核验，通过后直接经 Completion 交付确切回答。字段缺失时保存中间进展，继续研究；恢复不生成答案，也不增加独立汇总或第二次语义核验。全部调用计入原预算，不再构造研究 Final。当前生产接入、例外范围及正式验收状态见 [ADR 0032](../adr/0032-conversation-research-claims.md)。

部署绑定的检索实验不进入 claim／选证／语义 verifier。模型用原生提交交回完整候选，SubmittedFinal 与实际用量持久后检查引用、实际执行、冻结/test及权限，再返回同一 Final。恢复沿同稿完成校验，不发布清单、ZIP或报告 Artifact，不收集下载资源；该领域检查继续由 [ADR 0037](../adr/0037-experiment-submission-first-delivery.md)拥有，模型传输已由 ADR 0045 替换。

当前主循环仍直接编排研究局部步骤，代码职责混合见[架构现状](../architecture/core-architecture-current-state.md#31-当前主循环的职责混合)。[主循环边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md)拥有待验证整理方案；本页只说明现行行为。

模型决定开放语义和下一步 Proposal；代码决定 schema、scope、policy、唯一推导、预算与不变量；执行系统产生 execution fact；Verifier 和 Completion Gate 分别判断语义满足与 required result contract。

ConversationService 提交模型决策产生的 `DecisionFeedback` 时绑定 `decision_turn`，同轮多个工具被拒绝只算一次尝试，完整反馈仍全部交给下一轮模型。相同动作种类、原因和计划版本在成功进展之后跨两个不同决策回合被拒绝，才触发既有重复错误停止保护；Journal 恢复保留回合归属。前置非决策反馈不计为模型重试。责任与证据边界见 [ADR 0019](../adr/0019-bind-feedback-to-decision-turn.md)。

终止计划没有可执行活动项，直接提交新工具仍会被拒绝。反馈明确允许模型提出后续计划，沿已有交互模式与唯一活动项准入继续执行；不把历史已完成工作项重新标为未完成，也不把计划终止等同于用户任务完成。

Conversation 把本轮 `EffectiveCapabilities` 物化为逐动作 `ModelActionDefinition`，服务提供方通过原生工具调用返回动作名和 typed 参数。Tool/Agent 动作 Schema 不暴露 `plan_step_id`；模型通过独立 `control_working_plan` 修订进度，最多一个 `in_progress`；执行系统有活动项时关联它，没有时记录空关联，不用进度完成禁止工具。completed 可因新证据重开，历史执行事实不可改写。Provider Adapter 返回结构化原调用，Conversation 的模型接口 decoder 再将合法 wire 解码为现有 Proposal；Admission、权限、预算和执行网关仍在模型之外决定是否执行。

原生 function.arguments 只含该操作的直接业务参数，精确工具名、Schema 与解码由同轮 Definition 绑定；内部 Proposal 的 kind、调用身份和执行字段由 Runtime 恢复。实验工具按既有 descriptor 恢复领域 action，不要求模型重复输出通用包装。结构反馈使用实际 wire 坐标、原调用及缺失字段，不解析英文报错或自动填值。见[工具模型接口](tools.md#当前生产链路)与 [ADR 0043](../adr/0043-direct-code-agent-tool-parameters.md)。

主循环使用 `action_choice=auto`，有调用时先处理调用，无调用的完整合法 assistant 正文由回答模块解释为候选。内部 typed 输出工具按请求声明要求输出；服务提供方参数适配由[模型组合](../architecture/cross-cutting.md#2-模型调用的实际组合)拥有。

当前原生引用候选由 `FinalMessage.segments` 唯一保存正文及引用，`message` 仅为按序拼接的只读属性；旧正文写字段已删除，外部 `ConversationMessage.content` 仍为字符串。代码检查已验证回执与该正文相同后交付。最新完整提交与原子修订契约见 [ADR 0031](../adr/0031-complete-final-revisions.md)，完整交接检查点已成立，局部合并仅有 Offline 消费证据，完整 E2E 未通过。原生分段迁移与证据边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。

Plan 是否开始新一轮以同一会话和身份下 Journal 已接纳的 answer 为边界，不能从全部步骤 completed 推导；未交付任务的修订保持 Plan 身份。跨轮恢复按同一边界保留该 Plan 的成功执行资料，包括无活动项时的结果。新计划仍遵守 default/auto 审阅规则。整体候选、证据和限制见 [ADR 0025](../adr/0025-revisable-plan-progress.md)。

普通可见正文形成默认 `answer` 候选；`submit_final(message, disposition, references)` 显式选择沟通属性与行引用，`revise_final(base_resource_id, edits)` 修改当前稿，三者进入同一 `FinalMessage` 出口。有调用时正文只作该轮说明，坏调用不能降为文字答案；空白、reasoning、截断或非法角色不形成候选。claims 模式保留逐段结构，普通正文不能绕过当前版本写作。终止、修订和研究操作独占批次，引用、适用核验、预算、计划及未决执行在交付前检查。

意图判断及后台来源修订使用 `prompted_json`，以通用 Schema 指令、原始 JSON 文本和严格类型／来源校验承载，不请求工具或 API 格式功能。其他已迁移的内部 typed 能力使用原生输出声明，由 Infra 通过 LangChain 公共转换导出参数。两类承载都保留原件，按请求执行有限修复，不强转业务值。模板与版本见 [Prompt Registry](../llm-prompts.md)，验证范围见[统一设计 §15](../optimization/to_verify/conversation-loop-schema.md#15-内部意图判断采用提示式json的候选)。

验收条件约束结果，不表示已有待改正文或充分资料。模型根据任务选择合法 `disposition`；普通交互有冻结标准并提交 `answer` 时，运行系统执行适用语义核验。`clarification_required`、`limitation` 和 `failed` 不因标准存在而改成成功答案。该边界修复的实际用户结果见[评测记录](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)。

普通整稿 verifier 注册为 `workflow_activity`，由运行系统调用并生成 `SemanticVerificationReceipt`，不进入模型可见能力。研究统一核验沿 Model Port 返回绑定当前版本的 `ResearchReview`，Completion 不再追加语义调用。Verifier 只聚合 `passed|failed`；运行系统不解读逐判据的失败类别来选择工具相位。预算内的失败把完整 feedback 交还智能体决定修订或继续取证；下一轮已耗尽预算则直接停止。成功的个人知识 `Observation` 提交后，下一回合不再暴露已经完成的 `search_personal_knowledge`，但其他可见能力和最终交付入口保持可用。

新增请求前检查预算和截止；额度耗尽后仍可解码已付费原件，或完成无需新模型的同稿交付，新的核验和执行继续受预算约束。`max_tool_calls=0` 允许正常无工具回答，预算耗尽不生成替代答案或额外 Final 宽限。阈值按已知消费检查，未知不填零也不单独停止；在途请求可超出阈值。实际用户结果见[评测盘点](../evals/02-current-case-inventory.md)。

正常动作批次在 Plan／continue 准入后、工具持久接受前，先由现有 Journal 提交本批已发生的模型费用、Context 和已接纳 Plan。后续提交写完整用量并保留 latest 业务事实，两个动作不重复累加同一响应费用；提交失败不继续派发。该顺序的真实阶段反事实已验收，完整重启与交付仍独立验收，见[研究 Spec](../optimization/to_verify/verify_results/research-experiment.md#2-决策状态先于持久接受)与 [ADR 0035](../adr/0035-research-experiment-artifact-delivery.md)。

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

Model Port 统一拥有传输重试；Schema 或语义错误按各自输出协议处理，不当作临时网络故障。主循环设置 `max_output_repairs=0`，无效动作由 Application 决策循环反馈和修复；Adapter 不隐式重新生成。结构合法但未声明的动作由 `decode_model_action_invocations` 拒绝，整批不执行，原调用和字段诊断交给下一轮模型。Adapter 不猜测参数、补造调用身份或改写业务值。

内部 typed 能力保留各请求声明的有限修复次数，并在同一承载中修复。部署的默认结构化承载由 `STRUCTURED_OUTPUT_TRANSPORT` 选择，请求级 `native_tool` 或 `prompted_json` 使用各自声明；失败不自动切换格式。配置与服务提供方差异见[环境说明](../env.md#provider-选择与参数绑定)。

每份完整响应先保存原件与实际费用，恢复通过稳定调用身份和 continuation 优先解码已付费输出，Journal 原件只存一次，Trace 保存 typed 引用。失败携带已完成响应的用量，外层重试累计失败与恢复消费；后续传输失败不抹去先前已知费用。缺失的输入或输出用量保持未知，`total_tokens` 记录已知下界，延迟覆盖整个操作与等待。协议、原件和恢复契约见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。

## Grounded answer

产品没有平行 Ask runtime。Conversation 是唯一 FinalMessage owner：模型按当前目标选择 `search_personal_knowledge`，外部事实由受治理只读工具返回，模型在同一循环内综合。回答本身不写长期知识；显式保存必须另走确认写路径。

## 可观测与评测

- `InteractionTrace` 记录 typed inputs、usage、context composition、执行顺序和 final message；
- `conversation.model_failure` 记录 component、stage、operation、reason code、Provider host/status、retryable，以及同一 typed `ProviderFailureDiagnostics`；服务方业务错误码、错误类型、信息、请求 ID 和 `Retry-After` 在 Adapter 中按白名单提取。连接失败另保留最多八层异常类型及允许的传输异常消息、`ModelTransportDiagnostics` 快照。每个字符串最多 512 字符，密钥、认证值和 URL 脱敏；SDK HTTP 错误的完整字符串、响应体、Prompt 和 action 参数不进入诊断日志。现行 retry 的 scheduled/exhausted 日志沿用该对象，缺失仍未知；
- 完整工具响应被 `content_filter` 拒绝时，Adapter 在动作解码前停止且不重试，通过原错误对象携带真实响应和 `provider_response_complete=true`。Conversation 按原计量器保存其中的实际 usage；该标志不代替用量字段完整性，缺用量仍未知，真实断流仍按原规则标未知。完整过滤既不执行动作，也不进入参数修复；
- `llm.http.headers` 在正文读取前记录真实状态、白名单头和头到达时间；`llm.http.failed` 记录失败阶段，`llm.http.body_closed` 记录首末正文块时间、块／字节数及是否完整读取。每个物理请求有独立 `attempt_id`，状态随 Request 传递；时间以该请求开始为原点。`connect_host/port` 来自实际 TCP 连接事件，`peer_host/port` 来自当前 socket；复用连接时前者可缺失，未知不回填代理环境值。这些事实不代表 SDK 解析完成、用量完整或用户目标完成；
- SDK 在 SSE `[DONE]` 后正常关闭 HTTP 迭代器产生的 `GeneratorExit` 不记录为传输失败。原始 HTTP 正文未迭代至末尾时 `body_complete` 仍可为 false，须结合最终 SDK 完成观察判断模型响应是否完整；
- E2E archive 记录 `MeasurementProfile` 与 `CaseMeasurement`；
- `metrics_report` 生成同 profile 的完成率、token、调用、延迟与恢复指标；
- `release_gate` 独立判断 archive 能否用于目标 revision 发布。

## 不变量

- Runtime 不从关键词猜 intent、payload 或业务 plan；
- Proposal、Observation、Receipt、Verification 与 Completion 互不冒充；
- Tool schema 不是权限，Gateway 才产生受治理执行事实；
- 一个业务事实只有一个 owner 和写入口；
- 没有失败 baseline 与生产消费者时，不增加 Planner、Workflow、checkpoint、Registry 或兼容层。

REST／SSE 共享安全错误投影，分别标明模型输出协议、上游请求或本地运行错误；字段与状态映射见 [API](../api.md#post-apiconversationturn)。
