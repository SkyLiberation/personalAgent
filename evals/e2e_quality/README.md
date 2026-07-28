# 能力 E2E 与发布证据

本目录同时保存两类测试代码，但二者的证据等级严格分开：

- `release`：从真实 HTTP 用户入口进入独立 Web 进程，使用真实模型、真实
  PostgreSQL 和场景所需的真实 provider，走到 `completed` 或该反事实规定的
  fail-closed 终态。测试不得注入业务对象、调用内部 Service 推进流程、替换
  Gateway/Store/Model，也不得使用测试 hook 制造状态窗口。
- release 用例的用户输入必须表达目标用户会提出的目标和约束，不得点名内部 Tool、
  Agent、Artifact、verdict、Model 或执行顺序。精确 capability、并发、receipt 和
  provider binding 只能作为执行后的 trace/contract 证据，不能替代用户结果。
- `diagnostic`：用于真实外部 Profile 和专项定位；即使通过，也不能单独产生产品、
  组合或复杂主循环的发布声明。当前 E16–E19 分别验证 GitHub、GPT Researcher、
  Notion 和 capability-unavailable Profile，并由相应产品用例从正式入口消费。

唯一分类来源是
[`evidence_catalog.py`](evidence_catalog.py)。测试文件不另存一份 layer/status，
pytest 收集阶段会拒绝未登记用例，并按 catalog 自动添加 marker。业务事实仍由
生产代码中的 canonical owner 持有；catalog 只拥有“某测试证明什么”的元数据。

## 五个证据层

| layer | 读取的主要 canonical owner | 证明目标 |
| --- | --- | --- |
| `understanding` | Analysis Proposal、Admission、Accepted Analysis、TaskContract | 用户语义不被 validator 静默改写，Definition 编译正确 |
| `planning_control` | Plan Proposal、DecisionFeedback、AcceptedIntent、Command | 模型提案与确定性管控边界正确，无业务 fallback |
| `authority_gateway` | Confirmation、Grant、Gateway、Provider result/receipt | 未授权不调用，授权只缩权，执行只能经过 Gateway |
| `journal_recovery` | InvocationJournal、outbox、checkpoint、domain event | 崩溃恢复不重复副作用，不重新决定已冻结 Command |
| `verification_completion` | Observation、EvidenceAdmission、VerificationReport、CompletionReport | 执行事实不冒充 Goal 成功，报告齐全后才完成 |

layer 是断言焦点，不是缩短流程的许可。任何 `release` 用例仍必须从用户输入走完整
链路；负向用例可以结束在明确的 denied、waiting、terminated 等合法终态，但不得
伪造 `completed`。

## 当前基线

- `product_capability`：E01–E13，共 13 个正式用户旅程；
- `composite_capability`：C01–C04，共 4 个组合能力旅程；
- `complex_loop`：L01–L06，共 6 个主循环、恢复和验证旅程；
- `capability_profile`：E16–E19，共 4 个真实外部能力专项证据，不直接产生发布声明；
- `--e2e-require-complete-matrix` 会同时检查 E、C、L 三组 catalog 条目及对应测试节点，
  缺少任何条目或节点都会在收集阶段失败。
- 发布能力由 `release_gate.py` 对机器声明、catalog eligibility、clean 同 revision
  trace、test outcome 和 checksum 求交集；历史 trace、skip 或 dirty 工作树均不可信。

## 运行

运行完整 release 矩阵：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
```

当前命令收集 23 个 release 用例。测试进程会复用正式 Web 服务，但每个用户旅程开始前
通过正式 debug reset 清理业务事实；失败时保留服务临时目录并输出 trace archive 路径。

运行真实外部 Profile 专项用例：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
uv run pytest evals/e2e_quality/test_release_user_outcomes.py `
  --e2e-scope=diagnostic -q -s
```

按证据层运行：

```powershell
uv run pytest evals/e2e_quality --e2e-scope=release --e2e-layer=authority_gateway -v -s
uv run pytest evals/e2e_quality --e2e-scope=diagnostic --e2e-layer=journal_recovery -v -s
```

每次执行会生成 trace archive，包括环境指纹、HTTP 事件、canonical state 证据、
pytest 结果和校验和。API key 不写入归档。

发布投影：

```powershell
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

任一 E/C/L 声明不可信时返回非零。当前 gate 还要求目标 revision 与 archive revision
一致，且两者均为 clean；dirty 工作树下通过测试只能作为工程证据，不能成为发布证据。
