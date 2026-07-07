# GitHub MCP Workflow

本文总结 GitHub MCP 接入后的当前架构：GitHub 远程仓库问答不再通过离线工具选择器或 direct tool 调用旁路执行，而是作为一等 workflow 进入 `execute_entry -> router -> workflow -> ReAct -> ToolGateway -> audit trace` 完整链路。

## 一句话结论

GitHub MCP 是只读远程仓库能力，当前映射为 `github.search_code`、`github.get_file_contents`、`github.search_repositories` 三个受治理工具。用户询问明确的 GitHub 仓库、代码、文件或仓库搜索问题时，Router 会路由到 `github_repository_qa`，由固定 workflow 的 ReAct 步骤在允许列表内选择工具，真实调用仍统一经过 ToolGateway、PolicyEngine、审计和 e2e 质量门禁。

## 接入目标

这次接入解决的是 Agent 对远程 GitHub 仓库的读取能力，而不是新增一个绕过主编排的工具快捷入口。

目标边界：

- 让 Agent 能回答“某个 GitHub 仓库的实现在哪里”“读取 README.md”“按 stars/topic/language 搜仓库”等问题。
- MCP server 只作为工具来源；业务上只注册显式批准的只读工具。
- 工具调用必须经过同一套 ReAct / ToolGateway / audit 机制。
- e2e_quality 必须验证完整入口链路，而不是只验证 `AgentService.execute_tool()`。

明确移除的设计：

- 不再使用 `select_tools_for_prompt(...)` 这类离线 selector。
- 不再在 e2e 里手工选工具并调用 `service.execute_tool(...)` 来模拟成功。
- 不把 GitHub MCP 作为 `ask` 的隐式兼容 fallback；它有独立 intent 和 workflow。

## 当前工具能力

| 工具名 | 远端 MCP tool | 作用 | 治理契约 |
| --- | --- | --- | --- |
| `github.search_code` | `search_code` | 在 GitHub 仓库中搜索代码 | `public_agent`、`low`、`external_network`、`github:repo:read` |
| `github.get_file_contents` | `get_file_contents` | 读取仓库文件内容，例如 README 或源码文件 | `public_agent`、`low`、`external_network`、`github:repo:read` |
| `github.search_repositories` | `search_repositories` | 搜索可见 GitHub 仓库 | `public_agent`、`low`、`external_network`、`github:repo:read` |

默认 GitHub MCP preset 使用官方 Docker stdio server：

```text
docker run -i --rm
  -e GITHUB_PERSONAL_ACCESS_TOKEN
  -e GITHUB_READ_ONLY
  ghcr.io/github/github-mcp-server
```

`GITHUB_READ_ONLY=1` 是默认安全边界。后续如果要接 issue、PR、workflow 或文件写入能力，不能复用当前只读 workflow，必须单独建中高风险工具、确认策略、权限域和 eval。

## 固定拓扑

```text
github_repository_qa
  github-retrieve resolve (execution_mode=react)
    allowed_tools:
      github.search_code
      github.get_file_contents
      github.search_repositories
    -> github-compose compose
```

这个拓扑来自 `WorkflowSpec / WorkflowRegistry`，不是 LLM 动态生成。LLM 只参与 `github-retrieve` 这个单步 ReAct 内部的工具选择，并且只能在 `allowed_tools` 中选择。

## 完整执行链路

```text
EntryInput
  -> normalize_entry
  -> route_intent
       DefaultIntentRouter
       github repository deterministic rule
  -> project_workflow_steps
       WorkflowRegistry.select("github_repository_qa")
       WorkflowPlanner compile ExecutionPlan
  -> validate_projected_steps
       StepProjectionValidator checks registered tools and allowed_tools
  -> step execution
       github-retrieve
         -> react_graph
              react_init
              react_iterate
              react_tool_node
                 ToolGateway.invoke_graph
              consume_react_tool_result
              react_finalize
       github-compose
  -> finalize_step_execution
  -> finalize_entry_result
```

关键点：

- Router 只输出 `github_repository_qa` goal，不输出工具名、风险策略或 workflow 拓扑。
- WorkflowSpec 才是工具允许列表、步骤依赖和执行模式的真源。
- ReAct 只是 `github-retrieve` 内部的执行模式，不是全局 autonomous loop。
- ToolGateway 仍然负责工具查找、策略校验、参数注入、执行、artifact 归一和审计。
- `github-compose` 只消费上一步结果并生成最终回复，不重新选择工具。

## Router 边界

GitHub workflow 的确定性路由规则只覆盖明确的仓库/代码/文件/搜索问题，例如：

- `github/github-mcp-server` 这类 `owner/repo`
- `repo:openai/openai-python filename:client.py`
- `README.md`、`.py`、`.ts`、`.go` 等文件线索
- `stars:`、`topic:`、`language:` 等 GitHub 搜索限定语
- 明确提到 GitHub 仓库、代码实现、读取文件或搜索仓库

