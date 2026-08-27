# 设计优化队列

> 本文件只拥有尚未关闭的用户问题、准入状态、活动方案和退出条件。当前实现由 `summary/`、`topics/` 说明，执行结果由 `evals/` 与校验和归档保存；完成决策进入 ADR，不在队列中保留过程正文。

## 1. 当前结论

**当前没有已准入的生产实现方案。** `INTERACTION-INTENT-DELEGATION-CONTRAST-001` partial target 达到 `18/18` 语义正确，但 P95 `52.539s` 超过预声明 `45s`，已与双证据 span、普通研究参数修订和 AgentArtifact finalization 候选一起完整撤回。后续同时间窗 Provider Conformance 仅得到 control `1/20`、contrast `0/20` 的弱语义差，同时 contrast 增加 `1,768` token 且 P95 更高，不支持复活该 Prompt 候选。`INVESTIGATION-PROJECT-WITHDRAWAL-001` 已正式关闭并转入 [ADR 0015](../adr/0015-withdraw-investigation-project.md)。

| 编号 | 问题类型 | 当前状态 | 下一道门禁 |
| --- | --- | --- | --- |
| `CONVERSATION-RESEARCH-DELIVERY-001` | 普通研究结果缺口 | A1；当前生产 baseline `0/20 delivered`；逐工具 Schema 候选虽恢复 68 次 Tool 执行但 target 仅 `4/20 delivered`，已撤回 | 暂停局部参数补丁；后续候选必须同时解释当前参数不可表达和候选开启后 15 条预算耗尽，且仍需新的 Complexity Justification |
| `AGENT-DELEGATION-DELIVERY-001` | 显式委托稳定性缺口 | A1；历史组 `10/20 delivered`；2026-08-27 当前正式 baseline 为 `2/20 delivered`；单次 answer-only partial target `0/6` 已撤回；冻结成功 Artifact 的 FinalMessage Conformance 只有 `4/7` IDs 精确匹配、现有 Admission `5/7` 接受 | 父级收口 Conformance 未过 `7/7` 门槛，不准入生产候选；子级超时仍是独立责任主体。后续必须提出新的单一 semantic-completion contract，并先补两个 A 级实现比较与新的 Complexity Justification |
| `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` | 前台委托被误判为后台持续 | A1；只读旋转诊断 `1/20`、同输入重复诊断 `3/20`；正式 HTTP baseline `5/20` false-background；双 span partial target `0/8` false-background，但延迟门槛失败并撤回 | 同时间窗 Provider Conformance 已完成；当前不再投 Prompt/schema 候选。只有新的正式入口自然输入 cohort 在当前代码重复达到预声明错误门槛，并且新机制先证明配对净收益时才重开 |
| `INTERACTION-INTENT-DELEGATION-CONTRAST-001` | 同一 Semantic Decision 的前台/后台反事实不稳定 | A1；原 schema 两批合计 `5/40` false-background；对比示例 partial target `0/18`、P95 `52.539s`，已撤回；严格交错 Conformance 为 control `1/20`、contrast `0/20`，contrast token 与 P95 更高 | 关闭当前对比示例方向；Conformance 不是产品 target，单个不一致 pair 不足以抵消已失败的产品成本门禁 |

活动实现候选数为 **0**。InteractionIntent 的两个候选都改善了 partial target 语义，却被预声明成本门禁否决；严格交错协议又只观测到一个语义不一致 pair 和更高的 contrast 成本，因此当前关闭 Prompt/schema 局部方向。成功 Artifact 后 Plan 收口的只读 Conformance 也未过 `7/7` 门槛，不能复活 answer-only 候选；子级授权/超时继续作为独立责任主体冻结。

评测控制面已完成一项内部工程优化：`PromotionGateController` 会在每个 checksum 有效的 ProductEvidence 样本封存后计算预声明 cohort 门槛，门槛不可逆失败时停止余下昂贵样本，但只有完整达到预声明样本数才允许通过。它不改变上述生产候选数，也不把 partial target 晋升为产品证据。

第二阶段已把 `AGENT-PERF-001-DELEGATE` 迁移到执行前 evidence enrollment，使调用阶段的 pre-capture 失败可以封存并触发早停；但本轮正式行为回归只有 `19/20` 正确 limitation，因此该内部实现当前状态为 **implemented, not release-admitted**，不得据此声明当前 dirty revision 行为已验证或可发布。

第三阶段已把 `BACKGROUND-CONTINUATION-LIMITATION-001` 从“一个 pytest item 内循环 20 次”破坏式替换为 20 个独立正式样本。真实运行在第 `2/20` 条产品失败后自动停止剩余 18 条，证明评测反馈优化生效；产品 target 同时被正确拒绝，当前发布状态仍不改变。

## 2. DeepSeek Harness 外部机制比较（未准入）

