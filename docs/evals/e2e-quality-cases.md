# 正式环境核心用户结果 E2E

`evals/e2e_quality/evidence_catalog.py` 是用例身份、证据种类、入口、Provider profile、故障机制
和发布资格的唯一 owner。本文解释分类原则，不复制 test-name 映射。

## 1. 统一取证模型

产品只向用户暴露目标入口；E2E 不按 Conversation、Workflow、Project 给用户预先分流。系统在
目标被理解后，按执行所需的状态、治理和恢复机制选择内部路径：

```text
User Goal
  -> Semantic Decision
  -> Admission / Policy
  -> Capability Execution
  -> Execution Fact
  -> Semantic Verification
  -> Completion
```

E2E 必须从用户真实掌握的信息进入正式 HTTP 或 Application Use Case，自动断言用户结果和关键
反事实。执行后可以读取 trace、Receipt、Claim、Artifact 或 Project projection，但不能在用户
输入中指定 Tool、Agent、Plan、内部 ID、执行顺序或 Verifier 次数。

## 2. 发布准入

只有 catalog 中 `release_eligible=true` 的用例可以参与产品发布声明，并且必须：

1. 从独立 Web 进程的正式入口进入；
2. 使用真实模型、真实 PostgreSQL 和场景需要的真实 Provider；
3. 不注入 Proposal、Plan、Grant、Observation 或 Result；
4. 断言用户结果以及关键错误结果未发生；
5. 以真实进程终止验证恢复，不用进程内 hook；
6. 保存 trace envelope、manifest、summary 和 checksum。

Tool `ok=true`、数据库新增记录、child Agent `completed`、Verifier `passed` 或 scripted state machine
到达终态都不能单独作为产品 E2E。

## 3. 当前证据分类

| 分类 | 当前编号 | 证明范围 | 发布资格 |
| --- | --- | --- | --- |
| 应用能力 | E01–E05、E08–E14、E20、E22–E23、IP01 | 一个明确用户目标从正式入口获得结果 | 是 |
| 复杂交互 | L01–L06 | 能力选择、并发、恢复、预算和验证反事实 | 是 |
| Capability Profile / boundary eval | E16–E19、E21、E24 | 真实 MCP/A2A 可执行、超大返回受控，或研究边界对照 | 否 |
| Durable diagnostic | LT01–LT08、LT10–LT13 | Domain/Application/PostgreSQL/worker 协议 | 否 |

共 22 个 release、18 个 diagnostic。

以下旧分类已删除：

- E06/E07：只是复跑 E16–E19/E17 的 wrapper，没有新增用户结果；
- C01–C04：串接多个独立 Use Case，未证明一个组合用户目标；
- B03：历史失败证据与当前 IP01 使用相同实现和输入，不能在当前矩阵断言相反结果；
- LT09：对 Conversation 的 coverage 使用常量，没有实际执行 paired baseline。

历史 B03 archive 仍可证明当时 revision 的不足，但不属于当前可执行 catalog。

## 4. 能力与机制的边界

E01–E05、E08–E14、E20、E22–E23、IP01 证明应用能力。L01–L06 中的并发、恢复、预算和 receipt-bound revision 是
Runtime Mechanism 的反事实证据，不应被当作用户要选择的入口。E16–E21 证明 Provider/Connector
profile，也不自动等于产品能力。

一个新组合能力只有在存在单一、不可拆分的用户目标，并且最简单现有路径 baseline 失败时才能
新增 E2E。把 ingest、ask、research、save 分别调用一次，不能拼成组合能力证据。

## 5. 当前主要反事实

- 未确认、错误 digest、scope denied 时零副作用；
- Ask 不把模型回答隐式写成 Claim；
- 另一 personal knowledge 的事实不进入回答；
- capability unavailable 不选择语义相近的替代 Tool；
- budget exhaustion 不生成未经执行的答案；
- child Artifact 不自动成为父级 FinalMessage；
- restart/replay 不重算冻结 Command、不重复副作用；
- report 缺 Evidence、Verification 或 required mapping 时不能完成。

E05 只接受 `completed_verified` / `completed_with_limitations`，并要求非空 Digest 且每项具有来源；
partial 状态和空 Digest 不再被发布门禁当作 Research 成功。

## 6. Archive 与发布门禁

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

release gate 只接受 catalog、clean matching revision、passed summary、trace envelope 和 checksum
的交集。终态是 E2E 断言，不在 catalog 中保存第二份不可执行元数据。历史 archive、dirty
worktree、diagnostic 或 capability profile 均不能绕过发布条件。

本次执行了 L01、E22、E23 三个目标 release 旅程以及 E24 boundary diagnostic；其余当前
release 矩阵未在同一 clean revision 完整执行，因此仍不得声称 release ready。
