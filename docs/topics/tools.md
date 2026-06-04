# 工具层

优秀 Agent 的工具层不是把 API 暴露给模型，而是把模型的意图转换为可理解、可组合、可控、可观测的系统动作。

当前项目的工具层已经完成了基础执行协议的收敛：业务工具仍使用 LangChain `@tool` 声明，但执行边界由项目内的 LangGraph-native `ToolGateway` 承接，用统一 artifact 承载业务结果，并通过工具 `extras.governance` 暴露结构化治理属性。它更接近一个轻量 Tool Runtime，而不是裸露 API 集合。

## 设计目标

工具层需要同时满足两类要求：

- 对模型友好：工具名称、描述、参数 schema 要让模型知道何时调用、如何调用、不要在什么场景调用。
- 对系统可靠：工具执行必须有结构化输入输出、风险标记、确认机制、结果归属校验和可审计记录。

因此工具层的职责不是“替 Agent 思考”，而是限制和承接 Agent 的行动：

```text
Agent 决策层
    ↓
计划 / ReAct 选择工具与参数
    ↓
ToolGateway / ToolExecutor
    ↓
业务工具
    ↓
结构化 artifact / evidence / HITL 状态
```

## 当前实现

- 每个业务工具由 `build_*_tool()` 工厂创建，并使用 `@tool` 声明名称、描述、参数 schema、`response_format` 与结构化治理 `extras.governance`。
- `ToolExecutor` 负责注册和查询 LangChain `BaseTool`，并持有统一 `ToolGateway`；Agent 执行期不再自行编译工具子图。
- `PlanExecutionGraph` 持有确定性步骤/HITL 的 `plan_tool_node`，`ReactGraph` 持有受限探索动作的 `react_tool_node`；二者都调用同一个 Gateway 节点。
- `ToolGateway` 使用执行期 `tool_messages` 通道；用户可见的跨轮对话只保存在 `messages` 中，内部工具交换不会污染会话历史。
- state 使用 `pending_tool_step_id`、`pending_tool_call_id` 与 `pending_react_iteration` 校验工具结果归属，恢复后不会消费到旧调用的 artifact。
- 调试 API 和非编排的同步入口使用 `invoke_direct()` 直接调用工具，不建立额外 Graph。
- `PlanValidator` 直接读取工具的 Pydantic 参数 schema，并读取 `extras` 中的治理属性。

## 与优秀 Agent 工具层的对照

| 维度 | 优秀 Agent 工具层 | 当前项目状态 |
| --- | --- | --- |
| 工具抽象 | 暴露任务语义工具，而不是裸 API 或数据库操作 | 已按业务动作封装为 `capture_*`、`graph_search`、`web_search`、`delete_note` |
| 输入契约 | 使用结构化 schema，参数少而明确，可在执行前校验 | 已使用 Pydantic schema，并由 `PlanValidator` 校验计划参数 |
| 输出契约 | 返回稳定机器可读结构，失败可解释，证据可追踪 | 已统一为 `ok / data / error / evidence` artifact |
| 读写分层 | 读工具低风险开放，写工具标记副作用并受控执行 | 已用 `ToolGovernance.side_effects`、`risk_level`、`permission_scope` 表达读写和权限边界 |
| 高风险治理 | 删除、外发、付款、生产变更等需要确认、审计、幂等和回滚 | `delete_note` 已实现确认暂停；其他高风险类别目前尚未出现 |
| 执行隔离 | 内部工具消息不污染用户会话，可恢复后精确归属 | 已通过 `tool_messages` 与 pending id 做隔离和归属校验 |
| 自主探索限制 | ReAct 只能调用低风险、允许列表内工具，并限制迭代 | 已禁止高风险/需确认工具进入 ReAct，并限制 `max_iterations` |
| 观测审计 | 每次调用记录工具名、输入、输出、耗时、错误、用户/线程/副作用 id | 已提供 `tool_invocation_event()` 统一事件形状，direct 调用和图执行期工具结果都会产出审计 payload |
| 工具描述质量 | 描述包含使用时机、禁用场景、副作用和返回解释 | 当前工具描述已补充主要副作用和禁用场景，后续可继续按业务演进细化 |
| Tool Gateway | 在模型与真实系统之间集中处理权限、速率、确认、重试、幂等、审计 | 已引入轻量 `ToolGateway`，集中执行策略和审计；速率限制、权限后端和审计落库仍可继续扩展 |

## 已具备的能力

当前工具层的优势在于执行路径简单、契约统一，并且与 LangGraph 编排紧密结合：

- 复用 LangChain 原生工具协议，减少自研协议漂移。
- `ToolGateway` 负责工具调度、治理策略、参数注入、消息返回和审计事件记录。
- `content_and_artifact` 同时满足模型观察和业务结构化消费。
- `PlanValidator` 在执行前阻断未知工具、非法参数、高风险 ReAct、删除计划缺少确认等问题。
- `ToolGovernance` 将风险、确认、副作用、权限、幂等、回滚和审计要求固定为代码契约。
- HITL 状态进入 checkpoint，用户确认后可继续同一计划步骤。
- ReAct 与确定性计划共享工具注册表，但执行通道和风险边界分开。

## 主要差距

当前实现已经能支持个人知识 Agent 的核心工具调用，但距离成熟生产级工具层还有几类差距：

