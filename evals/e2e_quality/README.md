# 能力 E2E 与发布证据

本目录包含两种证据，唯一分类 owner 是
[`evidence_catalog.py`](evidence_catalog.py)：

- `release`：从独立 Web 进程的正式 HTTP/Application 入口进入，使用真实模型、真实
  PostgreSQL 和场景所需的真实 Provider，断言一个用户目标及关键反事实；
- `diagnostic`：验证外部 Capability Profile 或 durable runtime 协议，只用于定位，不能单独
  产生产品发布声明。

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

## 当前矩阵

- `product_capability`：E01–E05、E08–E14、E20、E22–E23、IP01，共 16 个应用能力旅程；
- `complex_loop`：L01–L07，共 7 个用户旅程及其 runtime 反事实；
- `capability_profile/boundary_evaluation`：E16–E19、E21、E24，共 6 个外部能力或边界专项证据；
- `durable_investigation`：LT01–LT08、LT10–LT13，共 12 个 in-process runtime diagnostic；
- release 共 22 个，diagnostic 共 18 个。

当前没有组合能力 release 用例。原 C01–C04 只是串接独立 Use Case，未证明一个不可拆分的用户
目标，已退出 catalog；B03 是历史失败 archive，不再对当前实现执行相反断言；LT09 没有实际运行
Conversation paired baseline，也已删除。E06/E07 只是复跑 E16–E19/E17 的 wrapper，同样删除。

发布能力由 `release_gate.py` 对机器声明、catalog eligibility、clean 同 revision trace、test
outcome 和 checksum 求交集。终态由测试中的可执行断言拥有，不再维护一个 gate 不读取的
`expected_terminal` 镜像字段。

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
