# E2E Quality 用例

`evals/e2e_quality/` 是真实环境 behavioral diagnostic。它运行生产入口、Task Analyzer、Executive Loop、Postgres、Evidence Engine、Tool/Agent Gateway，以及当前环境中可用的模型、web、Graph、MCP 和 A2A provider。

这不是完全确定性的 merge gate。真实模型和外部 provider 会漂移，因此稳定的 schema、Graph/Patch invariant、scope、HITL、幂等和失败恢复必须由 hermetic suite 以硬阈值保护；E2E 用于发现组合行为与环境漂移。

## 运行

```powershell
uv run pytest evals/e2e_quality -v
```

按 case 或 branch 运行：

```powershell
$env:E2E_QUALITY_CASES="E2E-ASK-002,E2E-ART-001"
$env:E2E_QUALITY_BRANCHES="ask,artifact"
uv run pytest evals/e2e_quality -v
```

子集默认记录 diagnostics，但不强制整体 baseline；需要强制时设置 `E2E_QUALITY_ENFORCE_BASELINE=true`。

未配置真实 structured model 时，依赖 Task Analyzer 的 live case 应 skip，不允许注入关键词 Router 伪装真实通过。其他 provider 缺失或降级应体现在 capability resolution、tool/agent trace、Observation、verification 或最终分数中。

## 当前边界

| 层 | 真实执行内容 |
| --- | --- |
| 任务理解 | `DefaultTaskAnalyzer` 输出 Goal、Relation 与 ResourceHint |
| 控制 | Executive decide/validate/act/observe/verify 循环 |
| Protocol | capture、artifact、solidify、delete、knowledge/research lifecycle |
| 开放式工作 | ask、direct response、summarize 等 BoundedAction 组合 |
| Capability | native/MCP/A2A resolution、scope、provider binding 与拒绝原因 |
| 工具 | ToolGateway、PolicyEngine、HITL、幂等和审计 |
| 证据 | ContextPack、citation、grounding、contradiction 与 verifier |
| 状态 | Postgres、LangGraph checkpoint、resume 和 run snapshot |

开放式 Goal 不通过 Procedure identity 评分。`procedure_id` 只对实际 Procedure invocation 有意义；E2E runner 不用 goal kind 冒充 Procedure。MCP/A2A case 通过 `expected_capability_ids`、`expected_agent_ids`、provider artifact 与 verification 状态评分。

## 评分维度

- Task intent hints 与显式 Goal dependency；
- terminal/run status 和 confirmation interrupt；
- Protocol ID 与内部 step，仅适用于 Protocol；
- tool/capability/agent 选择及 forbidden provider；
- answer、citation、evidence、grounding 与 verification；
- Research source/event/digest 与 stop reason；
- tool error kind、失败次数、预算和 stage timing；
- Workspace claim/admission/relation/projection 的持久化结果。

每个 case 同时声明正向期望和必要的 forbidden invariant。权限绕过、错误副作用、伪 workflow、未验证 A2A artifact、无 evidence 完成等问题使用硬失败，不被 branch 平均分抵消。

## 结果解释

失败应先按边界定位：

- Goal 或 relation 错误：Task Analysis；
- 有正确 Observation 但下一动作不合理：Executive；
- requirement 正确但 provider 错：Capability Resolver；
- provider 正确但调用被拒或越权：Gateway/Policy；
- Protocol 内部 step 错：Protocol compilation/execution；
- action 成功但 Goal 错误完成：Verification；
- 单次正确但 resume 丢失：checkpoint/conversation。

Live 网络和模型措辞波动不应通过硬编码关键词 fallback 修复。应优先补 replay fixture、改进 prompt/schema/decision policy，或把不稳定指标留在 diagnostic 层。
