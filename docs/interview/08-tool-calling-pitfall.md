# 开发踩坑复盘：统一结构化 Proposal 阻塞工具调用

> **这次最关键的坑不是模型偶尔输出了坏 JSON，而是旧模型契约把工具选择、动态参数、工作清单、子智能体委托和最终回答压进了同一个结构化 Proposal。** 当前代码已经用逐动作原生 Tool Calling 替换旧参数传输，并关闭 `L01` 的重复个人检索；最新 G2 证明剩余阻塞已经迁移到普通 Conversation 的语义路由、工作清单时机与 Completion 收口。

## 1. 面试时先给结论

**我在开发中遇到的最大阻塞，是曾经把“结构化输出”误当成了“原生工具调用”。** 旧系统虽然要求模型返回合法 JSON，却没有在普通 Conversation 决策中向服务提供方发送逐工具 Schema。它把完整工具目录写进提示词，再让模型生成一个通用 `AgentTurnDecision`；外层 JSON 可以解析，内部参数和生命周期仍会连续被 Admission 拒绝。

这个问题最初很像模型能力不足，因为 MiMo 和 DeepSeek 会在不同阶段失败。代码和追踪记录最终把问题拆成了三层：服务提供方是否遵守传输协议、输出是否满足类型结构、Proposal 是否满足业务不变量。逐动作原生 Tool Calling 与成功后的阶段化能力投影让 `L01` 达到 `3/3`，但 G2 的混合证据请求仍会在直接 Web 搜索循环和 `gpt_researcher` 委托之间漂移。因此原生工具调用解决了参数协议问题，却不是研究交付的充分条件；继续把所有失败归咎于 JSON 会掩盖后续的委托、工作清单和 Completion 问题。

## 2. 失败现象暴露了两个独立阻塞

**历史 baseline 同时暴露了工具参数阻塞和研究交付阻塞，当前证据已经把两者分开。** 原 corrected-grader v3 baseline 在前两项均未交付后早停，并出现大量 `invalid_arguments`；当前 L01 不再出现参数错误。最新 `ASK-001B` 一次在三次成功 `web_search` 后耗尽预算，另一次成功委托 `gpt_researcher` 并生成带官方来源的答案，却没有走预期的直接 Web 路径且耗时 `143.09s`。详细样本和归档身份只在[当前端到端用例盘点](../evals/02-current-case-inventory.md)维护。

同日完整发布选择为 `0/9 passed`。模型调用阶段合计占 `977.402s / 1009.335s`，说明迭代时间主要消耗在重复模型回合，而不是本地断言。这个时间分布不能证明九项失败都来自工具调用，但它解释了为什么“模型生成 Proposal—Admission 拒绝—重新生成整个 Proposal”的循环会同时拖慢产品和开发反馈。

## 3. 根因不是一句“模型不能稳定输出 JSON”

**历史参数根因是模型可见协议与工具实际参数不一致；当前剩余根因是动作虽然合法，但选择与结束边界仍不稳定。** JSON 语法正确、Pydantic 外层解析通过、业务 Proposal 合法和用户目标完成是四个不同事实；只观察第一层会把架构问题误判成模型方差。

### 3.1 旧 Conversation 没有发送原生工具定义

**旧 Conversation 走统一结构化输出，没有向服务提供方发送原生工具定义。** 当前 `ConversationService` 已从 `EffectiveCapabilities` 物化逐动作 `ModelActionDefinition`，并用 `kind="tool_calling"` 发送精确 Schema。服务提供方返回原生动作后，`Adapter` 只负责解码，Admission 与执行网关继续拥有准入和执行事实。

`Capability Projection` 继续表达本轮可见性和治理事实，但不再替代逐工具参数 Schema。当前实现坐标是 [`StructuredModelRequest`](../../src/personal_agent/capabilities/contracts/model.py)、[`ConversationService._decide`](../../src/personal_agent/application/conversation/service.py)、[`model_actions.py`](../../src/personal_agent/application/conversation/model_actions.py)和 [`OpenAIModelClient._chat_kwargs`](../../src/personal_agent/infra/structured_model.py)。

### 3.2 通用 `arguments` 与严格 Schema 直接冲突

