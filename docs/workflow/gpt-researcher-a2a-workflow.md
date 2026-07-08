# GPT Researcher A2A Workflow

本文总结 `gpt-researcher` 以 A2A 接入后的当前架构。它不是 `ask` 或 `research_once` 的兼容 fallback，也不是直接 HTTP shortcut；它是一个独立 workflow，显式委托已部署的外部研究 Agent。

## 一句话结论

当用户明确点名 `GPT Researcher` / `GPT-Researcher` / `A2A` 并要求研究报告时，Router 会路由到 `gpt_researcher_a2a`，固定 workflow 调用受治理工具 `gpt_researcher.a2a_research`。真实执行仍经过 ToolGateway、PolicyEngine、超时/重试/限流和审计。

## 外部能力

`D:\mySoft\workspace\gpt-researcher` 暴露 A2A JSON-RPC 后端：

```text
Agent Card: http://127.0.0.1:8001/.well-known/agent-card.json
A2A JSON-RPC: http://127.0.0.1:8001/a2a
```

当前使用 `message/send` blocking 调用，参数形态遵循 gpt-researcher 的 A2A 文档：

```text
message.role=user
message.parts=[{"kind":"text","text": topic}]
message.metadata.report_type=research_report
message.metadata.report_source=web
message.metadata.tone=Objective
configuration.blocking=true
```

返回的 A2A task 会归一为工具 artifact：

- `task_id`
- `context_id`
- `state`
- `report`
- `artifacts`
- `metadata`
- `raw`

## 固定拓扑

```text
gpt_researcher_a2a
  gptr-a2a-research tool_call(gpt_researcher.a2a_research)
    -> gptr-a2a-compose compose
```

这个拓扑来自 `WorkflowSpec / WorkflowRegistry`。`gptr-a2a-research` 是 deterministic tool_call，不需要 ReAct 选择工具；它的作用是把一次外部 Agent 委托纳入统一 ToolGateway 边界。

## Router 边界

进入该 workflow 的请求必须显式提到 GPT Researcher 或 A2A，例如：

```text
用 GPT Researcher A2A 调研 Agent2Agent 协议采用情况，并生成研究报告
```

普通“调研最近动态”“收集官方发布”“整理最新论文”仍走本工程内置 `research_once`。简单问答仍走 `ask`。

## 治理边界

`gpt_researcher.a2a_research` 当前治理契约：

| 字段 | 值 |
| --- | --- |
| exposure | `public_agent` |
| risk_level | `medium` |
| side_effects | `external_network` |
| permission_scope | `a2a:gpt_researcher:research` |
| timeout | `PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS`，默认 120s |
| max_retries | 1 |
| rate_limit | 5/min/user |

风险为 medium 的原因：一次调用可能触发外部搜索、较长任务和成本消耗；但它不直接写入个人长期知识，也不删除或修改本工程状态，所以不要求 HITL。

## 配置

```env
PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED=true
PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENDPOINT=http://127.0.0.1:8001/a2a
PERSONAL_AGENT_GPT_RESEARCHER_A2A_AGENT_CARD_URL=http://127.0.0.1:8001/.well-known/agent-card.json
PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS=120
PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_TYPE=research_report
PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_SOURCE=web
PERSONAL_AGENT_GPT_RESEARCHER_A2A_TONE=Objective
PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS=
```

gpt-researcher 后端启动方式：

```powershell
cd D:\mySoft\workspace\gpt-researcher
docker compose -f docker-compose.a2a.yml up --build
```

## e2e_quality Golden Set

| Case | 输入类型 | 期望 workflow | 期望工具 | 禁止工具 |
| --- | --- | --- | --- | --- |
| `E2E-GPTR-A2A-001` | 显式 GPT Researcher A2A 研究请求 | `gpt_researcher_a2a` | `gpt_researcher.a2a_research` | `graph_search`、`research_run_loop` |

该用例注册同名 fake A2A 工具，但调用动作由 `execute_entry` 的真实入口链路产生。测试验证 Router、Workflow projection、StepExecutionGraph、ToolGateway 和 audit trace，而不是直接调用工具。

## tool_quality Golden Set

`evals/tool_quality` 验证 `gpt_researcher.a2a_research` 的治理 metadata：

- exposure 为 `public_agent`
- risk 为 `medium`
- side effects 为 `external_network`
- permission scope 为 `a2a:gpt_researcher:research`
- timeout / retry / rate limit / audit 满足 baseline

## 验证命令

```powershell
uv run --extra dev python -m pytest tests/test_gpt_researcher_a2a_tool.py tests/test_gpt_researcher_a2a_workflow.py tests/test_workflow_validator.py evals/tool_quality -q
```

```powershell
$env:E2E_QUALITY_BRANCHES="gpt_researcher_a2a"
$env:E2E_QUALITY_ENFORCE_BASELINE="true"
uv run --extra dev python -m pytest evals/e2e_quality -q
Remove-Item Env:\E2E_QUALITY_BRANCHES
Remove-Item Env:\E2E_QUALITY_ENFORCE_BASELINE
```

## 相关代码位置

| 位置 | 作用 |
| --- | --- |
| `src/personal_agent/infra/a2a.py` | GPT Researcher A2A JSON-RPC client |
| `src/personal_agent/tools/gpt_researcher_a2a.py` | 受治理 LangChain tool |
| `src/personal_agent/kernel/config_models.py` | A2A 配置模型 |
| `src/personal_agent/kernel/config_env.py` | A2A 环境变量解析 |
| `src/personal_agent/planning/router.py` | 显式 GPT Researcher/A2A 路由规则 |
| `src/personal_agent/planning/workflow.py` | `gpt_researcher_a2a` WorkflowSpec |
| `src/personal_agent/orchestration/orchestration_nodes/_steps.py` | topic 注入和 report compose |
| `evals/e2e_quality/test_workflow_e2e_quality.py` | 完整链路 e2e case |
| `evals/tool_quality/cases.json` | 工具治理 golden case |
