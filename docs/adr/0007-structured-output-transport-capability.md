# ADR 0007: Structured Output Transport Capability Isolation

- 状态：Accepted for experimental implementation；not merge-ready
- 日期：2026-07-28
- baseline：`data/e2e_traces/20260728T135746.012529Z-20360-ce914ffb`
- target evidence：`data/e2e_traces/20260728T143217.175037Z-28784-bb0ed0e8`
- 移除或完成门禁日期：2026-08-28

## Goal / Current Incorrect Behavior / Expected User-visible Result

同一 IP01 自然语言调查请求使用 OpenAI-compatible DeepSeek deployment 时，不应因 Provider
接受但不执行 strict `json_schema` 而在 Plan/Replan/Verifier typed contract 上失败。最终用户
结果仍是带来源、日期和局限的可读报告；Provider transport 通过不能替代该结果。

## Business Expansion or Proven Constraint / Out of Scope

已证明约束是不同 Provider/model 对结构化输出协议支持不等价。范围仅隔离 structured-output
transport。Out of Scope：修改 Planner/Verifier schema、补字段、放宽 Pydantic、增加业务重试、
更改 Project 预算或把 transport error 伪装为完成。

## Simplest Baseline E2E / Executed Result / Root Cause

命令：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E='true'
uv run pytest evals/e2e_quality/test_product_capability_outcomes.py::test_product_ip01_live_investigation_report --e2e-scope=release -q -s
```

baseline 用时 226.9 秒、约 33.4k token，终态 `paused/provider_unavailable`；一次 repair 后
`_PlanDraft.requirement_mappings` 仍缺失。根因是旧 `OpenAIModelClient` 总先发送 strict
`json_schema`，只在 HTTP 明确拒绝时降级；DeepSeek 接受请求但不执行 schema，异常分支无法发现。

## Target E2E and Counterfactuals

相同命令、入口、输入和预算下，target archive 用时 59.7 秒、可计 28,828 token；全部
Plan/Replan/Verification typed parse 通过，`environment_failed=false`，且没有 schema repair。
它仍因 evidence verification repair 与 frozen-work revision admission 暂停，未交付报告。

反事实：strict Adapter 遇到不支持协议不得运行时降级；JSON Object 第二次仍无效必须失败；
Adapter 不补字段、不截取多个不同 JSON 值。Tool Strategy 在两个 IP01 archive 中产生多 Tool
或不同连续 JSON，未证明收益，已从最终设计删除。

## Decision Ownership / Fact Owner and Write Path

- `StructuredConfig.output_transport`：deployment capability profile 的唯一配置事实；
- Composition Root：唯一 Adapter 选择点；
- `StrictJsonSchemaAdapter` / `JsonObjectStructuredAdapter`：只拥有 transport request/response；
- Pydantic output type：typed contract owner；
- Planner、Verifier：开放业务语义 owner，不感知 Provider transport。

运行中不得根据 parse error 修改全局 transport。Proposal、Execution Fact、Verification 与
Completion owner 均未改变。

## Required Production Capabilities and Missing-capability Delivery

已有 `StructuredModelClient` Port、OpenAI-compatible SDK 调用、Pydantic parse、usage/trace 和
Composition Root。扩展一个显式 profile 和 JSON Object Adapter；它发送 `json_object`、注入
canonical schema、最多请求一次模型完整重写、聚合两次 latency/token，并 fail closed。

## Affected Modules and Dependency Direction

仅影响 `kernel/config_models.py`、`kernel/config_env.py`、`infra/structured_model.py`、Composition
测试及 release fixture 配置物化。Application/Domain 仍只依赖 Model Port，依赖方向未改变。

## Complexity Added, Removed and Rejected Alternatives

新增一个枚举字段和一个 transport Adapter；同步删除 mutable `_structured_transport`、
`json_schema -> json_object -> plain text` 异常驱动降级及对应测试。拒绝 Provider-name Adapter，
因为变化源是 capability；拒绝增加 repair 次数或截取首个不同 JSON，因为会隐藏模型失败；
拒绝保留 Tool Adapter，因为复杂 IP01 已证伪。

## Removed Legacy Path / Risks / Exit

旧隐式降级和 plain-text fallback 已删除。风险是 JSON Object 依赖 Prompt 约束，且当前 target
尚未产生最终用户报告，因此本 ADR 不授权 merge/release。2026-08-28 前必须在同一自然目标上
取得报告交付并通过关键反事实，或证明该 Adapter 被另一个已通过用户 E2E 的 deployment 消费；
否则删除 JSON Object Adapter、profile 和本 ADR，改用具备原生 schema 能力的 deployment。

当前工程验证：相关模型/config/catalog 测试 77 passed；完整低层套件 659 passed、4 warnings、
242.52 秒；变更范围 Ruff、compileall 与 package DAG gate 均通过。这些不能替代失败的 IP01。
