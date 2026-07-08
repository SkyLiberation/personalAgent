# GPT Researcher A2A Workflow

本文总结 `gpt-researcher` 以 A2A 接入后的当前架构。它不是 `ask` 或 `research_once` 的兼容 fallback，也不是 ToolGateway tool wrapper；它是一个独立 workflow，通过 AgentGateway 显式委托外部研究 Agent。

## 一句话结论

当用户明确点名 `GPT Researcher` / `GPT-Researcher` / `A2A` 并要求研究报告时，Router 会路由到 `gpt_researcher_a2a`。固定 workflow 执行 `agent_call(gpt_researcher)`，由 AgentGateway 产生 AgentRun、AgentEvent 和默认 `unverified` 的 AgentArtifact。

## 外部能力

`D:\mySoft\workspace\gpt-researcher` 暴露 A2A JSON-RPC 后端：

```text
Agent Card: http://127.0.0.1:8001/.well-known/agent-card.json
A2A JSON-RPC: http://127.0.0.1:8001/a2a
```

当前 Agent adapter 支持：

- blocking invoke：A2A `message/send` with `configuration.blocking=true`
- async submit：A2A `message/send` with `configuration.blocking=false`
- poll：A2A `tasks/get`
- cancel：A2A `tasks/cancel`
- stream：A2A task stream/output 映射为 `AgentEvent(type="stream_delta")`

## 固定拓扑

```text
gpt_researcher_a2a
  gptr-a2a-research agent_call(gpt_researcher)
    -> AgentGateway
       -> AgentRun
       -> AgentEvent
       -> AgentArtifact(unverified)
  gptr-a2a-compose compose
```

这个拓扑来自 `WorkflowSpec / WorkflowRegistry`。`gptr-a2a-research` 是 deterministic `agent_call`，不需要 ReAct 选择工具；它的作用是把一次外部 Agent 委托纳入 AgentGateway 边界。

## 治理边界

`gpt_researcher` 当前 AgentGovernance：

| 字段 | 值 |
| --- | --- |
| protocol | `a2a_jsonrpc` |
| risk_level | `medium` |
| side_effects | `external_network` |
| permission_scope | `a2a:gpt_researcher:research` |
| data_egress_class | `content` |
| trust_level | `external` |
| timeout | `PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS`，默认 120s |
| rate_limit | 5/min |

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

## 质量门禁

| Gate | 验证内容 |
| --- | --- |
| `tests/test_gpt_researcher_a2a_tool.py` | `GPTResearcherA2AAdapter` 的 AgentRunResult、AgentGovernance 和 unverified artifact |
| `tests/test_gpt_researcher_a2a_workflow.py` | workflow 使用 `agent_call(gpt_researcher)` |
| `evals/agent_gateway_quality` | invoke、submit/poll、cancel、stream、多 Agent registry |
| `evals/e2e_quality` | `execute_entry -> router -> gpt_researcher_a2a -> agent_call -> AgentGateway -> AgentRun / AgentArtifact` |

## 验证命令

```powershell
uv run --extra dev python -m pytest tests/test_agent_gateway.py tests/test_gpt_researcher_a2a_tool.py tests/test_gpt_researcher_a2a_workflow.py evals/agent_gateway_quality -q
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
| `src/personal_agent/kernel/contracts/agent.py` | AgentDefinition / AgentRun / AgentArtifact 契约 |
| `src/personal_agent/agents/gateway.py` | AgentGateway invoke / submit / poll / cancel / stream |
| `src/personal_agent/agents/gpt_researcher_a2a.py` | GPT Researcher A2A adapter |
| `src/personal_agent/planning/workflow.py` | `gpt_researcher_a2a` workflow |
| `src/personal_agent/orchestration/orchestration_nodes/_steps.py` | `agent_call` step 执行 |