1. Tool Gateway 已有基础抽象，执行策略还可继续深化

   现在工具调用统一进入 `ToolGateway`，已经集中处理 ReAct 风险边界、高风险确认执行的幂等 key 校验和审计事件。随着工具增多，可以继续在 Gateway 内扩展权限后端、速率限制、重试策略和副作用登记。

2. 读写治理仍需执行策略落地

   `ToolGovernance.side_effects` 已经能区分 `read_local`、`external_network`、`write_longterm`、`delete_longterm`、`send_external`、`irreversible`。下一步需要为不同副作用绑定默认执行策略，例如写工具是否必须先草稿、删除是否必须软删除、外部网络是否需要来源限制。

3. 工具描述还可以更像“模型操作手册”

   工具 description 不应只描述“做什么”，还应说明：

   - 什么时候使用
   - 什么时候不要使用
   - 是否有副作用
   - 是否需要用户确认
   - 返回 artifact 中哪些字段可作为后续步骤依据

4. 审计事件还没有进入独立持久化存储

当前 `tool_invocation_event()` 已定义统一事件形状，`ToolGateway` 会为 direct、确定性计划和 ReAct 调用记录统一审计事件；计划执行和 ReAct 的工具结果消费也会在 `tool_result` 事件中带上 `invocation` 审计 payload。下一步应把这些事件写入独立审计表：

   ```text
   thread_id
   user_id
   tool_name
   tool_call_id
   step_id
   execution_mode
   input
   output
   artifact.ok
   error
   evidence
   latency_ms
   risk_level
   requires_confirmation
   side_effects
   permission_scope
   side_effect_id
   ```

5. 幂等与回滚策略尚未显式化

   对 `delete_note` 这类写操作，当前已有确认机制，确认执行时会携带 Gateway 校验的幂等 key；后续还可以补充删除前快照、软删除/恢复窗口等策略。未来如果增加外发、支付、生产操作类工具，这一点会变成硬要求。

## 工具注册表

| 工具 | 类型 | 用途 | 治理属性 |
| --- | --- | --- | --- |
| `capture_text` | 写 | 写入文字知识笔记 | `risk_level=low`, `side_effects=write_longterm`, `permission_scope=memory:write` |
| `capture_url` | 外部读 | 提取链接正文 | `risk_level=low`, `side_effects=external_network`, `permission_scope=network:read` |
| `capture_upload` | 写 | 提取上传文件正文 | `risk_level=low`, `side_effects=write_longterm`, `permission_scope=memory:write` |
| `graph_search` | 本地读 | 查询图谱知识 | `risk_level=low`, `side_effects=read_local`, `permission_scope=memory:read` |
| `web_search` | 外部读 | 查询公网资料 | `risk_level=low`, `side_effects=external_network`, `permission_scope=network:read` |
| `delete_note` | 删除 | 删除知识笔记 | `risk_level=high`, `requires_confirmation`, `side_effects=delete_longterm`, `permission_scope=memory:delete`, `idempotency_key_required` |

## 返回结果

工具统一使用 `response_format="content_and_artifact"`：

- `content` 供 LangGraph/LangChain 消息流表达工具观察结果。
- `artifact` 保存业务结构化输出：`ok`、`data`、`error`、`evidence`。

成功结果：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "evidence": []
}
```

失败结果：

```json
{
  "ok": false,
  "data": null,
  "error": "错误原因",
  "evidence": []
}
```

这种结构使 `ToolGateway` 负责工具调度、治理策略与参数校验，编排节点仍能使用稳定的结构化数据维护计划进度、证据与 HITL 状态。

## HITL 与高风险动作

`delete_note` 是当前唯一高风险工具。它采用两阶段执行：

1. 第一次调用仅返回待确认 payload。
2. `PlanExecutionGraph` 将 payload 写入 checkpoint 的 `pending_confirmation`，并在确认节点暂停。
3. 用户确认后，同一工具在 `confirmed=True` 的输入下由 `plan_tool_node` 执行删除。

高风险工具不会进入 `ReactGraph` 的自主调用。`PlanValidator` 会阻止 `execution_mode="react"` 的步骤声明 `risk_level="high"` 或 `requires_confirmation=True`。

## 审计事件

direct 调用由 `ToolExecutor.invoke_direct()` 记录 `tool_invocation` 日志字段。图执行期调用由工具结果消费节点记录：

- 计划步骤：`_node_consume_plan_tool_result()` 在 `tool_result` 事件中写入 `invocation`。
- ReAct 步骤：`_node_consume_react_tool_result()` 在 `tool_result` 事件中写入 `invocation`。

`ToolTrackingSubState` 会在调用开始时保存 `pending_tool_name` 和 `pending_tool_input`，消费结果时再与 artifact 合并，形成包含输入、输出、风险、副作用和权限范围的审计 payload。

## 演进建议

下一阶段可以把当前轻量工具层演进为更完整的 Tool Gateway：

- 将 `tool_result.payload.invocation` 落库到独立审计表。
- 围绕 `ToolGovernance` 扩展统一执行策略入口：权限校验、速率限制、确认、幂等、回滚、审计。
- 为写工具建立默认策略：先草稿、再确认、后执行；必要时保存执行前快照。
- 为外部访问工具建立来源、超时、速率限制和结果引用规范。
- 定期用测试覆盖每个工具的 schema、artifact、治理属性和高风险执行路径。

判断标准很简单：模型可以选错工具或传错参数，但工具层应该尽量让错误停在执行边界内，而不是变成不可追踪、不可恢复的系统副作用。