**旧 `ToolCallProposal.arguments` 允许任意字典，但严格化后的服务提供方 Schema 实际不允许任何参数键。** 该字段的类型是 `dict[str, Any]`，因此旧 Schema 没有预声明 `query`、`path` 或其他工具专属属性。`strictify_schema()` 又对所有对象设置 `additionalProperties=false`。旧 `arguments` 的有效形状相当于：

```json
{
  "type": "object",
  "additionalProperties": false
}
```

严格遵守旧 Schema 的模型只能生成空对象；Admission 又不能替模型补 `query` 或静默更换工具，所以缺参会重新进入模型循环。当前逐动作定义直接复用各工具 typed Schema，旧失败只作为历史诊断保留。

### 3.3 一个 Decision 同时承担了动作与生命周期

**参数修复还会被工作清单和完成状态放大。** `AgentTurnDecision` 要求模型在 `ContinueTurnProposal` 与 `FinalMessage` 之间选择；继续执行时又要同时决定工具或 Agent、参数、`plan_step_id`、可选工作清单以及是否等待用户。Admission 返回一个局部错误后，模型重新生成的是整个 Decision，而不是只修复某个工具的参数。

因此失败会在多个错误之间振荡：补上工作清单可能触发审阅边界，去掉工作清单又可能留下非法 `plan_step_id`；成功子智能体已经返回 Artifact 后，父级仍可能提出缺参读取或额外搜索；预算最终消耗在 Proposal 修复，而不是有效执行。稳定的治理原则本身没有错——Proposal 仍不能直接获得权限——问题在于模型侧的统一封装把原本应独立演进的语义绑在了一次生成中。

## 4. DeepSeek 与 MiMo 只是改变了失败阶段

**不同服务提供方暴露的是协议支持差异，不能归纳为某个模型“会 JSON”、另一个模型“不会 JSON”。** 历史 DeepSeek-compatible deployment 会接受 strict `json_schema` 请求却不实际执行 Schema，导致 Plan、Replan 或 Verifier 缺少 typed 字段。项目因此通过 [ADR 0007](../adr/0007-structured-output-transport-capability.md) 隔离 `json_object` 传输；该 target 证明 typed parse 可以通过，但没有产生最终用户报告，ADR 也明确不授权发布。

当前 MiMo 路径能够返回逐动作调用，但仍会在直接 Web 搜索、外部智能体委托、工作清单阶段和最终结果契约之间漂移。这个对比说明服务提供方会改变失败分布和吞吐，不能替系统证明产品交付。面试时应把以下问题逐层回答：

1. 服务提供方是否真正执行声明的传输协议；
2. 返回内容是否满足静态类型；
3. Proposal 是否满足当前业务状态与权限不变量；
4. 工具或 Agent 是否产生可信 `Observation`；
5. 用户要求是否通过 Verification 与 Completion。

## 5. 优秀智能体把模型决策和运行治理分开

**主流实现的共同点不是“更会写提示词”，而是让模型提出离散工具调用，让运行外壳拥有校验、权限、执行和结果回注。** 下列来源均为官方规范或固定提交源码，属于 A 级机制坐标；它们说明机制如何实现，不证明本工程采用后必然改善用户结果。

