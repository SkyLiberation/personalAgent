# E2E 执行与机器证据目录

本目录当前由 [`evidence_catalog.py`](evidence_catalog.py) 分成两种**执行 selection**：

- `release`：9 条同时具有 typed 用户结果契约与真实 HTTP/模型/PostgreSQL profile 的 Product E2E；
- `diagnostic`：21 条 Application、Runtime 或 Capability Profile supporting evidence。

已撤回的 Investigation Project 及其 scripted conformance 已从当前矩阵删除；历史结论只由 checksum 归档保存。

当前逐项证据分类、baseline 合法性和指标覆盖见
[`docs/evals/README.md`](../../docs/evals/README.md)。

用户输入不得点名内部 Tool、Agent、Artifact、Model、执行顺序或结束判断。精确 capability、
并发、receipt、provider binding 只能在执行后通过 trace/contract 断言。

## 证据焦点

| layer | 主要事实 owner | 证明目标 |
| --- | --- | --- |
| `understanding` | Goal/Intent、Admission、TaskContract | 用户语义不被 validator 静默改写 |
| `planning_control` | Proposal、DecisionFeedback、AcceptedIntent、Command | 语义决策与确定性管控边界正确 |
| `authority_gateway` | Confirmation、Grant、Gateway、Receipt | 未授权不执行，授权只缩权 |
| `journal_recovery` | InvocationJournal、outbox、checkpoint、domain event | 恢复不重复副作用，不重算冻结 Command |
| `verification_completion` | Observation、VerificationReport、CompletionReport | 执行事实不冒充 Goal 完成 |

layer 是断言焦点，不是独立产品链路，也不能替代完整用户结果。

## 矩阵与发布门禁

精确用例、证据类别、test double、覆盖不变量和机器 `release_eligible` 只由 `evidence_catalog.py` 枚举。Product E2E 必须绑定 persona、source、自然目标、可观察结果、反事实、baseline 与 assertion owner；`DUR-001/L02/E12` 等 supporting evidence 不进入产品完成率。

发布能力由 `release_gate.py` 对机器声明、catalog eligibility、clean 同 revision trace、test
outcome 和 checksum 求交集。终态由测试中的可执行断言拥有，不再维护一个 gate 不读取的
`expected_terminal` 镜像字段。

文档不记录已退出用例或某次运行状态；历史证据留在对应 archive，当前矩阵始终由 catalog 计算。

## 运行

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

运行 diagnostic：

```powershell
uv run pytest evals/e2e_quality --e2e-scope=diagnostic -q -s
```

每次执行生成 manifest、逐用例 trace、pytest summary 和 checksum。API key 不写入归档。
历史 trace、skip、dirty worktree 或不同 revision 的通过结果均不能成为发布证据。

发布信任结果与运行测量保持分离。生成确定性测量报告：

```powershell
uv run python -m evals.e2e_quality.metrics_report `
  --trace-root data/e2e_traces --list-cohorts
uv run python -m evals.e2e_quality.metrics_report `
  --trace-root data/e2e_traces --profile <cohort-specific-profile> `
  --require-complete-profile --output data/e2e_metrics/report.json
```

reporter 只读取 checksum 完整、profile 兼容的 archive，并把缺失 usage 标为 unavailable；它不能改变 release gate 的发布判断。
