# MCP Task-Domain Workflow

本文记录 GitHub / Notion MCP 在当前架构中的主路径。文件名保留为历史入口，但内容已经从 provider-specific GitHub workflow 更新为 capability-first 的 MCP task-domain workflow。

## 一句话结论

MCP provider 不再拥有独立 workflow identity。Router 只选择任务域：远程代码库问题进入 `external_codebase_qa`，外部工作区问题进入 `external_workspace_qa`，项目管理上下文进入 `external_project_ops`。具体使用 GitHub、Notion 或未来其他 MCP provider，由 `CapabilityResolver` 根据 `MCPCapabilityRegistry`、任务文本和 `CapabilitySelectionPolicy` 解析。

## 当前任务域 Workflow

```text
external_codebase_qa
  codebase-resolve resolve (execution_mode=react)
    -> CapabilityResolver -> allowed_tools
    -> ToolGateway
  codebase-compose compose

external_workspace_qa
  workspace-resolve resolve (execution_mode=react)
    -> CapabilityResolver -> allowed_tools
    -> ToolGateway
  workspace-compose compose

external_project_ops
  project-resolve resolve (execution_mode=react)
    -> CapabilityResolver -> allowed_tools
    -> ToolGateway
  project-compose compose
```

这些 ReAct step 不再静态声明 `github.*` 或 `notion.*` allowlist。运行时会先生成 `capability_resolution` 事件，再把解析出的 `allowed_tools` 交给 ReAct。实际工具调用仍统一进入 ToolGateway、PolicyEngine、幂等和审计。

## 当前 MCP Capability

| Provider | Capability | Local tool | Workflow scope |
| --- | --- | --- | --- |
| GitHub | `mcp:github:search_code` | `github.search_code` | `external_codebase_qa` |
| GitHub | `mcp:github:get_file_contents` | `github.get_file_contents` | `external_codebase_qa` |
| GitHub | `mcp:github:search_repositories` | `github.search_repositories` | `external_codebase_qa` |
| Notion | `mcp:notion:post-search` | `notion.search` | `external_workspace_qa` |
| Notion | `mcp:notion:retrieve-page-markdown` | `notion.retrieve_page_markdown` | `external_workspace_qa` |

## 完整执行链路

```text
EntryInput
  -> DefaultIntentRouter
  -> WorkflowRegistry.select("external_*")
  -> WorkflowPlanner compile ExecutionPlan
  -> StepProjectionValidator
  -> step execution
       resolve step
         -> CapabilityResolver
         -> capability_resolution event
         -> react_graph
              react_iterate
              react_tool_node
                 ToolGateway.invoke_graph
              consume_react_tool_result
              react_finalize
       compose step
  -> answer_completed
```

## 质量门禁

- `tool_quality` 验证 MCP tool 的治理 metadata 与 capability metadata。
- `resolver_quality` 验证 CapabilityResolver 的 selected / denied capabilities、local-first、read-only clamp 和跨 provider composition。
- `e2e_quality.github_mcp` / `e2e_quality.notion_mcp` 验证完整入口链路：task-domain workflow、`capability_resolution` 事件、ReAct scoped allowlist、ToolGateway audit 和最终回答。
