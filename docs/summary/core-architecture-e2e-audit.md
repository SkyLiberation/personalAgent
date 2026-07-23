# 核心架构的历史 E2E 证据矩阵

本文是 [`core-architecture-current-state.md`](core-architecture-current-state.md) 中架构声明的
发布证据索引。测试分类的唯一 owner 是
[`evidence_catalog.py`](../../evals/e2e_quality/evidence_catalog.py)；业务事实仍分别由
`TaskContract`、`TaskRuntimeProjection`、Command、Grant、Journal、VerificationReport
和 CompletionReport 持有。

本文中的 E01–E17 是架构边界/Profile 证据编号，不是 Phase 0 产品能力证据。
产品能力 E01–E13、组合 C01–C04 及当前空发布基线见
[`phase0-capability-release-baseline.md`](phase0-capability-release-baseline.md)。
旧编号即使历史通过，也不能被 release gate 当作产品能力证明。

## 发布级证据标准

一个用例只有同时满足以下条件才计入 release E2E：

1. 从原始用户输入和外部 HTTP 入口进入独立 Uvicorn 进程；
2. 使用真实 structured model、真实 PostgreSQL checkpoint，以及场景需要的真实 provider；
3. 不注入 Proposal、Plan、Grant 或 Result，不替换 Model、Gateway、Store，不使用故障 hook；
4. 正向路径走到真实完成，负向路径走到明确的 denied、waiting 或 fail-closed 终态；
5. 断言直接读取 canonical owner，而不是仅匹配 UI 文本或日志；
6. 故障恢复通过终止和重启真实服务进程制造，不以进程内 callback 代替。

## 旧架构 E01–E15 实现

截至 2026-07-21，旧架构 catalog 包含 15 个 release 用例。下表只保留历史诊断价值；
它不参与 Phase 0 产品能力基线。新的完整产品矩阵会在收集阶段检查 E01–E13 的
`product_capability` 条目，目前会按设计报告全部缺失。

最近一次完整矩阵尝试归档为
`20260721T170152.613415Z-16604-a4f4cc45`：15 个用例均被实际收集和执行，但在 E04
第二段请求开始，Highway structured endpoint 返回 `403 NOT_ENOUGH_BALANCE`，后续依赖
真实 Task Analysis 的用例按设计 fail closed。因此该归档是“矩阵可执行、正式依赖额度
不足”的失败证据，不计为全矩阵通过。此次运行同时发现并修复了两个额度耗尽前的本地问题：
模型 Proposal schema 与 `BoundedAction.max_iterations` 下界不一致，以及 RunSnapshot 将
`terminated` lifecycle 误显示成 `completed`。

| 编号 | release 终态与证明重点 | 最近通过 trace |
| --- | --- | --- |
| E01 | 简单回答：Goal verification 先于 Completion，无伪造执行 Grant | `20260721T131447.509625Z-38244-23045807` |
| E02 | 复合写入再回答：确认、真实写入、双 Goal 验收与重启恢复 | `20260721T141011.170913Z-28992-f59f02cf` |
| E03 | 缺少副作用输入：无 Journal、Verification 或虚假 Completion | `20260721T132010.675031Z-32344-945eb079` |
| E04 | 删除确认边界：确认前目标仍存在且零 mutation effect | `20260721T142737.434978Z-17364-74fbfb26` |
| E05 | 缺失 provider：在 Grant/Journal 前 fail closed | `20260721T145249.765786Z-41408-046777e9` |
| E06 | 重启后拒绝删除：无 confirmation-bound Grant、Receipt 或副作用 | `20260721T142930.295063Z-11516-58acedbb` |
| E07 | Gateway dispatch 后进程崩溃：恢复消费同一结果且外部写入恰好一次 | `20260721T163137.492753Z-5920-ebd033ee` |
| E08 | Task Analysis 冻结：Accepted Analysis 等于被接受 Proposal，无 Admission 改写 | `20260721T143107.851966Z-21348-585cbf91` |
| E09 | 资源所有权：shared/local resource 只由 Compiler 归属且不跨 Goal 泄漏 | `20260721T152422.633324Z-43280-1ef8fbb1` |
| E10 | 编译原子恢复：Contract、初始 Runtime、CompilationCommit 同时恢复 | `20260721T162809.907623Z-45380-40fa6886` |
| E11 | required provider 不可用：持久化 acquisition request，保留已验证 Goal 和原 Plan | `20260721T165528.536129Z-39276-fb7c053c` |
| E12 | Planner Admission：非法 Plan 只产生 typed feedback 和模型修订，无代码修补 | `20260721T164406.268967Z-33868-9cef2567` |
| E13 | 跨用户资源：scope denial，不产生越权 Observation/Grant/Journal/Receipt | `20260721T153606.250506Z-38960-c4dc305d` |
| E14 | acquisition 批准：批准事实不冒充环境 availability 或 provider binding | `20260721T151225.697347Z-27372-ca25e75e` |
| E15 | 不可信 provider 内容：保留 instruction taint，不能进入语义验收证据 | `20260721T161340.520054Z-28092-2471ceac` |