| 实现与坐标 | 可复核机制 | 对本次踩坑的启示 |
| --- | --- | --- |
| OpenAI [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) | 工具具有各自的参数定义；工具调用与文本是不同的输出项，并由 `tool_choice` 控制选择范围 | 不要求模型把所有工具参数写进一个通用自由字典 |
| Claude Code [工具参考](https://code.claude.com/docs/en/tools-reference)与[权限](https://code.claude.com/docs/en/permissions) | 模型面对离散内置工具或 MCP 工具；运行外壳按 deny、ask、allow 处理权限，[Hooks](https://code.claude.com/docs/en/hooks-guide)可以在调用前后确定性拦截 | 工具选择与权限判断不是同一个模型字段 |
| Gemini CLI 固定提交的 [`turn.ts`](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/core/turn.ts)与[策略引擎](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/docs/reference/policy-engine.md) | 模型返回 `FunctionCall(name, args)`；工具注册表查找名称，`tool.build(args)` 构建并校验调用，调度器再处理确认和执行 | 参数校验归具体工具，策略只决定允许、拒绝或询问用户 |
| OpenHands [Runtime](https://docs.openhands.dev/openhands/usage/architecture/runtime)与[安全指南](https://docs.openhands.dev/sdk/guides/security) | 运行系统把 `Action` 交给 `ActionExecutor`，并把结果作为 `Observation` 返回；确认策略与安全分析独立 | 执行事实不与模型的完成声明混装 |
| DeepSeek Harness 固定提交的 [Capability Seams](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/docs/capability-seams.md) | 工具注册与守卫执行、`Agent Loop`、审批、沙箱、`Plan Mode` 和子智能体具有独立接缝 | Plan、权限和子智能体不需要成为同一个工具 Proposal Schema |

这些实现共同支持下面的责任链：

```text
模型提出一个具体工具调用
  -> 具体工具 Schema 校验参数
  -> 策略和 Admission 判断本次是否获准
  -> 执行系统产生 Observation
  -> 模型消费 Observation 后继续或回答
  -> Verification 与 Completion 判断用户结果
```

OpenAI 的公开 API 可以作为机制坐标，但不能据此推断 Codex 未公开的内部实现。当前工程只采纳能够映射到本地失败阶段、并通过适用 baseline、target、回归或消融门禁的最小部分。

## 6. 最重要的处理不是继续打补丁，而是撤回失败候选

**一次有界修正仍未改善正式用户结果后，我们停止了提示词和 Schema 局部叠加。** 供应商原生工具传输候选在正式 target 中消除了 `invalid_arguments`，但只交付 `1/3`；随后只增加 `tool_name -> input_schema.required` 提示绑定的候选，在第一个样本仍出现 15 次 `invalid_arguments`。两个候选都已删除，没有保留生产开关、降级路径或双轨入口。

这次处理形成了三条工程纪律：

- 先用追踪记录定位最早失败阶段，再选择单一变量；工具参数、错误委托、工作清单和 Completion 不能混成一个“智能体优化”。
- target 没有改善预声明用户结果时撤回候选；参数错误减少只能证明参数阶段变化，不能冒充研究报告已经交付。
- 把长评测拆成逐样本正式用例，并由 promotion gate 在门槛不可达到时早停。当前研究 v3 baseline 在 `0/2 delivered` 后停止余下 18 项，缩短失败反馈但不改变产品结论。

当前 `TOOL-CALL-PROTOCOL-001` 已从[设计优化队列](../future/design-optimization-backlog.md)退出。窄范围混合证据请求的语义路由 target 已通过；`CONVERSATION-RESEARCH-DELIVERY-001` 回到 `A1`，因为广泛多来源研究仍没有冻结单一最早失败阶段。后续候选不得把已经关闭的参数协议或窄范围路由重新当成根因。

## 7. 如果面试官追问“最后怎样落地”

**已经落地的边界是让服务提供方产生带精确 Schema 的原生动作，`Adapter` 再把动作归一为内部 Proposal。** 运行系统继续拥有工具可见性、Admission、权限、预算、执行和 `Observation`；成功个人检索后，下一回合不再暴露同一读取动作。`L01` 的 `3/3` 只证明这个最小闭环，不能证明 Research 已经完成。

当前剩余问题是相同混合证据请求会选择不同执行路径：直接 Web 路径重复采集并耗尽预算，外部智能体路径可以交付答案但成本高且随后仍提出过晚工作清单。下一候选必须先冻结用户结果和允许的执行边界，再判断责任属于 `InteractionIntent`、能力选择还是 Completion；不能增加重试次数来掩盖问题。

## 8. 这次踩坑带来的判断

**可靠智能体的关键不是让模型一次输出更多结构，而是缩小每次模型决定的语义范围。** 类型化 Proposal、确定性 Admission 和执行治理仍然必要；真正需要收敛的是模型可见协议的职责数量。外层 JSON 可解析不等于工具可执行，工具可执行不等于研究完成，服务提供方差异也不等于架构结论。

稳定架构定义见[智能体运行外壳与关键能力 §1、§4](03-capability-axes.md)，最新结果数字和归档限制见[当前端到端用例盘点](../evals/02-current-case-inventory.md)，未解决问题与下一项允许动作见[设计优化队列](../future/design-optimization-backlog.md)，外部机制的完整分级入口见[工具执行与安全参考](../agentRef/tool-execution-and-safety.md)。
