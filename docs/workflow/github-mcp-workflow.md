# 历史设计：MCP Codebase Capability

> 状态：本文保留旧 `TaskAnalyzer/GoalGraph/Executive` 路径的迁移记录，不能描述当前 MCP
> 生产入口。当前 Conversation MCP 链路由 `EffectiveCapabilities -> ToolCallProposal ->
> Admission -> ToolExecutor/ToolGateway -> ActionObservation` 拥有，事实见
> [personalAgent 当前核心架构](../summary/core-architecture-current-state.md)。

GitHub、Notion 等 MCP provider 不拥有独立 workflow identity。它们以 capability 注册到统一 Registry，由 Executive 为当前 Goal 产生 provider-neutral requirement，CapabilityResolver 在执行前绑定具体 provider。

## 链路

```text
EntryInput
  -> TaskAnalyzer
       Goal("定位仓库中的鉴权逻辑")
       ResourceHint(codebase, repository/code, search/read)
       optional required provider=github
  -> GoalGraphCompiler
  -> Executive: acquire/explore BoundedAction
  -> CapabilityResolver
       eligibility + policy + scope + provider binding + coverage + rank
  -> ActionExecutionGraph / optional ReAct
  -> ToolGateway
  -> MCP tool
  -> Observation with provenance
  -> GoalVerifier
```

Task Analyzer 不保证 GitHub 能解决问题，也不选择具体 MCP tool。即使 provider 满足 schema，结果仍可能为空、过期或与 Goal 无关，因此 MCP artifact 先作为 untrusted Observation，主 Agent 负责后续验证、补证和最终回答。

## Scope

Resolver 输入是 Goal-scoped `CapabilityRequirement`，包含 semantic domain、resource type、operation、locator 与 required/preferred provider。一个 Goal 的 GitHub binding 不会扩散到同一任务的其他 Goal。

MCP tool 必须通过 ToolGateway，继续受：

- allowed tool set；
- PolicyEngine；
- user/session/provider scope；
- permission 与 credential；
- timeout/rate limit；
- audit 与 artifact provenance。

## 失败语义

MCP unavailable、denied、partial coverage、provider error 或空结果都形成结构化 Observation。Executive 决定换 provider、修改 acquire 策略、澄清 locator、委派、降级回答或停止；不存在 `external_codebase_qa` fallback workflow，也不会遍历所有工具碰运气。

## 验证

关键回归位于 `tests/test_github_resource_binding.py`、`tests/test_notion_resource_binding.py`、Capability Resolver tests 和 E2E capability cases。