## 架构设计与反事实

| 设计边界 | 对应 E2E | 没有该设计会出现的错误 | canonical assertions |
| --- | --- | --- | --- |
| Task Analysis Proposal / Admission / Accepted Analysis | E03、E08 | validator 补写或改写用户语义，失败时仍编译任务 | proposal lineage、admission verdict、accepted body、零下游副作用 |
| TaskContract / Runtime Projection 分治 | E02、E09、E10 | 状态更新覆盖 Goal 定义，资源归属漂移，崩溃留下半任务 | immutable Contract、Runtime revision、`resources_for_goal`、CompilationCommit |
| Deliberative Plan 与 Planner Admission | E11、E12 | 缺能力时重写已完成事实，非法 Plan 被 deterministic fallback 修好 | PlanDefinition 不变或显式 revision、DecisionFeedback、零静默 patch |
| Executive Proposal / AcceptedIntent / Command | E02、E08、E13 | 模型建议直接成为权限；scope-expanded payload 被执行 | DecisionAudit、AcceptedIntent、immutable/superseding Command digests |
| Capability 完整等价类与 acquisition | E05、E11、E14 | 按名称或相似度选择不等价 provider；批准请求被当作能力已可用 | full class dimensions、零 Grant、AcquisitionProjection、awaiting environment |
| Confirmation 与 Grant | E04、E06 | idempotency key 或准备态 Grant 冒充用户确认 | AuthorizationDigest、ExecutionCommandDigest、confirmation ref、零写入 |
| Gateway 与 Journal/outbox | E02、E07 | graph node 直调 provider；崩溃恢复重复副作用 | provider-bound Grant、reserved/dispatched/observed Journal、唯一 provider effect |
| Execution fact / Evidence / Goal verification / Completion 分层 | E01、E02、E03、E15 | tool result 一出现就宣布 Goal 或 Task 成功；注入文本成为验收依据 | ExecutionFactReport、EvidenceAdmission、GoalVerificationReport、CompletionReport |
| Checkpoint 与进程恢复 | E02、E07、E10 | 重启后重新决定 Command、重复执行或恢复出不一致 aggregate | 同 task/command digest、连续 event cursor、原子 compile triple、一次副作用 |

## E11 的边界说明

E11 不再声称“任何 capability gap 都必须触发 PlanPatch”。用户明确要求 `ZetaCloud`，
而当前 portfolio 没有同时覆盖 provider、domain、resource type、operations、freshness、trust、
authority、egress、evidence 与 failure semantics 的完整等价类。合理行为是：

1. 第一 Goal 经确认、Gateway、Journal、Receipt 和 Verification 正常完成；
2. Executive 不删除用户要求的 provider，也不选择一个“最像”的替代能力；
3. 第二 Goal 产生并持久化 `CapabilityAcquisitionRequest` 后暂停；
4. 已验证 Goal、外部写入、TaskContract 和原 Plan 均不被回滚或重写；
5. 用户批准 acquisition 仍不等于环境已出现该 provider，这一反事实由 E14 证明。

这说明 PlanMonitor 的合理最小动作在该场景是零 patch。只有真实 observation 使既有执行策略失效、
且模型提出的 patch 通过 Plan Admission 时，PlanPatch 才有存在依据。

## 运行与判定

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality/test_release_user_outcomes.py `
  --e2e-scope=release -v -s
```

单个历史 trace 只证明对应架构场景曾通过。产品发布必须另行通过 Phase 0 release gate；
diagnostic、架构 release 和 Capability Profile 都不能替代产品用户旅程。
