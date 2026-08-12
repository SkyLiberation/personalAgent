# Product E2E 与发布证据

**Product E2E 证明用户结果，release gate 判断这份证据能否用于目标 revision；二者都不负责证明框架效率。**
`evals/e2e_quality/evidence_catalog.py` 是用例身份、证据种类、入口、Provider profile、故障机制和发布资格的唯一 owner，本文只解释稳定规则，不复制会漂移的用例清单和数量。

## 1. 用户结果链

```text
User Goal
  -> Semantic Decision
  -> Admission / Policy
  -> Capability Execution
  -> Execution Fact
  -> Semantic Verification
  -> Completion
```

E2E 必须从用户真实掌握的信息进入正式 HTTP、CLI、消息入口或 Application Use Case，自动断言正确结果发生以及关键错误结果没有发生。Tool、Agent、Plan、内部 ID、执行顺序和结束判断只能在执行后的 trace、Receipt、Artifact 或 Project projection 中核对，不能写入用户 Prompt 替 Agent 决策。

## 2. 证据职责

| 证据 | 证明范围 | 不能证明什么 |
| --- | --- | --- |
| Product capability E2E | 一个用户目标和关键反事实从正式入口成立 | 所有场景、框架整体优势 |
| Complex interaction E2E | 能力选择、并发、恢复、预算、验证等组合行为 | 单个机制普遍优于其他实现 |
| Capability profile / boundary diagnostic | MCP、A2A、Provider 或治理边界可执行、可定位 | 产品发布能力 |
| Offline semantic eval | 某个 scorer 对应的语义质量 | 正式环境中的完整用户结果 |
| Release gate report | archive 对目标 revision 是否可信、eligible evidence 是否齐全 | token、成本、延迟、恢复率或维护性 |

应用能力用例证明用户结果；Runtime Mechanism 的反事实和 Provider profile 是路径证据或诊断证据，不是用户需要选择的产品入口。多个独立 Use Case 各自通过，也不能拼成一个未执行的组合能力。

## 3. 发布证据门禁

参与发布声明的用例必须同时满足：

1. 由 catalog 计算为 `release_eligible`；
2. 从正式入口经过生产主路径；
3. 使用目标场景要求的真实模型、数据库和 Provider；
4. 不注入 Proposal、Plan、Grant、Observation 或 Result；
5. 自动断言用户结果和关键反事实；
6. 需要恢复时以真实进程终止验证，不使用进程内 hook；
7. 保存 trace envelope、manifest、summary 和 checksum；
8. archive 与目标 clean revision 一致且完整通过。

Tool `ok=true`、数据库新增记录、child Agent `completed`、Verifier `passed` 或 scripted state machine 到达终态，都不能单独成为发布证据。

## 4. 关键反事实族

具体用例和断言以 catalog 与测试代码为准。当前矩阵应覆盖的稳定反事实包括：

- 未确认、错误 command ref 或 scope denied 时没有副作用和敏感内容泄漏；
- Ask 不把模型回答隐式写成长期知识；
- 其他 principal 的个人知识不进入回答；
- capability unavailable 时不选择语义相近但不等价的替代资源；
- budget exhaustion 时不生成未经执行或未经验证的完成答案；
- child Artifact 不自动成为父级 FinalMessage；
- restart/replay 不重算冻结 Command、不重复已提交副作用；
- 恢复后 owner 与 execution ref 不混淆，跨 scope 读取 fail closed；
- 同一次失败可按 run ref 定位到 Policy、Admission、Execution、Verification 或 Completion 阶段；
- required report 缺 Evidence、Verification 或 mapping 时不能完成。

新反事实只有在真实用户场景的 baseline 已暴露错误，或它保护明确安全不变量时才进入矩阵；不能为了展示架构对象而新增用例。

## 5. Archive 与运行

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

`release_gate.py` 对 catalog eligibility、clean matching revision、test outcome、trace envelope 和 checksum 求交集。一次定向运行、历史 archive、dirty worktree、diagnostic 或 capability profile 不能绕过发布条件。

archive schema 3 通过 `MeasurementProfile` 冻结 runtime/model/prompt/budget/fixture/repetition，通过 `CaseMeasurement` 保存权威 usage 与恢复事实。`metrics_report` 只聚合同 profile、checksum 完整的 archive；缺失值不记零，diagnostic 不进入产品完成率。当前没有第二个真实 runtime profile，因此报表只建立基线，不给出框架 A/B 结论。
