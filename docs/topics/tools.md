# 工具执行

当前工具层直接使用 LangChain 工具与 LangGraph `ToolNode`，不再维护独立的工具协议。

## 结构

- 每个业务工具由 `build_*_tool()` 工厂创建，并使用 `@tool` 声明名称、描述、参数 schema 与返回 artifact。
- `ToolExecutor` 仅注册和查询 LangChain `BaseTool`；不再自行编译工具子图。
- `PlanExecutionGraph` 持有确定性步骤/HITL 的 `plan_tool_node`，`ReactGraph` 持有受限探索动作的 `react_tool_node`；二者复用同一工具注册表。
- `ToolNode` 使用执行期 `tool_messages` 通道；用户可见的跨轮对话仅保存在 `messages` 中，内部工具交换不会污染会话历史。
- state 使用 `pending_tool_step_id`、`pending_tool_call_id` 与 `pending_react_iteration` 校验工具结果归属，恢复后不会消费到旧调用的 artifact。
- 调试 API 和非编排的同步入口使用 `invoke_direct()` 直接调用工具，不建立额外 Graph。
- `PlanValidator` 直接读取工具的 Pydantic 参数 schema，并读取 `extras` 中的治理属性。

## 已注册工具

| 工具 | 用途 | 治理属性 |
| --- | --- | --- |
| `capture_text` | 写入文字知识笔记 | `writes_longterm` |
| `capture_url` | 提取链接正文 | `accesses_external` |
| `capture_upload` | 提取上传文件正文 | `writes_longterm` |
| `graph_search` | 查询图谱知识 | 只读 |
| `web_search` | 查询公网资料 | `accesses_external` |
| `delete_note` | 删除知识笔记 | `risk_level=high`, `requires_confirmation`, `writes_longterm` |

## 返回结果

工具使用 `response_format="content_and_artifact"`：

- `content` 供 LangGraph/LangChain 消息流表达工具观察结果。
- `artifact` 保存业务结构化输出：`ok`、`data`、`error`、`evidence`。

这种结构使 `ToolNode` 负责工具调度与参数校验，编排节点仍能使用稳定的结构化数据维护计划进度、证据与 HITL 状态。

## HITL

`delete_note` 第一次调用仅返回待确认 payload。`PlanExecutionGraph` 将其写入 checkpoint 的 `pending_confirmation` 并在确认节点暂停；用户确认后，同一工具在 `confirmed=True` 的输入下由 `plan_tool_node` 执行删除。高风险工具不会进入 `ReactGraph` 的自主调用。
