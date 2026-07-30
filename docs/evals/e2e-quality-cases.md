# 正式环境核心用户结果 E2E

`evals/e2e_quality/evidence_catalog.py` 是用例身份、证据种类、入口、Provider profile、故障机制
和发布资格的唯一分类 owner。本文解释为什么这样分类，不复制完整 test-name 映射；当前 archive
与发布结论见
[Phase 0 能力与发布基线](../summary/phase0-capability-release-baseline.md)。

## 1. E2E 要证明什么

项目的框架主链是：

```text
Semantic Proposal
  -> Admission / Policy
  -> Governed Execution
  -> Execution Fact
  -> Verification
  -> Completion
```

E2E 必须从用户真实掌握的信息进入正式 HTTP 入口，自动断言最终用户结果和关键反事实。它可以在
执行后读取 trace、Receipt、Claim、Artifact 或 Project projection 证明生产路径，但不能在用户
输入中指定 Tool、Agent、Plan、内部 ID、执行顺序或 Verifier 次数。

只证明以下内容不算用户 E2E：

- Pydantic 对象创建成功；
- Tool 返回 `ok=true`；
- 数据库新增一行；
- child Agent 进入 `completed`；
- Verifier 返回 `passed`；
- 内部状态机在 scripted Port 下走到终态。

## 2. 发布级入口标准

只有 catalog 中 `release_eligible=true` 的用例才可以参与产品发布声明。它必须：

1. 从真实 HTTP 入口进入独立 Web 进程；
2. 使用 `Settings.from_env()` 的真实模型、真实 PostgreSQL 和场景所需真实 Provider；
3. 不注入 Proposal、Plan、Grant、Observation 或 Result；
4. 正向路径到达用户可观察结果，负向路径到达明确 denied/waiting/limitation/fail-closed；
5. 同时断言关键错误结果没有发生；
6. 需要恢复时以真实进程终止制造窗口，而不是进程内 callback；
7. 保存 trace envelope、manifest、summary 和 checksum。

PostgreSQL 测试库、临时 Artifact 目录和 Graphiti group prefix 只做数据隔离，不替换业务组件。

## 3. 当前证据分类

| 分类 | 当前编号 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| 原生产品能力 | E01–E14、IP01 | 一个明确产品目标从正式入口获得结果 | 未覆盖的其他能力和组合 |
| 组合用户旅程 | C01–C04 | 多个已存在能力完成同一用户目标 | 单个组件普遍可靠 |
| 复杂 Interaction | L01–L06 | 自然能力选择、并发、恢复、预算和 receipt-bound revision | durable Project 全生命周期 |
| Capability Profile | E16–E19 | 真实 MCP/A2A connector 可执行或 fail closed | 独立产品发布声明 |
| Durable diagnostic | LT01–LT13 | 生产 Domain/Application/PostgreSQL/worker 协议 | live model/provider 产品结果 |
| Baseline diagnostic | B03 等历史 archive | 当前产品行为的已执行不足 | 修复已经正确 |

`EvidenceClaimKind`、`EntryBoundary`、`FaultMechanism` 和 `release_eligible` 的机器规则只在
`evidence_catalog.py` 中维护。

## 4. 三条生产主链怎样取证

### Conversation

```text
POST /api/conversation/turn 或 SSE adapter
  -> AgentTurnDecision
  -> Admission
  -> ToolExecutor / AgentGateway
  -> ActionObservation / DecisionFeedback
  -> FinalMessage
```

断言重点：自然能力选择、错误 Tool/参数拒绝、Observation 驱动、预算限制、跨 scope 隔离、最终
文本与 required receipt 的绑定。

### 固定 Application Workflow

```text
Product API
  -> explicit Use Case / Domain Command
  -> confirmation / transition / provider
  -> Receipt or typed terminal result
```

断言重点：确认前零副作用、错误 digest 拒绝、唯一写入口、重启恢复、replay 不重复执行。

### Investigation Project

```text
POST /api/investigation-projects
  -> PostgreSQL definition + worker queue
  -> accepted Plan / ready set
  -> Tool or Agent execution
  -> Evidence Admission / Verification
  -> Completion Gate / report
```

LT 用例验证状态机、journal、恢复和不变量；IP01 才从 live HTTP/worker/model/Web Search 路径证明
一个用户报告目标。两者不能互相替代。

## 5. 反事实是主要可信度来源

当前矩阵按场景断言：

- 错误 digest、scope denied 和未确认操作不执行；
- Ask 不把模型答案隐式写成 Claim；
- 另一 workspace 的事实不进入回答；
- capability unavailable 不选择“最像”的替代 Tool；
- budget exhaustion 不拼接未经执行的业务答案；
- child Artifact 不自动成为父级 FinalMessage；
- restart/replay 不重新生成冻结 Command，不重复副作用；
- report 缺 Evidence、Verification 或 required mapping 时 Completion Gate 不通过。

正向结果可能偶然命中；这些反事实用来证明权力边界确实生效。

## 6. Archive 与发布门禁

每次 archive 包含：

- `manifest.json`：commit、dirty state、环境和模型 profile；
- `*.trace.json`：逐用例生产 trace；
- `summary.json`：pytest 结果、阶段耗时和失败；
- trace envelope：用例、run identity 与关键事实索引；
- `checksums.sha256`：JSON 完整性。

运行：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

release gate 只接受 catalog、clean matching revision、passed summary、trace envelope 和 checksum
的交集。历史 archive、dirty worktree 定向通过、diagnostic 或 capability profile 均不能绕过该
条件。

## 7. 当前边界

IP01、E14 和多组 Conversation/MCP/A2A 定向 archive 已提供对应工程证据；旧完整 23/23 archive
不匹配当前 catalog，当前工作树也不是 clean matching revision。package DAG gate 还在
2026-07-30 审计中实际失败。当前不得声称完整 release ready；修复和退出计划见
[可信 Agent Runtime 演进与收敛](../future/trusted-agent-runtime-evolution.md)。
