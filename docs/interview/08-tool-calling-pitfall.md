# 开发踩坑复盘：统一结构化 Proposal 阻塞工具调用

> 本文保留统一 Proposal 与工具参数错位的历史复盘。现行动作、工作清单控制与最终提交已按 [ADR 0016](../adr/0016-separate-plan-control-from-action-execution.md)、[ADR 0017](../adr/0017-separate-action-selection-from-final-delivery.md)分开；研究 claim 主链见 [ADR 0032](../adr/0032-conversation-research-claims.md)。下文 G2、`L01` 和旧准入状态只对应当轮，最新问题与证据分别由 [Future](../future/design-optimization-backlog.md)和[评测盘点](../evals/02-current-case-inventory.md)维护。

## 1. 面试时先给结论

**这次历史阻塞来自把“结构化输出”误当成了“原生工具调用”。** 旧系统虽然要求模型返回合法 JSON，却没有在普通 Conversation 决策中向服务提供方发送逐工具 Schema。它把完整工具目录写进提示词，再让模型生成一个通用 `AgentTurnDecision`；外层 JSON 可以解析，内部参数和生命周期仍会连续被 Admission 拒绝。

这个问题最初很像模型能力不足，因为 MiMo 和 DeepSeek 会在不同阶段失败。代码和追踪记录最终把问题拆成了三层：服务提供方是否遵守传输协议、输出是否满足类型结构、Proposal 是否满足业务不变量。逐动作原生 Tool Calling 与成功后的阶段化能力投影让 `L01` 达到 `3/3`，但 G2 的混合证据请求仍会在直接 Web 搜索循环和 `gpt_researcher` 委托之间漂移。因此原生工具调用解决了参数协议问题，却不是研究交付的充分条件；继续把所有失败归咎于 JSON 会掩盖后续的委托、工作清单和 Completion 问题。

## 2. 失败现象暴露了两个独立阻塞

**当轮 baseline 的参数错误与后续研究未交付属于不同责任边界。** 旧评测早停时存在大量 `invalid_arguments`；逐动作工具候选改善了参数阶段，后续请求仍在搜索、委托和结束之间反复。工具调用合法不能代替研究目标完成。

当轮模型回合占主要耗时，只能说明失败反馈缓慢，不能证明全部失败来自参数协议。具体归档与后续分类由[评测盘点](../evals/02-current-case-inventory.md)拥有；旧发布选择和单次延迟不再作为今天的结果画像。

## 3. 根因不是一句“模型不能稳定输出 JSON”

**历史参数根因是模型可见协议与工具实际参数不一致；后续选择和结束问题需要各自的真实输入归因。** JSON 语法正确、Pydantic 外层解析通过、业务 Proposal 合法和用户目标完成是四个不同事实；只观察第一层会把架构问题误判成模型方差。

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

**参数修复还会被工作清单和完成状态放大。** 旧 `AgentTurnDecision` 要求模型在 `ContinueTurnProposal` 与 `FinalMessage` 之间选择；旧继续执行相位还同时决定工具或 Agent、参数、`plan_step_id`、可选工作清单以及是否等待用户。当时 Admission 返回一个局部错误后，模型重新生成的是整个 Decision，而不是只修复某个工具的参数。

因此失败会在多个错误之间振荡：补上工作清单可能触发审阅边界，去掉工作清单又可能留下非法 `plan_step_id`；成功子智能体已经返回 Artifact 后，父级仍可能提出缺参读取或额外搜索；预算最终消耗在 Proposal 修复，而不是有效执行。稳定的治理原则本身没有错——Proposal 仍不能直接获得权限——问题在于模型侧的统一封装把原本应独立演进的语义绑在了一次生成中。

## 4. DeepSeek 与 MiMo 只是改变了失败阶段

**不同服务提供方暴露的是协议支持差异，不能归纳为某个模型“会 JSON”、另一个模型“不会 JSON”。** 历史 DeepSeek-compatible deployment 会接受 strict `json_schema` 请求却不实际执行 Schema，导致 Plan、Replan 或 Verifier 缺少 typed 字段。项目因此通过 [ADR 0007](../adr/0007-structured-output-transport-capability.md) 隔离 `json_object` 传输；该 target 证明 typed parse 可以通过，但没有产生最终用户报告，ADR 也明确不授权发布。