泛泛的“调研 GitHub 最近新闻”“查资料”仍优先走 research 或 ask 边界，避免 GitHub 仓库 QA 抢占更广义的信息任务。

## 治理边界

GitHub MCP 工具虽然是外部网络访问，但当前只映射只读能力，因此风险等级为 low。治理仍不能省略：

- `PERSONAL_AGENT_GITHUB_MCP_ENABLED` 控制 GitHub preset 是否启用。
- `GITHUB_PAT` 通过 `PERSONAL_AGENT_GITHUB_MCP_TOKEN_ENV` 指定，不写死在配置里。
- MCP server 可以发现更多远端工具，但只有 `tools` 显式映射的能力会注册到 ToolGateway。
- 每个映射必须声明 `risk_level`、`side_effects`、`permission_scope`、timeout、retry、rate limit 和 audit。
- ReAct 执行期会同时受 `allowed_tools` 和 PolicyEngine 守卫。

## e2e_quality Golden Set

GitHub MCP 用例已经迁到 `evals/e2e_quality` 的 `github_mcp` branch。它们不是直接工具调用测试，而是完整入口链路测试。

| Case | 输入类型 | 期望 workflow | 期望工具 | 禁止工具 |
| --- | --- | --- | --- | --- |
| `E2E-GH-MCP-001` | 仓库实现位置问题 | `github_repository_qa` | `github.search_code` | `graph_search` |
| `E2E-GH-MCP-002` | README / 文件读取问题 | `github_repository_qa` | `github.get_file_contents` | `graph_search` |
| `E2E-GH-MCP-003` | GitHub 仓库发现问题 | `github_repository_qa` | `github.search_repositories` | `graph_search` |
| `E2E-GH-MCP-004` | `repo:` 限定代码搜索 | `github_repository_qa` | `github.search_code` | `graph_search` |
| `E2E-GH-MCP-005` | 个人知识问题负例 | `ask` | 无 GitHub 工具要求 | GitHub MCP 三个工具 |

Positive cases 注册本地 fake GitHub 工具作为 MCP 替身，但调用它们的动作由 `execute_entry` 里的 ReAct 节点产生。测试只 mock ReAct 的模型 tool-choice 结果，仍然经过真实 Router、Workflow projection、ReAct graph、ToolGateway 和 audit store。

## tool_quality Golden Set

`evals/tool_quality` 继续作为离线治理 metadata gate。它不调用工具，只验证 GitHub MCP 工具的治理字段：

- exposure 是否为 agent 可见范围。
- risk 是否为 low。
- side effects 是否为 `external_network`。
- permission scope 是否为 `github:repo:read`。
- timeout、retry、rate limit、audit 是否满足 baseline。

这层 gate 证明“工具可被安全注册”；e2e_quality 证明“用户问对应问题时完整链路确实会调用对应工具”。两者职责不同。

## 验证命令

```powershell
uv run --extra dev python -m pytest tests/test_github_repository_workflow.py tests/test_workflow_validator.py tests/test_mcp_tools.py evals/tool_quality -q
```

```powershell
$env:E2E_QUALITY_BRANCHES="github_mcp"
$env:E2E_QUALITY_ENFORCE_BASELINE="true"
uv run --extra dev python -m pytest evals/e2e_quality -q
Remove-Item Env:\E2E_QUALITY_BRANCHES
Remove-Item Env:\E2E_QUALITY_ENFORCE_BASELINE
```

## 相关代码位置

| 位置 | 作用 |
| --- | --- |
| `src/personal_agent/kernel/models.py` | `EntryIntent` 增加 `github_repository_qa` |
| `src/personal_agent/planning/router.py` | GitHub 仓库 QA 确定性路由规则 |
| `src/personal_agent/planning/workflow.py` | `github_repository_qa` WorkflowSpec |
| `src/personal_agent/orchestration/orchestration_nodes/_steps.py` | compose 阶段呈现 ReAct 工具结果 |
| `src/personal_agent/infra/mcp.py` | MCP http / stdio transport 和工具发现调用 |
| `src/personal_agent/kernel/config_env.py` | GitHub MCP preset 和工具映射 |
| `evals/e2e_quality/test_workflow_e2e_quality.py` | 完整链路 GitHub MCP e2e cases |
| `evals/tool_quality/test_tool_quality_gate.py` | GitHub MCP 工具治理 metadata gate |
| `tests/test_github_repository_workflow.py` | Router / Workflow 架构断言 |

## 面试讲法

可以说：GitHub MCP 没有被做成一个“看到 GitHub 就直接调工具”的兼容层，而是接成了 workflow-first 架构里的一个新业务 workflow。Router 只识别 intent；WorkflowSpec 声明步骤、ReAct 模式和 GitHub 工具 allowlist；ReAct 只负责单步内选择哪个只读 GitHub 工具；真实执行统一进 ToolGateway，所以权限、限流、超时、审计和 e2e 可观测性都和其它工具一致。e2e golden set 也按完整链路验证，避免只测 direct tool call 造成假阳性。
