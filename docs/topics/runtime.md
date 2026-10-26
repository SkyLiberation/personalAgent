# 当前 Runtime

**Runtime 负责装配和执行机械事实，不拥有用户目标、领域状态或最终完成语义。** 当前普通交互是一个基于 typed Observation 的 Conversation loop；固定事务由各自 Application/Domain 拥有。

回答结果由 Runtime 显式注入 direct 或 claims 模块，核验由 required/none 独立配置；同一个 Conversation 循环继续拥有执行、计量和唯一 Final。Journal 冻结装配，恢复及同对话新 run 不允许更换配置。默认保持 claims+required；无核验仅用于当前授权的独立流程诊断，范围与退出见 [ADR 0041](../adr/0041-replaceable-answer-result-modules.md)。

整个 Loop 已按[统一设计](../optimization/to_verify/conversation-loop-schema.md)替换为原生意图协议，实施决定见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。源码已删除空准备动作与独立 Final JSON 成文；局部生成与完整任务结果分别由统一设计和评测记录拥有，按实际范围报告。

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

进入主决策前，`derive_interaction_intent` 通过注册 Prompt 及原生输出工具识别交互相位、显式验收条件和响应后的后台要求。用户来源采用原消息索引及行坐标，Runtime 恢复原文；requirements 可引用历史用户消息，phase／background 只取最新用户。模型负责语义，Admission 校验来源与互斥；真实后台要求仍按 capability_missing 拒绝，未创建后台任务。原有一轮后台来源修订和 requirements 冻结保持。原始用户消息拥有完整目标，提取的条件不替代它；具体参数与尚未验收边界见[统一设计 §5](../optimization/to_verify/conversation-loop-schema.md#5-能力内部的-typed-输出)。

决策输入的剩余额度由 `interaction_prompt` 的 `RemainingInteractionBudget` 唯一物化。存在既有 `run_deadline_at` 时，ConversationService 从同一 Trace 截止与当前 UTC 派生 `wall_seconds_at_input`，action／ordinary final 同时收到快照说明；生成和执行持续计时，快照不是新的权限或保证时长。无截止时省略字段和说明，原四项额度保持。研究 writer 继续使用原独立输入；墙钟硬停止和恢复后的原截止保持；费用未知的继续政策见下段。研究部署的任务墙钟和累计实验执行额度分别显式配置，不再默认统一900秒；当前预算切片及工程验证见[研究Spec](../optimization/to_verify/knowledge-decision-delivery.md#长任务预算与诊断范围)。接入与结果边界见[主循环 Spec §3.17](../optimization/to_verify/conversation-loop-boundaries.md#317-已有运行截止的模型可见投影)。

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

普通外部研究的 claims 与最终回答由同一版本和原 Interaction Journal 保存；模型自主取证和编辑，统一核验通过后直接经 Completion 交付确切回答。全部调用计入原预算，不再构造独立汇总或研究 Final。当前生产接入、例外范围及正式验收状态见 [ADR 0032](../adr/0032-conversation-research-claims.md)。

部署绑定的检索实验不进入 claim／选证／语义 verifier。模型用原生提交交回完整候选，SubmittedFinal 与实际用量持久后检查引用、实际执行、冻结/test及权限，再返回同一 Final。恢复沿同稿完成校验，不发布清单、ZIP或报告 Artifact，不收集下载资源；该领域检查继续由 [ADR 0037](../adr/0037-experiment-submission-first-delivery.md)拥有，模型传输已由 ADR 0045 替换。

当前主循环仍直接编排研究局部步骤，代码职责混合见[架构现状](../architecture/core-architecture-current-state.md#31-当前主循环的职责混合)。[主循环边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md)拥有待验证整理方案；本页只说明现行行为。

模型决定开放语义和下一步 Proposal；代码决定 schema、scope、policy、唯一推导、预算与不变量；执行系统产生 execution fact；Verifier 和 Completion Gate 分别判断语义满足与 required result contract。

ConversationService 提交模型决策产生的 `DecisionFeedback` 时绑定 `decision_turn`，同轮多个工具被拒绝只算一次尝试，完整反馈仍全部交给下一轮模型。相同动作种类、原因和计划版本在成功进展之后跨两个不同决策回合被拒绝，才触发既有重复错误停止保护；Journal 恢复保留回合归属。前置非决策反馈不计为模型重试。责任与证据边界见 [ADR 0019](../adr/0019-bind-feedback-to-decision-turn.md)。

终止计划没有可执行活动项，直接提交新工具仍会被拒绝。反馈明确允许模型提出后续计划，沿已有交互模式与唯一活动项准入继续执行；不把历史已完成工作项重新标为未完成，也不把计划终止等同于用户任务完成。

Conversation 把本轮 `EffectiveCapabilities` 物化为逐动作 `ModelActionDefinition`，服务提供方通过原生工具调用返回动作名和 typed 参数。Tool/Agent 动作 Schema 不暴露 `plan_step_id`；模型通过独立 `control_working_plan` 修订进度，最多一个 `in_progress`；执行系统有活动项时关联它，没有时记录空关联，不用进度完成禁止工具。completed 可因新证据重开，历史执行事实不可改写。Provider Adapter 返回结构化原调用，Conversation 的模型接口 decoder 再将合法 wire 解码为现有 Proposal；Admission、权限、预算和执行网关仍在模型之外决定是否执行。

原生 function.arguments 只含该操作的直接业务参数，精确工具名、Schema 与解码由同轮 Definition 绑定；内部 Proposal 的 kind、调用身份和执行字段由 Runtime 恢复。实验工具按既有 descriptor 恢复领域 action，不要求模型重复输出通用包装。结构反馈使用实际 wire 坐标、原调用及缺失字段，不解析英文报错或自动填值。见[工具模型接口](tools.md#当前生产链路)与 [ADR 0043](../adr/0043-direct-code-agent-tool-parameters.md)。

主循环使用`action_choice=auto`，有调用时先处理调用，无调用的完整合法assistant正文由回答模块解释为候选。内层typed输出工具仍用required；不能推定所有Provider都支持同名强制参数。DeepSeek思考模式的既有参数适配由[主循环Spec §3.18](../optimization/to_verify/conversation-loop-boundaries.md#318-deepseek-思考模式的原生动作编码)拥有，该历史动作检查不能再被概括为当前主循环拒绝所有正文。

当前原生引用候选由 `FinalMessage.segments` 唯一保存正文及引用，`message` 仅为按序拼接的只读属性；旧正文写字段已删除，外部 `ConversationMessage.content` 仍为字符串。代码检查已验证回执与该正文相同后交付。最新完整提交与原子修订契约见 [ADR 0031](../adr/0031-complete-final-revisions.md)，完整交接检查点已成立，局部合并仅有 Offline 消费证据，完整 E2E 未通过。原生分段迁移与证据边界见 [ADR 0023](../adr/0023-native-answer-segments-and-visible-citations.md)。

Plan 是否开始新一轮以同一会话和身份下 Journal 已接纳的 answer 为边界，不能从全部步骤 completed 推导；未交付任务的修订保持 Plan 身份。跨轮恢复按同一边界保留该 Plan 的成功执行资料，包括无活动项时的结果。新计划仍遵守 default/auto 审阅规则。整体候选、证据和限制见 [ADR 0025](../adr/0025-revisable-plan-progress.md)。

主循环使用一套原生assistant消息协议：普通可见正文形成默认answer候选，submit_final(message,disposition,references)显式选择沟通属性／行引用，revise_final(base_resource_id,edits)修改当前稿，均进入同一个FinalMessage提交出口。有调用时正文仅作该轮说明，坏调用不能降为文字答案；空白、reasoning、截断或非法角色不形成候选。旧稿和claims的逐段结构不被拍平，claims适用时普通正文不能绕过首次或当前版本的写作。终止／修订／研究操作仍独占批次并在执行前检查。正文不会直接成为Completion事实；引用、适用核验、预算、计划及未决执行保持原门禁。意图判断及原后台来源修订使用显式prompted_json：通用Schema指令、原始JSON文本和原严格类型／来源校验，wire不请求工具或API格式功能。其余native typed能力继续使用同一原生输出声明；Infra用既有LangChain公共转换导出parameters。两类均保留原件、有限同承载修复及原类型，不强转业务值；当前验证边界由统一设计§15拥有。模板与版本由[Prompt Registry](../llm-prompts.md)拥有。

当前工作树删除了“有验收标准就已有待改正文和充分材料”的指令，也删除了由此强制非 `answer` 继续迭代的分支。
验收条件只约束结果，不决定用户任务或证据是否齐全；任务语义与合法 disposition 由模型判断。
普通交互存在冻结标准且模型提交 `answer` 时，仍由运行系统调用语义验证；`clarification_required`、`limitation`、
`failed` 不因标准存在而改成成功答案。合法终态不等于满足原用户结果；真实 E2E 已运行，但尚未到达模型 Final，见
[评测记录](../evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)。

普通整稿 verifier 注册为 `workflow_activity`，由运行系统调用并生成 `SemanticVerificationReceipt`，不进入模型可见能力。研究统一核验沿 Model Port 返回绑定当前版本的 `ResearchReview`，Completion 不再追加语义调用。Verifier 只聚合 `passed|failed`；运行系统不解读逐判据的失败类别来选择工具相位。预算内的失败把完整 feedback 交还智能体决定修订或继续取证；下一轮已耗尽预算则直接停止。成功的个人知识 `Observation` 提交后，下一回合不再暴露已经完成的 `search_personal_knowledge`，但其他可见能力和最终交付入口保持可用。

每个主决策仍收到剩余 model_turns／tool_calls／agent_calls／tokens。新增请求前检查原预算和截止；额度耗尽不妨碍解码已付费原件或完成无需新模型的同稿交付，但新的核验或执行仍守原边界。预算分支不生成替代答案、不增加强制 Final 宽限；max_tool_calls=0 不禁止正常无工具回答。阈值按已知消费检查，未知不填零也不单独停止；在途请求可超出数值，停止不等于研究完成。结果边界见[当前评测用例盘点](../evals/02-current-case-inventory.md)。

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

主循环无效动作修复唯一归 Application 决策循环，不再由 Adapter 隐式重生成；内层 typed 能力保留各请求原有有限修复次数。每份完整响应先保存原件与实际费用，稳定调用身份和 continuation 支持优先解码已付费输出。Journal 原件一次保存，Trace 使用 typed 引用；恢复不按 usage 轮数猜相位。REST／SSE 共享中性错误投影，输出无效、上游请求和本地 Runtime 分别归因，见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。