本轮核对对象为 DeepSeek Harness `dsh@0.1.1-rc.2`、提交 [`b150a551`](https://github.com/deepseek-ai/deepseek-harness/commit/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e)，核对日期为 2026-08-26。该项目的 [README](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/README.md) 明确标记为开发者预览版（developer preview）并允许兼容破坏。因此，本工程只把已发布源码和架构契约作为 A 级机制参考，不把其稳定性、对象数量或拓扑当作需求证据。

| 机制域 | DeepSeek Harness 的可复核语义 | 本工程结论 | 进入候选前的门禁 |
| --- | --- | --- | --- |
| 消息注入与中断 | [Session](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/session.md) 用持久消息箱区分 `followup`、`steer`、`inject`；消息拥有 `MessageId` 和 `inserted`、`claimed`、`discarded` 生命周期，普通后续与步骤边界中断的唤醒语义不同 | **借鉴契约，不立即实现。** 若未来重新证明响应后继续工作是用户能力缺口，必须把 `accepted`、`claimed`、`discarded`、`settled` 分开；“已接收消息”不能代表“已交付结果” | 先形成独立产品失败 baseline；再与 [Temporal 固定流程消息传递](https://github.com/temporalio/documentation/blob/6f46de944c41b1823331536a65356548b94578c7/docs/develop/java/workflows/message-passing.mdx) 的 Signal/Update 接收与完成边界做第二个 A 级交叉核对，并定义同输入单变量消融 |
| 可恢复执行单元 | [Core](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/core.md) 与 [Subagent](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/subagent.md) 以一个持久 `Session`、至多一个进程内 `Activation`、一个 `AgentHandle` 和唯一先进先出消息箱继续执行，不再叠加中间 `Task` 状态机 | **只借鉴“单一执行责任主体”。** 若准入，`AgentRun` 只拥有执行事实，Application 层继续拥有 `Goal`、业务状态、结果契约和 Completion；禁止恢复通用 `Project`、`Task` 或第二套智能体循环 | 必须证明前台请求无法满足响应后交付的真实用户需求，并核对 Temporal 的确定性、replay、重试与补偿契约；DeepSeek Harness 的[本地 Job](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/jobs.md)或 `Activation` 不得被解释为恰好一次或跨进程副作用重放保证 |
| Session 事实与模型上下文 | [Session 事件日志](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/session.md) 是只追加事件日志（append-only event log）和权威事实源。模型历史从类型化事件推导，模型可见输入必须能由日志重建 | **诊断完成，暂不准入。** 20 个正式交互的完整快照写入放大 P95 为 `7.285x`，但总量只有 `1,652,203 B`；重复的新实例恢复测量 P95 均不超过 `1.113 ms`，重建与正式 API trace 不一致为 `0/20`；尚未形成影响用户或工程交付的约束 | 只有在真实规模下复现恢复、磁盘或写入延迟门槛失败，并补齐第二个独立 A 级实现后，才可提出单一事实源的破坏式替换；禁止快照与事件日志双轨 |
| 上下文令牌压力与 compaction | [TokenMeter](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/token-meter.md) 只在规范请求封套一致时复用服务提供方用量，否则估算完整请求面；[Compaction](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/compaction.md) 在步骤执行前出现压力或溢出时，先确定性裁剪工具结果并重新计量，再按需总结，同时保持工具调用与结果配对 | **当前 baseline 未复现，退出。** 同一 20 交互、157 个模型回合中，单回合输入 token P95 为 `7,058`、最大 `7,409`，没有上下文溢出或错误截断；继续保留 `Artifact` 精确读取主路径 | 只有正式入口出现可重复的上下文溢出、错误截断或预检明显失真，才重开并与 OpenAI 官方 [Responses compact](https://developers.openai.com/api/reference/java/resources/responses/methods/compact) 契约交叉核对 |
| 工具执行治理 | [Tools](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/tools.md) 在执行前给出 `allow`、`deny`、`ask`，并用单调保护保证后续监听器只能收紧、不能重新放行 | **不新增生产机制。** 当前 `Proposal`、`Admission`、`Policy`、`Grant` 和 `Gateway` 已提供更强的权力边界；只在现有测试无法机械证明“拒绝不可被后续阶段翻转”时补最小不变量测试 | 先给出可复现的策略翻转工程基线；没有失败则退出，不引入监听器链或新的 `Policy` 责任主体 |
| 全插件化与开放事件合并 | [Architecture](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/architecture.md) 将 harness 组件统一为插件，并允许多个插件贡献或合并 `Session` 事件 | **拒绝移植。** 当前没有两个独立生产消费者或已测变化源；全插件化会弱化 Application Capability、Domain 责任主体、穷尽类型和单一写入口 | 不进入候选；只有外部协议边界或第二个真实消费者出现，并且净删除复杂度为正时，才重新审计 |

DeepSeek Harness 的核心完成判定（core completion）表达运行系统“当前没有未清偿义务”，不等于用户 `Goal` 已语义满足。本工程继续保留 `Execution Fact -> Semantic Verification -> Completion` 分离，禁止用 `job finished`、`session finished`、消息 `settled`、工具调用或状态 `success` 替代用户结果。

## 3. `CONVERSATION-RESEARCH-DELIVERY-001` 已撤回实验

逐工具 Schema 参数修订曾按下述 Complexity Justification 准入。正式 target 证明它能把 Tool 成功执行从 `0` 提升到 `68`，却只把 delivered 从 `0/20` 提升到 `4/20`，并把 P95 从 `239.337274s` 恶化到 `277.645424s`、总 token 从 `1,013,659` 增加到 `1,540,709`。它因此不是可保留的产品优化；实现、helper 和专用测试均已删除。

### 3.1 失败 baseline 与唯一阶段

- 正式入口：`POST /api/conversation/turn`，`interaction_mode=auto`，真实 MiMo、PostgreSQL、Web Search 和 A2A Composition；五类自然研究请求各重复四次。
- 不可变归档：`data/e2e_traces/product_baselines/conversation-research-delivery-001/baseline/20260827T034117.920622Z-5044-d7d2e301`；`checksums.sha256` 已机械复核有效。
- 用户结果：`0/20 delivered`、`0` 个入口错误；失败分类为 `15/20 tool_arguments_rejected`、`3/20 agent_execution_failed`、`2/20 disposition_limitation`。
- 最早主导阶段：Admission 前累计 `226` 次 `invalid_arguments`，普通 Tool 成功与失败执行均为 `0`；外部 Agent 有 `10` 次成功 Artifact 和 `5` 次失败，但没有一条形成 required result contract。
- 成本对照：P95 `239.337274s`、`152` 个模型决策轮、`172` 次模型调用、`1,013,659` token。模型 Provider 请求和顶层结构化解析持续成功，不能把失败归因于环境或 JSON 解析。
- 机械根因：`ToolCallProposal.arguments` 是开放 `dict[str, Any]`；顶层严格结构化输出经 `strictify_schema` 后把该对象变成 `additionalProperties=false` 且没有属性，服务提供方只能生成 `{}`。真实 `WebSearchArgs.query` 是必填字段，随后被现有 `InteractionToolPort.validate_interaction_call` 确定性拒绝。

### 3.2 External Mechanism Comparison

核对日期为 2026-08-27。以下均为 A 级官方契约，且生产语义一致：模型先看到某个具体工具的参数 Schema，再返回该工具的结构化参数；没有实现把任意工具参数藏在顶层严格输出中的开放对象。

| 实现 | 可复核坐标与契约 | 本工程采纳 / 拒绝 |
| --- | --- | --- |
| OpenAI Function Calling | [API Reference：Function tool](https://developers.openai.com/api/reference/resources/responses/methods/create) 的 `tools[].parameters` 是该函数参数的 JSON Schema，`strict` 控制参数 Schema 遵循；返回 function call 的结构化 arguments | 采纳“逐工具 Schema + 强制已选工具”的传输语义；不迁移 Responses 对象、后台状态或完整工具循环 |
| Anthropic Tool Use | [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools) 的每个 client tool 拥有 `input_schema`；[Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls) 的 `tool_use.input` 应符合该 Schema | 采纳参数 Schema 由具体工具拥有；不引入 Anthropic 消息块、Tool Runner 或第二执行循环 |
| Gemini Function Calling | [Function calling](https://ai.google.dev/gemini-api/docs/generate-content/function-calling) 的 `FunctionDeclaration.parameters` 定义具体函数输入，模型返回 `FunctionCall.name` 与 `args` | 作为第三个独立交叉核对；不引入 SDK 自动执行或多工具编排 |

### 3.3 已实验的最小候选、事实 owner 与生产路径

实验唯一变量为 **`ConversationService` 是否消费一次逐工具 Schema 参数修订结果**：

1. 顶层模型继续拥有开放世界的 Tool 选择、`action_id`、`plan_step_id` 和目标语义；现有 Proposal 首次进入同一 Admission。
2. 仅当普通 `InteractionToolPort` Tool 被以 `invalid_arguments` 拒绝、且反馈只允许修订 `arguments` 时，Application 把原始对话、已提交的有界输入、Admission 反馈和该 Tool 的 `EffectiveToolCapability.input_schema` 交给现有模型 Port；`tool_choice` 强制为已经选定的 transport wire name。
3. 模型返回一次函数调用参数。Application 只能沿用不可变的 `action_id`、canonical `tool_name` 和 `plan_step_id`，替换反馈明确允许修订的 `arguments`；wire name 不匹配、调用数量不为一、参数不是 JSON object 或二次校验失败都 fail closed。
4. 修订后的完整 `ToolCallProposal` 再进入现有 Admission；Policy、Grant、Gateway、Execution、Verification 和 Completion 均不改变。模型调用计入 `model_calls` 与 token，但不伪装成新的用户级模型决策轮。

事实 owner 不变：工具定义仍由 Tool Registry/Application Capability 拥有，参数 Proposal 仍由模型产生，Admission 仍只接受或拒绝，Execution 仍产生执行事实。候选不新增表、持久状态、Interface、Registry、Planner、Workflow、Agent、Task、Event、Receipt 或第二写入口；参数修订只在当前请求内存中存在，恢复仍以已提交 Proposal/Observation 为准。

实验生产可达链为 `POST /api/conversation/turn -> ConversationService.respond -> 顶层 ToolCallProposal -> Admission invalid_arguments -> 单次逐工具 Schema 模型修订 -> 同一 Admission -> InteractionToolPort -> Gateway -> Tool Observation -> Verification/Completion -> 用户答案`。target 真实消费了该链；当前生产代码已删除参数修订消费点并恢复工具零执行和参数拒绝的 baseline 行为。

拒绝的替代方案：

- 不恢复已经在 MiMo 真实样本中得到 `0/3 delivered` 的 JSON-string 参数传输；
- 不为全部动态工具构造顶层 Pydantic union，因为它扩大主决策 Schema、缓存和生命周期复杂度；
- 不增加模型轮次、重试、Prompt 提醒或 fallback，因为当前通道机械上无法表达任何参数键；
- 不改写 Admission 来补全 query，因为确定性代码不拥有开放语义参数。

### 3.4 预声明 Target、消融、指标与退出条件

同一数据集、输入顺序、身份、初始事实、正式入口、真实 Provider、预算、grader 和配置 cohort 下预声明：

| 指标 | baseline | target 门槛 |
| --- | ---: | ---: |
| delivered | `0/20` | `>=15/20`，且五类场景每类至少 `3/4` |
| `tool_arguments_rejected` | `15/20` | `<=2/20` |
| `invalid_arguments` | `226` | `<=22`（至少下降 90%） |
| 成功 Tool Observation | `0` | `>=15`，且至少四类场景出现 |
| 入口错误 | `0` | `0` |
| P95 用户可见延迟 | `239.337274s` | `<=239.337274s` |
| 总 token | `1,013,659` | `<=800,000` |

target 还必须通过现有权限不可翻转、隐藏 Tool 不可执行、预算、并发、重复 action、Plan 绑定、Verification/Completion 和模型 Provider contract 回归。状态 `success`、Tool 被调用或 Trace 命中不能替代 delivered grader。

原计划只有在 target 达到用户门槛后，才在候选代码状态的独立 patch/worktree 中只关闭第 2-3 步生产消费点。target 已先违反退出条件，因此不再为失败候选追加一轮高成本消融，也不保留生产 flag、fallback 或双轨入口；当前 baseline/target 的生产差异已证明参数修订被真实消费，但不用于声称候选可上线。

任一 target 用户门槛未达到，或延迟/token 超限，立即撤回候选并删除 helper、消费点和专用测试；若参数拒绝消失但交付仍失败，则把下一最早失败阶段作为新 baseline，禁止顺手修改 Agent、Plan、Verification 或 Completion。

### 3.5 正式 Target 结果与撤回

- target 归档：`data/e2e_traces/product_baselines/conversation-research-delivery-001/target/20260827T044341.716001Z-4012-aa452575`；baseline/target 的 checksum 和身份配对均机械验证有效。
- 用户结果：`4/20 delivered`；各场景分别为 `0/4`、`1/4`、`1/4`、`0/4`、`2/4`，未达到总量和任一场景门槛。
- 参数与执行：`invalid_arguments 226 -> 25`，未达到 `<=22`；Tool 成功 `0 -> 68`，Tool 失败仍为 `0`；说明机制真实生效，但 Tool 执行不能替代用户交付。
- 成本与延迟：模型决策轮 `152 -> 117`，模型调用 `172 -> 218`，token `1,013,659 -> 1,540,709`，P95 `239.337274s -> 277.645424s`；额外参数调用和恢复后的执行显著增加净成本。
- 后续失败：16 条未交付中，15 条以“本次交互已达到执行预算上限，未生成替代答案”结束；成功 Tool 之后仍累计 `completed_plan_step_immutable=7`、`plan_step_not_pending=7`、`invalid_arguments=17` 等反馈。这个分布只允许开启新的失败阶段诊断，不授权直接增加预算、重试、禁用 Agent、修改 Plan 或放宽 Completion。
- 撤回状态：逐工具 Schema helper、`ConversationService` 消费点和专用测试已删除；Conversation/模型回归恢复为 `130 passed`。正式产品仍保持 baseline 行为，不能声称研究能力已改善。

## 4. `AGENT-DELEGATION-DELIVERY-001` 当前正式 baseline

2026-08-27 直接复用既有 `evals/product_baselines/test_agent_perf_delegate_001.py`，从正式 `POST /api/conversation/turn`、`interaction_mode=auto` 进入真实 MiMo、PostgreSQL 与 GPT Researcher A2A 主路径。四类自然显式委托主题轮转五次，共 20 个同配置样本；没有新增测试专用旁路或生产机制。

- 证据根：`data/e2e_traces/product_agent_perf_delegate_current_20260827/agent-perf-001-delegate/baseline/`；20 份独立 archive，checksum 错误 `0`，`config_cohort` 唯一值数量为 `1`，commit `35f1426964cf26d489a2432cb57382e558813199`，dirty tree 由 manifest digest 冻结。
- 用户结果：`2/20 delivered`，P95 `202.786s`，总 token `989,369`、P95 `56,055`，模型决策轮 `157`、模型调用 `177`；入口错误为 `0`。四类主题分别为 `1/5`、`1/5`、`0/5`、`0/5`，不能归因于单一主题。
- 子级执行事实：`9/20` 子任务为 `completed`，其中 `2` 条交付、`7` 条父级未交付；`11/20` 为 `timed_out`。这否定“30 秒父级等待预算是唯一失败阶段”，也证明延长预算最多只能处理部分样本。
- 父级收敛事实：累计 `invalid_arguments=111`、`agent_artifact_already_returned=13`、`plan_step_binding_required=10`、`duplicate_action_id=7`、`plan_step_not_pending=7`、`completed_plan_step_immutable=4`。成功 Artifact 存在仍不能替代父级结果契约；现有 grader 对其中部分样本表面分类为 `authoritative_source_missing`，因果分类必须以 trace 中最早失败阶段为准。
- 单次 `E17` 重跑曾在进入 AgentGateway 前把请求误判为 `background-continuation`，但本 20 样本没有复现该入口失败，因此不准入 InteractionIntent 修改。
- 当前退出结论：不存在一个已证明的单变量能同时消除 `11` 次子级超时和 `7` 次 completed-but-undelivered。禁止直接增加预算、重试、模型轮次或后台 Session，也禁止复活已撤回的逐工具参数修订；后续若提出组合候选，必须先解释为何它仍是一个责任主体和一个可消融变量，并重新定义 Complexity Justification。

### 4.1 同批 Session 日志与 Context 压力诊断

该 20 样本同时提供 `FileInteractionJournal` 的工程基线，不另造产品失败：

复核命令：`python -m evals.provider_diagnostics.interaction_journal_snapshot_001 <server-data/interaction_runs> data/e2e_traces/product_agent_perf_delegate_current_20260827`。脚本只读日志和 checksum 归档，不是生产入口或产品能力证据。

- 每个交互保存 `7–10` 个全量版本，版本数 P95 为 `10`；累计快照 `1,652,203 B`，最终快照合计 `251,457 B`，单交互写放大最小 `4.702x`、P95 `7.285x`、最大 `7.427x`。
- 用新的 `FileInteractionJournal` 实例逐个恢复最终版本，重复测量 P95 均不超过 `1.113 ms`，观测最大值 `5.383 ms`；与正式 API 归档的 `InteractionTrace` 结构不一致为 `0/20`。
- 157 个真实模型回合的输入 token P95 `7,058`、最大 `7,409`；typed inputs 字符 P95 `9,070`、最大 `10,492`，没有服务提供方上下文溢出、错误截断或预检失真。
- 结论：写放大是已测现象，但在当前规模下未造成恢复或用户结果约束；事件日志与 compaction 均不准入。未来若重开，必须以新的真实规模失败 baseline 为需求来源，不能把 DeepSeek Harness 的结构当作需求。

### 4.2 委托归因观测基线

当前 20 样本能够证明 `11` 次 `timed_out`，却不能从 checksum archive 还原每次模型授权的 `time_budget_seconds` 或提交后的真实等待时长：`DelegationGrant` 在 Gateway Admission 使用后没有持久消费者，`ChildAgentRunRecord` 和 `InteractionTrace` 均不保存该事实，现有 Agent 事件也没有时间坐标。这个缺口只阻止责任归因，不是用户能力失败本身。

允许的最小诊断改动是一次结构化日志：由 `ConversationService` 在每次真实委托结束时记录 `action_id`、`agent_id`、授权预算、提交后等待时长、Application 总耗时、Provider 终态和 Application 观察终态。日志不包含子目标或 Artifact 内容，不进入模型上下文、Grant、AgentRun、Projection 或用户响应，不改变 deadline、重试、状态迁移和 Completion。该改动按“用户行为不变的观测资产”验收；只有新的正式入口样本消费这些字段后，才允许讨论预算 owner，日志本身不能作为交付优化。

归因复测复用正式委托用例前五个自然样本，证据位于 `data/e2e_traces/product_agent_perf_delegate_attribution_20260827/`，5 份 archive checksum 错误为 `0`。结果为 `1/5 delivered`：四次 Provider `completed` 的授权预算分别为 `120/180/180/240s`，实际等待 `74.641–109.859s`，其中三次父级未交付、一次交付；唯一 `timed_out` 样本由模型只授权 `60s`，在 `60.031s` 触发。它证明短授权与成功 Artifact 后父级不收敛是两个独立责任主体，禁止包装成一个预算候选。

### 4.3 `AGENT-ARTIFACT-FINALIZATION-001` 已否决实验

该候选只处理 20 样本中 `9` 个 Provider 已 `completed` 的父级消费阶段，不声称修复 `11` 次子级超时。当前正式 baseline 中 completed-to-delivered 为 `2/9`，另 `7` 条跑到父级预算耗尽；成功 Artifact 之后仍产生 `35` 次 `invalid_arguments`、`58` 条 typed feedback，9 条 completed 路径合计 `69` 个模型决策轮与 `460,685` token。归因复测又在 120、180、240 秒授权下重复三类 completed-but-undelivered，因此该父级失败已独立成立。

External Mechanism Comparison（核对日期 2026-08-27，A 级）：

| 实现 | 可复核契约 | 本工程采纳 / 拒绝 |
| --- | --- | --- |
| OpenAI Agents SDK [Manager / agents-as-tools](https://openai.github.io/openai-agents-js/guides/agents/#composition-patterns) 与 [Python tools](https://openai.github.io/openai-agents-python/tools/#agents-as-tools) | Manager 保留对话控制权，specialist 作为 Tool 返回结果，manager 负责最终总结；嵌套 Agent 的结果回到中央 Agent，而不是自动成为用户答案 | 采纳“子级结果返回后由父级受限综合”的边界；不迁移 Runner、handoff、Agent-as-Tool 对象或工具循环 |
| DeepSeek Harness [`SubagentResult`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/subagent.md#the-one-shot-start-request) | one-shot child 的成功结果按可选 `outputSchema` 返回 `SubagentResult.structured`，父级继续拥有消费；不为一次结果额外创建 Task 状态机 | 采纳“成功返回形成有界父级输入”；不引入 Session、Activation、report tool 或 continuable child |

Complexity Justification：

1. 唯一变量为：提交一个 `status=succeeded` 的 `agent_artifact` 后，下一次模型调用是否进入现有 `_decide_answer_only`，而不是再次开放 Tool、Agent 或 Plan Proposal。它只改变父级下一决策的允许输出类型。
2. 复用现有 `FinalMessage`、`resolved_plan_step_ids`、`admit_final_plan_resolution`、未读 Artifact 门禁、Review Verification 和 Completion；不新增 Model、状态、表、Interface、Registry、Workflow、Agent、Tool、事件或第二写入口。
3. Application 不自动宣布完成、不修改 Plan、不补字段；模型仍判断证据是否足够并可返回 truthful limitation。非法 Plan resolution、未读 offload 和 Review 失败仍由原门禁拒绝。
4. 候选只在当前交互内设置一次临时 `answer_only_pending`，不持久化派生状态；恢复行为继续由已提交 Artifact 与 Plan 重建。
5. 拒绝直接增加模型轮数、预算或 Prompt 重试；拒绝把成功 Artifact 当最终答案；拒绝恢复已撤回的逐工具参数修订，因为它在普通研究 target 中显著增加成本且未达用户门槛。

预声明同输入 20 样本 target：

| 指标 | baseline | target 门槛 |
| --- | ---: | ---: |
| 总 delivered | `2/20` | `>=8/20` |
| completed-to-delivered | `2/9` | `>=80%`，且 target 至少有 5 个 completed 样本 |
| completed-but-undelivered | `7` | `<=2` |
| 成功 Artifact 后 `invalid_arguments` | `35` | `<=2` |
| 总模型决策轮 | `157` | `<=120` |
| 总 token | `989,369` | `<=800,000` |
| P95 用户可见延迟 | `202.786s` | `<=202.786s` |
| 入口错误 | `0` | `0` |

target 还必须通过 Conversation、Plan、权限、重复委托、Artifact、Verification/Completion 和 Provider contract 回归。只有 target 达标后，才在独立 patch 中只关闭“成功 AgentArtifact 后设置 `answer_only_pending`”这一消费点执行消融；target 任一用户、延迟或成本门槛失败则删除候选，不追加预算修复。

执行结果（2026-08-27）：

- 候选代码状态先通过 `tests/test_conversation_interaction.py tests/test_structured_model.py`：`130 passed`；随后按同一正式入口、自然输入、真实 MiMo/PostgreSQL/GPT Researcher A2A 和既有 grader 启动 20 样本 target。证据根为 `data/e2e_traces/product_agent_perf_delegate_finalization_20260827/agent-perf-001-delegate/target/`。
- target 在第 6 个样本后提前停止，不能冒充完整 20 样本结果：stdout 用户结果为 `0/6 delivered`，其中 4 条形成 checksum archive，2 条在 `ProductEvidenceRecorder.capture` 前失败。预声明入口错误门槛为 `0`，第二条未归档失败出现后该门槛已不可逆，因此停止剩余 14 条以避免无效 Provider 成本。
- 4 条可复核 archive 的耗时为 `135.904477–296.736085s`，均为 8 个模型决策轮后 runtime budget limitation；总计 `32` 个模型决策轮、`38` 次模型调用、`213,643` token。两条子级 `completed` 样本分别返回 `5,905` 与 `5,758` 字符 Artifact，但仍未交付；两条子级 timeout 样本没有成功 Artifact。
- 两条已封存的 completed 路径都在 answer-only 后立即收到 `working_plan_incomplete`：现有 `_decide_answer_only` 只投影 Plan goal，没有投影 canonical pending step IDs；模型无法在 `FinalMessage.resolved_plan_step_ids` 中给出 Admission 要求的精确集合。运行随后重新进入开放 Proposal，继续出现 `agent_artifact_already_returned`、`invalid_arguments`、Plan binding/immutable feedback，最终耗尽预算。这证明“只收窄输出类型”不足，不能保留。
- 第二个本地候选曾同时把 pending IDs 只读投影给 answer-only；契约测试证明模型显式回传正确 IDs 时现有 Admission 可以完成 Plan，Application 没有自动宣布完成。但针对原 completed 失败样本的真实 pilot 首条在 `21.490859s` 被 InteractionIntent 误判为 `background-continuation`，产生 `capability_missing`，`agent_calls=0`；证据位于 `data/e2e_traces/product_agent_perf_delegate_finalization_plan_contract_pilot_20260827/agent-perf-001-delegate/target/`。预声明 `2/2` 晋级条件已不可达到，pilot 未消费候选，不能证明真实交付，候选同样撤回。
- 两轮候选的 `answer_only_pending` 消费点、pending-ID prompt 投影和专用测试改动均已删除；未保留 flag、fallback、双轨入口或自动 Plan 完成。由于 target 已违反退出条件，不执行高成本消融，也不声称修复、上线或用户结果改善。

### 4.4 `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` 已否决实验

同一正式用户输入明确要求“委托一个独立的外部研究助手，再由你核验并给出本次响应中的结论”，没有要求响应结束后继续、稍后查询、暂停、恢复或调整。只读 Provider 诊断在四主题轮转中得到 `1/20` admitted background，同一 repetition 16 原文重复得到 `3/20`；报告与 checksum 位于 `data/e2e_traces/provider_diagnostics/interaction-intent-delegation-boundary-001/20260827/` 与 `20260827-repeat-16/`。正式 `POST /api/conversation/turn` baseline 在 A2A、Tool、Agent 执行预算为 0 的可解释环境中得到 `15/20` 前台边界保持、`5/20` 错误的 `background-continuation capability_missing`，入口错误 `0`、Agent/Tool 执行 `0`、35 次模型调用、`88,672` token、P95 `29.542s`；20 份 archive checksum 错误为 `0`，证据根为 `data/e2e_traces/product_interaction_intent_delegation_boundary_20260827/interaction-intent-delegation-boundary-001/baseline/`。

External Mechanism Comparison（核对日期 2026-08-27，A 级）：

| 实现 | 可复核契约 | 本工程采纳 / 拒绝 |
| --- | --- | --- |
| OpenAI Agents SDK [Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/) 与官方 Responses [create contract](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) | agents-as-tools 由 manager 保留当前对话和最终答案，handoff 只转移当前 turn 的控制；真正后台执行由独立的 typed `background` boolean 显式选择 | 采纳“当前 run 内委托”和“后台生命周期”是不同契约；不移植 Runner、handoff 或要求新增 UI flag |
| DeepSeek Harness [`SubagentStartRequest` / continuable child](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/subagent.md#the-one-shot-start-request) | one-shot `start` 等待 `SubagentResult`；continuable background child 使用独立持久 Session、Activation、inbox 和 `startContinuable`，不是从普通“独立子 Agent”措辞隐式升级 | 采纳 one-shot 与 continuable 的结构性分界；不引入 Session、Activation、inbox、control tool 或后台能力 |

Complexity Justification：

1. 唯一失败阶段是 `InteractionIntentProposal -> admit_interaction_intent`：模型把“独立的外部研究助手”或整条消息当成一个可见 span，当前 Admission 只能证明 span 在原文，不能证明“响应后继续”与“未来再交互”两个必要谓词都存在。
2. 唯一变量为 background proposal 的证据 contract：破坏式删除单一 `background_source_span`，替换为 `background_after_response_source_span` 与 `background_later_interaction_source_span`。模型仍拥有两个开放语义判断；Admission 只机械验证 true 时两项非空、互不相同、均来自最新用户消息，false 时两项都为空。
3. 复用现有 `InteractionIntentProposal`、一次 revision、`AdmittedInteractionIntent` 和 `background-continuation capability_missing` 写入口；不新增 Model、模型调用、状态、表、Agent、Tool、Workflow、Router、关键词规则或第二写入口。Requirements 和 interaction phase 在 revision 中继续冻结。
4. 拒绝关键词/正则判断“后台”“独立”“稍后”，因为开放世界语义属于模型；拒绝每次都增加一次确认模型调用；拒绝把无法确认的 background 静默改写成成功。候选只提高 Proposal evidence 的可分解性和 Admission 的机械证据精度。
5. 正向控制复用 `BACKGROUND-CONTINUATION-LIMITATION-001` 的 20 条明确请求：它们分别包含“首次请求返回后独立推进”和“稍后查询领取报告”，必须继续 `20/20` 类型化 limitation 且零执行。

预声明 target：

| 指标 | baseline | target 门槛 |
| --- | ---: | ---: |
| 前台委托边界保持 | `15/20` | `20/20` |
| false-background | `5/20` | `0/20` |
| 入口错误 | `0` | `0` |
| Agent / Tool 执行 | `0 / 0` | `0 / 0` |
| 模型调用 | `35` | `<=45` |
| 总 token | `88,672` | `<=115,000` |
| P95 用户可见延迟 | `29.542s` | `<=45s` |
| 明确后台正向控制 | `20/20 limitation`、零执行 | `20/20 limitation`、`20/20 capability_missing`、零执行 |

target 达标后，在独立 patch/worktree 中只恢复单一 span schema、Prompt 和 Admission consumer 执行同输入 ablation；ablation 必须重新出现至少 `3/20` false-background，且 target/ablation 的输入、身份、初始事实、Provider、grader 一致。任一 target 门槛失败则删除双 span 字段、消费点和专用测试，不追加关键词、重试或模型确认。

执行结果（2026-08-27）：

- 候选破坏式替换为两个证据 span 后，InteractionIntent/明确后台 limitation 契约测试通过，完整 Conversation/StructuredModel 回归为 `130 passed`。没有新增模型调用路径、关键词规则、状态或第二写入口。
- 同输入正式 target 证据根为 `data/e2e_traces/product_interaction_intent_delegation_boundary_20260827/interaction-intent-delegation-boundary-001/target/`。前 8 条均保持前台边界、false-background `0/8`、入口错误 `0`、Agent/Tool 执行 `0`；共 16 次模型调用、8 个模型决策轮、`46,005` token，8 份 archive checksum 错误 `0`。
- 第 6、8 条分别约 `50.12s`、`59.11s`，使 20 样本 nearest-rank P95 的 `<=45s` 门槛在第 8 条时不可逆失败；partial target P95 为 `59.111s`。因此停止剩余 12 条，未运行显式后台正向控制和消融，不能声称完整 target、因果证明或可上线。
- 双 span schema、Prompt、Admission consumer 与专用测试改动已全部删除，恢复单一 `background_source_span`；未保留 alias、compatibility field、flag、fallback 或双轨入口。语义改善只能作为未来候选证据，不能覆盖预声明成本退出条件。
- 删除候选后又以相同正式入口、输入、身份和原单 span 代码状态执行独立重复 baseline：`20/20` 前台边界保持、false-background `0/20`、40 次模型调用、20 个模型决策轮、`113,034` token、P95 `32.356s`、最大 `37.684s`，20 份 archive checksum 错误 `0`；证据根为 `data/e2e_traces/iidb_repeat_20260827/interaction-intent-delegation-boundary-001/baseline/`。首次因 Windows 绝对路径 263 字符导致 evidence `.tmp` 写入失败的运行只留下 manifest，不计样本。该重复证明语义错误与延迟均有 Provider 方差，不能追溯放宽已经失败的双 span 门槛。

### 4.5 `INTERACTION-INTENT-DELEGATION-CONTRAST-001` 已否决实验

该候选复用 4.4 的产品失败、A 级比较和单一 owner，不重建 schema。当前 `_DERIVATION_INSTRUCTION` 已用抽象定义说明 background 必须同时包含“响应后继续”和“未来再交互”，但真实模型仍以 `5/40` 的正式入口频率把“独立 specialist 在当前响应内返回结果”纳入 background；相同输入另有只读诊断 `4/40`。第二批 baseline 的 0/20 不否定第一批失败，只证明 target/ablation 必须处理方差。

Complexity Justification：

1. 唯一变量是在现有 `interaction_intent:v2` system instruction 中增加两个机制级反事实示例：`delegate an independent specialist and synthesize in this response -> false`；`continue after this response and let me query/pause/resume/steer later -> true with an exact span`。
2. 示例不包含四个测试主题、marker、具体中文短语或 grader 字段，不新增关键词/正则分支；模型仍拥有开放语义判断，Admission 仍只验证原单 span 的来源与 phase 不变量。
3. 不新增/修改 Model、字段、模型调用、状态、表、Agent、Tool、Workflow、预算或 Completion；删除示例即可完整消融。相比双 span 候选，它没有结构迁移和 revision 触发面。
4. OpenAI Agents SDK 与 DeepSeek Harness 的 A 级契约均明确区分当前 run/one-shot delegation 与显式 background/continuable lifecycle；示例只把这一已核对机制边界提供给现有 semantic owner，不复制外部对象。
5. target 只证明用户没有收到错误后台理由；它不证明 Agent 委托或研究交付改善。显式后台正向控制仍必须保持 fail closed。

预声明 target：

| 指标 | 两批 baseline | target 门槛 |
| --- | ---: | ---: |
| 前台委托边界保持 | `35/40` | `20/20` |
| false-background | `5/40` | `0/20` |
| 入口错误 | `0/40` | `0/20` |
| Agent / Tool 执行 | `0 / 0` | `0 / 0` |
| 模型调用 | `75/40` | `<=42/20` |
| target 总 token | 不直接按两批相加比较 | `<=120,000` |
| target P95 / 最大延迟 | `29.542s / 32.356s` P95；重复最大 `37.684s` | `<=45s / <=60s` |
| 明确后台正向控制 | `20/20 limitation`、零执行 | `20/20 limitation`、`20/20 capability_missing`、零执行 |

target 全部门槛达标后，在独立 patch/worktree 中只删除两个对比示例并执行同输入 20 样本 ablation；ablation 必须 false-background `>=2/20`，入口错误 `0`。若 target 或显式后台正向控制失败，或者 ablation 未复现，立即删除示例与专用测试，不重投同一候选。

执行结果（2026-08-27）：

- 候选只增加两个通用英文反事实句，InteractionIntent/后台 limitation 契约测试与完整 Conversation/StructuredModel 回归通过；没有字段、模型调用或生产 consumer 变化。
- 同输入 target 证据根为 `data/e2e_traces/iidc_20260827/interaction-intent-delegation-boundary-001/target/`。前 18 条全部保持前台边界、false-background `0/18`、入口错误 `0`、Agent/Tool 执行 `0`；共 36 次模型调用、18 个模型决策轮、`103,346` token，18 份 archive checksum 错误 `0`。
- 第 11、18 条分别约 `52.54s`、`51.53s`，使 P95 `<=45s` 在第 18 条不可逆失败；partial target P95/最大均为 `52.539s`。因此停止最后两条，未执行显式后台正向控制和 ablation，不能声称完整 target 或因果证明。
- 两个对比句与专用 Prompt 断言已删除，恢复原 `_DERIVATION_INSTRUCTION`；没有保留 flag、fallback 或双轨 Prompt。两轮不同候选均得到 0 semantic failure 的 partial target，却都被两个 Provider 长尾否决；这不允许追溯放宽门槛，只准入未来的同时 control/target 或时间交错测量设计。

同时间窗 Provider Conformance（不是产品 target）：

- 新增只读诊断 `evals/provider_diagnostics/interaction_intent_contrast_interleaved_001.py`，固定同一自然输入、Provider、模型、typed output、temperature、max tokens 和请求 metadata；奇数组按 control→contrast、偶数组按 contrast→control，唯一主动变量为 system instruction 的两个对比句。回归测试机械约束两臂固定字段。
- 第一份探索报告位于 `data/e2e_traces/provider_diagnostics/interaction-intent-contrast-interleaved-001/20260827/`，20 对完整、checksum 有效、Provider error `0`，但两臂使用了不同的追踪 purpose/arm metadata；因此只记为非准入探索证据。其 control/contrast false-background 为 `3/20`、`0/20`，P95 为 `11.980s`、`21.812s`。
- 修正后的严格 v2 报告位于 `data/e2e_traces/provider_diagnostics/interaction-intent-contrast-interleaved-001/20260827-v2/`：20 对完整、40 个样本、checksum 有效、Provider error `0`。control/contrast false-background 为 `1/20`、`0/20`；总 token 为 `14,745`、`16,513`；P95 为 `19.354s`、`21.812s`，最大为 `20.082s`、`23.145s`；contrast-control 组内延迟差范围 `-16.083s` 到 `16.237s`，P95 `16.184s`。
- 该结果证明交错协议可观测同时间窗漂移，却没有建立可准入的 Prompt 收益：语义侧只有一个不一致 pair，成本侧 contrast 多 `1,768` token 且尾延迟更高；直接调用也不包含正式 HTTP、第二次 intent/limitation 调用和完整产品链。已撤回候选保持删除，不运行新的产品 target、正向控制或消融。

### 4.6 `AGENT-ARTIFACT-PLAN-FINALIZATION-CONFORMANCE-001` 未过准入门槛

该诊断只回答“现有 FinalMessage 与 Plan Admission 契约能否在成功 AgentArtifact 后稳定表达父级收口”，不证明用户结果，也不改变生产行为：

1. 输入只选自当前正式委托 baseline 中 checksum 有效、`delivered=false` 且已产生 succeeded `AgentArtifact` 的 7 份冻结归档；6 份仍有 pending Plan，1 份 Plan 已 terminal 但回答缺权威来源。每份 Artifact excerpt 至少含一个 URL。
2. 调用复用生产 `interaction_completion_answer:v1`、现有 `FinalMessage` schema 和现有 `_decide_answer_only` 输入物化；pending Plan 只追加生产已有的 `working_plan_incomplete` typed `DecisionFeedback`，其中明确列出必须由模型回传的 pending IDs。诊断不自动填 ID、不执行 Agent/Tool、不写 journal 或业务状态。
3. 预声明 Conformance gate 为：7/7 Provider 成功、7/7 模型显式回传精确 pending ID 集合并经 `admit_final_plan_resolution` 接受、6/6 pending 样本的空 ID 负控制被拒绝。marker 与已观察 URL 只作附加语义画像，不能把 Conformance 升格为产品 target。

External Mechanism Comparison（核对日期 2026-08-27，A 级）：

| 实现与固定坐标 | 可复核契约 | 本工程结论 |
| --- | --- | --- |
| OpenAI Agents Python [`run.py` / agent loop](https://github.com/openai/openai-agents-python/blob/10cdae4a3c30a29c6e96c8ec14e6bf1c5f02940e/src/agents/run.py) 与 [`running_agents.md`](https://github.com/openai/openai-agents-python/blob/10cdae4a3c30a29c6e96c8ec14e6bf1c5f02940e/docs/running_agents.md) | 模型产生目标 `output_type` 且没有 ToolCall 时，Runner 把它作为 `final_output` 终止；否则执行 Tool/Handoff 后继续。它不要求最终答案复制内部 Plan/Todo IDs | 只支持“父级仍需产生 final output”；该 Runner 没有本工程 canonical WorkingPlan 结果义务，不能据此删除 Completion Gate 或把 Tool/Agent success 当用户完成 |
| Gemini CLI [`write-todos.ts`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/write-todos.ts) | `write_todos` 完整覆盖 Todo 列表，逐项状态为 `pending/in_progress/completed/cancelled/blocked`，确定性校验至多一个 `in_progress`，然后把当前列表返回模型 | Todo 是模型规划辅助状态；源码没有把 Todo 完成等同于用户结果，也没有独立 Verifier/Completion 契约。不能照搬“完整覆盖”替代本工程 Plan 事实 owner |
| Hermes Agent [`todo_tool.py`](https://github.com/NousResearch/hermes-agent/blob/5d4ad23b0dc1412fea1f6592160ab4e8d154269c/tools/todo_tool.py) | `merge=false` 完整替换、`merge=true` 按 ID 更新；状态为 `pending/in_progress/completed/cancelled`，完整列表会在压缩后重注入，定位是 planning aid | 同样没有用户结果 Completion Gate；按 ID 更新能说明计划生命周期，不证明最终回答可以忽略 pending 义务 |
| DeepSeek Harness [`SubagentResult`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/subsystems/subagent.md#the-one-shot-start-request) | one-shot 子级把终态 `output` 与可选 `structured` 返回父级；非 completed 结果不得包装成成功 | 支持父级消费边界，不拥有父级 Plan 或用户 Completion；不能解决模型在父级开放 Proposal 中不进入 FinalMessage 的当前最早失败 |

四项 A 级实现没有两个与本工程“canonical Plan 义务 + FinalMessage 语义完成 + Completion Gate”语义等价的现成机制。它们共同否定“子级 success 自动完成父级”，也没有支持把 `resolved_plan_step_ids` 简化为 bool、删除 Plan Gate 或让 runtime 代填。因此本轮不形成新的机制候选。

执行结果（2026-08-27）：

- 密封报告位于 `data/e2e_traces/provider_diagnostics/agent-artifact-plan-finalization-conformance-001/20260827/`；7 个样本、7 次真实模型调用、Provider error `0`，共 `20,265` token，checksum 有效。
- 现有 Admission 接受 `5/7`，但逐条复核 raw `resolved_plan_step_ids` 后只有 `4/7` 精确匹配：样本 7 漏掉一个 pending ID，样本 20 同时回传 completed 与 pending ID；terminal 样本 18 回传了多余 completed ID，当前 Admission 因已无 pending step 而忽略并接受。6/6 pending 空 ID 负控制均被拒绝。
- 附加用户结果信号为 marker `6/7`、Artifact 中已观察 URL `5/7`。样本 6 的回答被截断且缺 marker/URL；因此即使只看内容也没有达到稳定父级交付。
- 诊断 gate 失败，已撤回的 answer-only 生产候选不得复活。诊断实现 revision v2 已把“函数未拒绝”与“ID 精确合法”分开，并新增 terminal 非法 ID 负控制；它暴露当前 Admission 会忽略 terminal Plan 的多余 ID，但这尚未形成用户可观察失败，禁止据此直接修改生产 Admission。
- 对 7 份原正式失败 trace 的追加只读归因显示 `working_plan_incomplete=0/7`：生产开放循环中模型根本没有进入 FinalMessage，主要反馈为 `invalid_arguments`、Plan binding/immutable、duplicate action 和重复委托。ID 表达只在已撤回的强制 answer-only 候选后成为下一失败；因此把 tuple 改成 bool 或动态 enum schema 不是当前生产最早失败阶段，按单变量规则退出。

### 4.7 `EVAL-FEEDBACK-LATENCY-001` 工程优化已落地

该项是评测控制面重构，不是 Application Capability 或 Runtime Mechanism 变更，用户行为保持不变。工程 baseline 位于 `data/e2e_traces/provider_diagnostics/eval-feedback-latency-001/baseline/`：InteractionIntent 两组 partial target 分别耗时 `252.095s` 和 `547.733s`，需要人工判断第 8、18 个样本已经使 20 样本 P95 门槛不可达到，且没有机器可读 cohort 决策；AgentArtifact 组还出现两次 `ProductEvidenceRecorder.capture` 前失败，只留 stdout，证明当前证据边界不能推断未封存事实。

Complexity Justification 与最小边界：

1. 唯一工程约束是“已封存样本能够机械证明门槛不可达到，但 runner 仍不知道应停止”；不修改 Prompt、Provider、正式入口、grader、产品状态或生产 Composition Root。
2. `PromotionGateSpec` 单一拥有预声明样本数、stage 和 typed constraints；`ProductEvidenceRecorder` 仍是单样本 ProductEvidence 唯一写入口；`PromotionGateController` 只消费 checksum 有效的只读事实并拥有本次进程内 cohort 决策；`TraceArchive` 封存独立的 `evaluation_promotion_decision_not_product_e2e` 报告。
3. 支持的确定性门槛只有当前已证明需要的 minimum/maximum count、maximum sum、nearest-rank percentile 上限和 conditional rate 下限。早停只允许 `rejected`；`passed` 必须收齐 `expected_samples`。错误 cohort、重复样本、缺指标、不同代码/config/grader/entrypoint 或坏 checksum 全部 fail closed。
4. pytest 插件在原 `ProductEvidenceRecorder.finalize` 之后观察 archive；不开启 `--product-promotion-spec` 时保持旧封存路径。它只应运行一个专用 cohort，不能借 cohort 通过覆盖其他 pytest 失败，也不能与 `--maxfail` 拼成第二套门禁。

External Mechanism Comparison（核对日期 2026-08-27，A 级）：

| 实现与坐标 | 可复核契约 | 本工程采纳 / 缺口 |
| --- | --- | --- |
| pytest stable [Test Execution Control](https://docs.pytest.org/en/stable/reference/reference.html#test-execution-control) 与 [Exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html) | `-x/--maxfail` 在第一个或第 N 个测试失败后停止，退出码区分 tests failed、interrupted、internal error 和 usage error | 采纳 pytest 生命周期内早停和不掩盖原始错误码；普通 `--maxfail` 不理解“最终 P95 已不可达到”等 cohort 约束，不能直接复用 |
| OpenAI Evals API [Evals](https://platform.openai.com/docs/api-reference/evals) | eval definition 分离 `data_source_config` 与 `testing_criteria`，run 以固定 data source 和 model configuration 执行 | 采纳“数据身份、评测条件、运行结果分离”；官方契约没有给出与本工程相同的逐样本不可逆 aggregate 早停语义，因此不声称存在两个语义等价实现，也不移植远端 Eval 对象 |

执行 target 位于 `data/e2e_traces/provider_diagnostics/eval-feedback-latency-001/target/`：

- 对原 8 样本组回放，在第 `8/20` 个样本以 `p95-latency-ceiling` 自动拒绝，与人工结论一致；若当时在线启用，可避免余下 12 个无晋级价值样本。
- 对原 18 样本组回放，在第 `18/20` 个样本自动拒绝，与人工结论一致；可避免余下 2 个样本。最终实现的两次回放分别约 `1.526s`、`1.571s`，26/26 源 archive 与 2/2 决策 archive checksum 有效，false promotion 为 0。
- 历史回放只证明决策等价和可避免的样本数，不伪称已经回收历史 Provider 时间。证据/发布链回归 `30 passed`；正式 `POST /api/conversation/turn` 后台能力边界 E2E 为 `1 passed in 158.64s`，新 archive checksum 有效。
- 本阶段遗留的 capture 前失败已由下节的 enrollment 处理；第一阶段历史决策 archive 保持不变，不追写或补造原来 stdout-only 的两个样本。

### 4.8 `EVAL-EVIDENCE-ENROLLMENT-001` 已实现但未过正式行为门禁

工程 baseline 与 target 分别位于 `data/e2e_traces/provider_diagnostics/eval-evidence-enrollment-001/baseline/` 和 `target/`。历史 `AGENT-PERF-001-DELEGATE` partial target 尝试 6 条，只有 4 条形成 checksum archive；另外 2 条在 `_turn`/结果物化期间失败，虽然“零 entry failure”已经不可达到，机器可观察失败数仍是 0。代码审计还显示变更前 25 个 Product Baseline 文件只在测试末尾一次性 `capture`，但没有证据支持机械迁移全部文件。

最小契约与事实 owner：

1. `ProductEvidenceRecorder.enroll` 在昂贵操作前一次性冻结 `nodeid + ProductEvidenceIdentity`；`capture_report` 只附加本样本的产品结果。原 `capture` 保留为两步操作的同进程便利入口，不形成第二事实 owner。
2. 测试进入 call phase且已 enrollment 后，如果异常阻止结果报告形成，finalize 写入 typed `ProductEvidenceCaptureFailure(state=enrolled_without_result_report)`，并保留真实 pytest outcome、duration 和 detail。它证明“该正式样本已进入但没有结果报告”，不猜测用户结果或 grader 指标。
3. promotion metric 新增 `result_report_missing` 与 `test_failed`；前者来自封存协议事实，后者来自 pytest 执行事实，不从自然语言、stdout 或缺省值推导。通过但遗漏 result report 的测试被强制改为失败；坏 checksum、fallback report 与 pytest outcome 不一致继续 fail closed。
4. 只迁移已有真实缺口的 `AGENT-PERF-001-DELEGATE`：identity 在 `POST /api/conversation/turn` 前冻结，20 个测试项与 `agent_delegate_target_001.json` 的 `expected_samples=20` 机械一致。其余 24 个 one-shot 用例没有已执行 pre-capture 失败 baseline，保持原状。

External Mechanism Comparison（核对日期 2026-08-27，A 级）：

| 实现与坐标 | 可复核契约 | 本工程采纳 / 缺口 |
| --- | --- | --- |
| pytest stable [`pytest_runtest_protocol` / `pytest_runtest_makereport`](https://docs.pytest.org/en/stable/reference/reference.html#pytest.hookspec.pytest_runtest_makereport) | 每个 item 明确经历 setup、call、teardown，并为各阶段产生 `TestReport`；call 异常仍有正式 outcome | 采纳 call report 作为执行事实和 finalize 时点；场景 identity 仍必须由测试在昂贵调用前显式 enrollment，hook 不猜测业务身份 |
| OpenAI Evals API [Eval run output item](https://platform.openai.com/docs/api-reference/evals) | output item 关联 datasource item、sample、status 和逐 grader results，失败 output item 可独立过滤 | 采纳“输入身份、执行状态、grader 结果分离”；远端契约不等价于本地调用前 enrollment，也没有证明可以为无 sample 的失败补造 grader 结果 |

执行结果：

- 故障注入证明 enrollment 后异常可形成 checksum archive，`result_report_missing=true` 并在 `1/1` 自动拒绝；pytest 集成场景在第 `2/3` 条异常后拒绝并停止第 3 条。
- “测试函数返回成功但忘记 `capture_report`”被转换为 pytest failed，不能产生伪通过；legacy `capture` 继续封存，相关证据/发布链回归为 `32 passed`，Ruff 通过。
- 正式 `POST /api/conversation/turn` 行为回归未通过：archive `data/e2e_traces/product_baselines/background-continuation-limitation-001/target/20260827T093207.005031Z-4308-278e6f7b` checksum 有效，但只有 `19/20` limitation、`19/20` capability_missing 和 `19/20` no-execution；`tool-governance-comparison` 第 1 次重复误入 `plan_ready`/执行路径。该变更不触及 `src/` 或生产 Composition Root，但未通过的正式门禁仍然成立，当前不得标记 behavior-verified 或 release-ready。
- 当前剩余盲区是 test body 之前的 fixture/setup failure：此时没有合法场景 identity，仍不得从 nodeid 或 stdout 补造 ProductEvidence。只有新的工程 baseline 证明它成为主要阻塞时才继续扩展协议。

### 4.9 `EVAL-COHORT-GRANULARITY-001` 逐样本正式早停已验证

工程 baseline/target 位于 `data/e2e_traces/provider_diagnostics/eval-cohort-granularity-001/`。上一版后台能力 E2E 只有一个 pytest item，在内部顺序调用 20 个正式 HTTP 请求，最后才写一个聚合 archive。2026-08-27 的失败运行在第 16 条已经违反零容忍门槛，却继续执行第 17–20 条，额外消耗 `19.935167s` 样本时间，整次运行为 `159.01s`；逐样本 promotion plugin 无法在内部循环边界介入。

破坏式替换保持四类自然请求 × 五次重复、同一正式入口、真实模型、PostgreSQL 和 typed 用户结果断言，但改变评测证据粒度：

1. 每个参数化 item 在请求前 enrollment，只执行一次 `POST /api/conversation/turn`，只拥有一个 scenario/repetition identity、一个 grader report 和一个 checksum archive。
2. grader 升级为 `background-continuation-limitation-001-v2-per-sample`；旧 v1 聚合 archive 继续作为 ADR 0015 的不可变历史证据，不与 v2 cohort 合并，也不保留第二个可执行入口。
3. `background_continuation_target_002.json` 预声明 20 个样本，对缺失报告、pytest failed 和后台执行均为零容忍。任何一项出现即可不可逆拒绝；通过仍必须收齐 20/20。

真实 target 结果：

- 收集 20 项；第 1 条通过并独立封存，第 2 条返回非 limitation 且开始执行，pytest 与 `zero-background-execution` 同时失败。
- promotion report 在第 `2/20` 条拒绝，剩余 18 条未执行；结果为 `1 failed, 1 passed in 53.96s`。两个 ProductEvidence archive 和 promotion archive checksum 全部有效。
- 门禁直接造成“剩余 18 条未执行”；不能把 `159.01s -> 53.96s` 全部解释为优化收益，因为随机产品失败位置从 baseline 第 16 条移动到 target 第 2 条。因果指标只记录避免样本数，墙钟只作观测。
- 工程优化 target 通过，产品 target 被正确拒绝。当前 background-continuation 分类比上一轮 `19/20` 仍不稳定，但单个新运行不能追溯修改生产 Prompt/schema；继续遵守本文件 4.5 的重新准入门槛。

## 5. 下一轮诊断顺序

下列项目都是诊断或 baseline 工作，**不是活动实现候选**：

1. `CONVERSATION-RESEARCH-DELIVERY-001` 的局部参数候选已撤回。后续只有一个候选能同时解释当前生产的参数不可表达、候选开启后的预算耗尽和结果未收敛，并完成新的 A 级机制核对与预声明 target 时，才可重开；DeepSeek Harness 的后台 `Session`、消息箱或 `Compaction` 仍不能解释该失败。
2. `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` 已完成只读诊断、两批正式 baseline、两个失败 target 和严格交错 Provider Conformance。control/contrast 只有 `1/20` 对 `0/20` 的弱语义差，而 contrast token 与 P95 更高；因此关闭当前双 span 与对比示例方向，不把 Conformance 冒充产品 target，也不事后放宽本轮绝对 `45s` 门槛。只有新的正式入口自然输入 cohort 在当前代码重复达到预声明错误门槛，才允许以新的 Complexity Justification 重开。
3. 父级收口 Runtime Conformance 已完成但失败：现有 Admission `5/7` 接受，严格 ID 契约仅 `4/7`，marker `6/7`、已观察 URL `5/7`；原正式失败 trace 还是 `working_plan_incomplete=0/7`，说明 ID 不是生产最早失败。OpenAI Agents、Gemini CLI、Hermes 与 DeepSeek Harness 的固定提交源码也没有两个语义等价的 canonical Plan Completion 实现。因此不进入产品 candidate/target；不以 runtime 自动填 ID、把 Agent success 当 Completion、放宽 Plan Admission或追加 Prompt 提醒修补结果。
4. `RUNTIME-SESSION-LOG-DIAGNOSTIC` 已完成并退出当前优化队列：写放大 P95 `7.285x`，但新实例恢复 P95 不超过 `1.113 ms`、重建不一致 `0/20`，没有成立的工程约束。
5. `CONTEXT-PRESSURE-BASELINE` 在同批 157 个真实回合中未复现溢出或错误截断，当前退出 `Compaction` 方向。
6. 只有独立自然用户样本证明“首个响应后仍需继续、可查询、可 `steer` 或 `cancel` 并最终交付”时，才开启 `BACKGROUND-CONTINUATION-DEMAND-BASELINE`。当前类型化 `capability_missing` 是诚实边界，不是该新能力的失败 baseline；显式前台委托不得计入该需求。

显式委托或其他诊断进入机制候选前，仍必须新增各自的 `Complexity Justification`，声明唯一变量、删除对象、退出条件和同输入 target；不得借用普通研究参数候选的证据。

## 6. 已关闭决策

### 6.1 调查项目撤回

- 决策与完整证据：[ADR 0015](../adr/0015-withdraw-investigation-project.md)；
- 机制开启 baseline：`data/e2e_traces/product_baselines/background-continuation-limitation-001/baseline/20260826T113052.621892Z-30036-eb7f45c0`；
- 删除后 target：`data/e2e_traces/product_baselines/background-continuation-limitation-001/target/20260826T111202.670374Z-2720-e3611907`；
- 配对结果：用例、输入、主体、入口、初始状态和评测器一致，代码状态不同，校验和有效；
- 当前产品边界：普通研究留在 `Conversation`；明确后台持续请求返回类型化 `capability_missing`；不保留 `Project`、通用 `Task` 或第二套研究循环。

## 7. 未准入问题的共同约束

后续研究质量或委托质量优化必须依次满足：

1. 用当前正式入口和自然输入复现用户缺失结果，冻结服务提供方、模型、预算和评测器；
2. 从追踪记录、`AgentRun`、`Artifact` 和服务提供方事实中定位唯一失败阶段，不能用 HTTP 200、调用次数或对象存在代替；
3. 按机制域核对至少两个独立 A 级实现，外部实现只回答“机制怎么做”；
4. 优先修复一个现有责任主体或消费点，不新增第二循环、镜像事实、通用 `Planner` 或持久 `Task`；
5. 使用同输入机制关闭 baseline、最小 target 和机械配对证明因果；
6. target 未改善预声明用户指标时撤回候选，并删除临时代码和测试资产。

普通 `Conversation` 当前仍为 `0/20 delivered`，不能因 `Project` 已删除而宣称研究恢复；显式委托当前正式 baseline 只有 `2/20 delivered`，也不能因 `AgentGateway` 可达或 9 个子任务完成而宣称委托交付。两项进入实现前必须各自提交新的 `Complexity Justification`。