当轮 MiMo 候选能够返回逐动作调用，仍有搜索、委托和结束选择失败。这个历史对比支持区分失败阶段，不能作为当前模型能力排序。分析依次核对：

1. 服务提供方是否真正执行声明的传输协议；
2. 返回内容是否满足静态类型；
3. Proposal 是否满足当前业务状态与权限不变量；
4. 工具或 Agent 是否产生可信 `Observation`；
5. 用户要求是否通过 Verification 与 Completion。

## 5. 外部机制只用于解释职责边界

**历史参考支持把具体调用参数与执行治理分开，但采用依据仍是本地参数反例。** 模型选择具体动作，逐工具 Schema 约束参数，Admission 与策略决定是否获准，执行系统返回实际结果，再由模型继续。外部 API 或固定源码不能证明本工程的研究结果改善，也不能用于推断未公开实现。

完整比较与来源等级由[工具执行与安全参考](../agentRef/tool-execution-and-safety.md)维护。本篇保留本地协议失败和取舍，现行职责由[工具专题](../topics/tools.md)与[Runtime](../topics/runtime.md)拥有。

## 6. 最重要的处理不是继续打补丁，而是撤回失败候选

**一次有界修正仍未改善正式用户结果后，我们停止了提示词和 Schema 局部叠加。** 供应商原生工具传输候选在正式 target 中消除了 `invalid_arguments`，但只交付 `1/3`；随后只增加 `tool_name -> input_schema.required` 提示绑定的候选，在第一个样本仍出现 15 次 `invalid_arguments`。两个候选都已删除，没有保留生产开关、降级路径或双轨入口。

这次处理形成了三条工程纪律：

- 先用追踪记录定位最早失败阶段，再选择单一变量；工具参数、错误委托、工作清单和 Completion 不能混成一个“智能体优化”。
- target 没有改善预声明用户结果时撤回候选；参数错误减少只能证明参数阶段变化，不能冒充研究报告已经交付。
- 把长评测拆成逐样本正式用例，并由 promotion gate 在门槛不可达到时早停。当轮研究 v3 baseline 在 `0/2 delivered` 后停止余下 18 项，缩短失败反馈但不改变产品结论。

旧协议候选的撤回与后来逐动作协议接入是不同变更，不能因今天使用原生动作就把旧候选写成成功。后续研究链已取得可定位的来源、取证和修订失败，活动准入由[设计优化队列](../future/design-optimization-backlog.md)拥有；本篇不再维护旧 G2 或研究用例的准入级别。新的研究失败仍需定位实际最早责任，不能默认重新打开已关闭的参数问题。

## 7. 如果面试官追问“最后怎样落地”

现行动作相位向模型发送逐动作 Schema，`Adapter` 解码成内部 Proposal；`control_working_plan` 单独表达工作清单控制，运行系统关联执行事实。模型结束动作相位后进入 typed 最终提交，适用核验和 Completion 通过后交付。具体责任与消费者由[Runtime](../topics/runtime.md)及[工具专题](../topics/tools.md)拥有。

工具参数、工作清单、来源支持、研究覆盖和最终汇总分别验收。历史参数阶段的局部通过保留原边界，后续研究失败在实际最早责任处定位；下一候选由问题证据准入，不能从旧参数故障推导当前根因。

## 8. 这次踩坑带来的判断

**可靠智能体的关键不是让模型一次输出更多结构，而是缩小每次模型决定的语义范围。** 类型化 Proposal、确定性 Admission 和执行治理仍然必要；真正需要收敛的是模型可见协议的职责数量。外层 JSON 可解析不等于工具可执行，工具可执行不等于研究完成，服务提供方差异也不等于架构结论。

稳定架构定义见[智能体运行外壳与关键能力 §1、§4](03-capability-axes.md)，最新结果数字和归档限制见[当前端到端用例盘点](../evals/02-current-case-inventory.md)，未解决问题与下一项允许动作见[设计优化队列](../future/design-optimization-backlog.md)，外部机制的完整分级入口见[工具执行与安全参考](../agentRef/tool-execution-and-safety.md)。
