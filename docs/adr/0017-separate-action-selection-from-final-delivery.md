# ADR 0017：分离动作选择与最终交付

- 状态：Accepted，target 与 Tool Calling 影响验证已通过，独立因果验证待完成
- 日期：2026-08-31
- 影响范围：Conversation 模型动作协议、Provider Adapter、Semantic Verification、FinalMessage 交付
- 详细设计：[普通对话研究交付与 Plan 边界优化方案](../future/conversation-research-delivery.md)

## 1. 背景与目标

普通 Conversation 原先把 `control_final_message` 与 Tool、Agent、Plan 控制都投影成同一组 Provider
actions。服务提供方一次可以返回多个 tool calls，因此模型可能在同一响应里同时提交 Final 和继续执行
动作；Application 又要求 Final 全局独占，只能拒绝整个响应。`HARNESS-003` 在执行事实已经齐全后因此没有
形成合法交付。

问题不是“禁止多个工具调用”。多个相互独立的只读动作仍应并行；冲突来自把终止交付也建模为可并行
动作。本决策的目标是让动作阶段与最终交付在顶层互斥，同时保留普通工具并行、typed Final、Verifier
修订和失败关闭。

## 2. 机制依据与本地失败证据

OpenAI Chat Completions 的官方契约把一次 assistant 结果表示为普通 message 或一个/多个 tool calls，
并允许通过 `tool_choice` 控制工具选择；[OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
也把 message output 与 function-call output 分开表示。LangGraph 的
[官方 quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)以“最后一条消息包含 tool calls
则进入 tools，否则结束”作为路由边界；其
[Functional API 文档](https://docs.langchain.com/oss/python/langgraph/use-functional-api)同样只在存在
tool calls 时继续循环，并允许并行执行多个调用。Anthropic 的
[官方 tool use 文档](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)也把一个或多个
`tool_use` blocks 与后续最终回答分成不同阶段。

这些实现只证明“动作可以并行、最终交付应位于动作循环之外”是成熟机制，不能代替本工程失败事实。
本工程的失败 baseline 是 `HARNESS-003` v4 归档
`data/e2e_traces/product_baselines/harness-003/target/20260831T041305.551156Z-34520-c8bf7b1d`：三份
档案事实已恢复且原始读取为零，但模型提交 Final 与动作的混合响应后仍未交付，最终为 `limitation`。

## 3. 决定与责任主体

| 决策或事实 | 唯一 owner | 写入口与约束 |
| --- | --- | --- |
| 下一步执行哪些普通动作、是否并行 | 模型 | action phase 中的 Provider action calls；每个调用只表达一个具体动作或 Plan 控制 |
| 是否已准备生成最终结果 | 模型 | 无 payload 的 `prepare_final` 控制；它不是答案，也不是完成证明 |
| Action 与 Final 顶层互斥 | Conversation Application | action phase 不接受 typed Final；finalization phase 不暴露任何 action definitions |
| Provider 是否返回合法 action envelope | Provider Adapter | `tool_choice=required` 下缺少 action 时只做一次同 Schema 协议修复；再次失败则返回稳定 typed failure |
| 草稿是否满足语义标准 | Verifier | `passed`、`needs_revision` 或 `insufficient_evidence`；不得改写执行事实 |
| 下一轮进入哪个阶段 | Conversation Application | `needs_revision` 保持 finalization；`insufficient_evidence` 返回 action phase；`passed` 进入 Completion |
| 用户可见最终文本 | `FinalMessage` / Completion 出口 | 只来自独占 finalization phase，通过适用门禁后提交 |

破坏式迁移如下：

1. 从 Provider action definitions 删除携带答案的 `control_final_message`；
2. 增加无参数 `prepare_final` 控制，只请求下一次独占 typed Final；
3. `StructuredModelResponse` 禁止同时携带 typed value 与 action invocations；
4. action phase 允许多个兼容 Tool/Agent/Plan actions，执行完后才按 `prepare_final` 进入 finalization；
5. finalization phase 不投影工具、Agent 或 Plan actions，只接收 `FinalMessage`；
6. Verifier 的 `needs_revision` 直接再生成 typed Final，不插入没有业务意义的 action 回合；
7. `insufficient_evidence` 才恢复动作能力，以便补取证据；
8. Provider 在 required action phase 返回纯文本时，Adapter 使用同一 action schema 做一次协议修复，不把
   纯文本猜成 Final，也不做无界重试。

## 4. 为什么保留 `prepare_final`

当前 Provider 边界需要 strict typed `FinalMessage`，而普通 action phase 需要原生工具调用。把 strict Final
Schema 与工具列表重新放进同一次 `auto` 请求，会让模型在尚未执行动作时直接选择 Final；两次真实样本
均为零工具即提前交付，其中一次还编造了本地证据。`prepare_final` 只承担协议相位切换，不携带答案、
步骤 ID、执行结果或完成结论，因此没有成为第二份业务事实。

未采用“无 tool calls 自动视为 Final”的原因是当前 action phase 明确使用 `tool_choice=required`，且真实
样本曾在 Plan 尚有 `in_progress` 与 `pending` 步骤时返回纯文本。把该违规响应静默解释为完成会绕过
模型动作契约。若未来 Provider 能在不附加 Final Schema 的 `auto` 模式下稳定区分行动与结束，应以新的
同输入 baseline 重新评估并删除 `prepare_final`，不能保留双轨终止协议。

## 5. 复杂度、验证与退出条件

本决策没有增加持久状态、表、Repository、Planner、Workflow 或业务投影。`finalization_pending` 是单次
Application loop 的瞬时控制事实；canonical Plan、执行 Observation、Verification Receipt 与
FinalMessage 仍由原 owner 持有。新增一个无 payload 控制 action，同时删除携带完整答案 Schema 的 Final
action及其混合响应拒绝分支。

相关 Contract、Adapter、Conversation 与 `TOOL-AUTH-001` 回归共 `164 passed`。真实
`HARNESS-003` target 归档为
`data/e2e_traces/product_baselines/harness-003/target/20260831T053359.624686Z-9232-a8b902dd`：最终
`1/1 passed`，11 个模型回合、14 次工具或 workflow 调用、97,363 tokens，pytest call 阶段
159.105 秒；第二轮没有重复访问按次计费原始档案，Plan 最终全部完成，Verifier 经修订后返回 passed。

同一批次执行 `tool_calling_protocol` 四个既有节点，得到 `3/4 pytest passed`、`4/4 capability passed`。
唯一 Product E2E 失败为 `E16` 的外部 GitHub `401 Bad credentials`；其四次原生动作仍到达 MCP，且四个
节点均无 action protocol rejection。密封归档为
`data/e2e_traces/tool-calling-validation/20260831T054359.245940Z-19676-8b59b6c6`，checksum 有效。

如果同一阻塞再次表现为 Final 与动作混合、Final 修订被送回 required action phase、一次协议修复后仍
经常缺 action，或该控制需要新增持久状态和启发式路由，应撤回本决策并重新评估无 tool-call 终止协议。
当前 target 是 dirty candidate 的单样本，不证明跨 Provider 的普遍稳定性、通用成本收益或发布完成；
剩余准入与回归状态由[设计优化队列](../future/design-optimization-backlog.md)维护。
