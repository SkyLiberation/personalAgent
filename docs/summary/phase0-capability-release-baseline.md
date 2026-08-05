# Phase 0 能力目录与发布基线

本文记录 capability-first 重构后的当前实现和验证事实，当前架构边界由
[`core-architecture-current-state.md`](core-architecture-current-state.md) 记录；尚未落地的设计只进入
[future 索引](../future/README.md)。E01–E05、E08–E14、E20、E22–E23、IP01、L01–L06 与发布声明的唯一机器映射由
[`release_gate.py`](../../evals/e2e_quality/release_gate.py) 拥有。

## 当前结论

截至 2026-07-31，Phase 1–5 的生产主路径代码和当前定向工程 E2E 已落地；发布资格仍未
建立。必须区分当前完整工程证据和 clean-revision release gate：

| 结论 | 状态 | 依据 |
| --- | --- | --- |
| 2026-07-24 历史工程 E2E | `passed` | 23/23 selected passed，1506.36 秒，archive `20260724T144409.800183Z-53716-a052c7cd` |
| 历史 GitHub/Notion MCP wrapper | `passed_historical_only` | 旧 E06 曾复跑 E16/E18/E19；因重复记功已退出当前 catalog，archive `20260725T064548.518818Z-19688-d08d031f` |
| 历史 tokeness GPT Researcher A2A | `passed`（旧模型定向） | E17 223.32 秒、L04 228.40 秒，分别为 archive `20260725T084944.789762Z-42408-b3b97220`、`20260725T085407.393906Z-28364-8e0c1122` |
| 历史 `gpt-5.6-luna` 尝试 | `configured_not_executable` | 最小 Provider 请求返回 404，E01/E17 正式 HTTP 均 fail closed |
| `gpt-5.6-terra` 尝试 | `rejected_by_runtime_contract` | E01 通过；E17 因顶层 union schema/retry 超时，修正 schema 后复杂请求仍超过 120 秒 |
| 当前 `deepseek-v4-flash` 配置 | `target_completed_release_not_established` | 显式 `json_object` Adapter + 关闭 thinking 后，IP01 最终 archive 已交付报告；完整 clean-revision 矩阵仍未建立 |
| 当前 catalog/gate 门禁 | `passed_current_engineering_evidence` | 2026-08-03：相关 contract 28 passed；40 个 E2E 可收集，其中 release 22、diagnostic 18 |
| 上一完整 release E2E | `historical_passed_engineering_evidence` | 旧版 E01–E13/C01–C04/L01–L06 共 23/23 passed，archive `20260726T011631.187395Z-20684-4a62da6a`；L01–L06 语义均已改变，不能证明当前 catalog |
| 当前自然复杂场景 | `passed_targeted_engineering_evidence`；L06 为 `unstable_diagnostic_evidence` | L01–L05 在同一批次通过。L06 历史：曾因旧“两次 verifier”白盒断言失败（archive `20260727T163802.147366Z-12512-71873e6b`），移除该错误 claim 后定向通过（archive `20260727T164815.081968Z-14456-e1196ad4`）。2026-07-30 改为凭据引用终止（[ADR 0009](../adr/0009-verified-final-message-receipt-reference.md)）后重测 9 次真实模型运行，**5 次通过**，4 次因 verifier 持续 `needs_revision` 而到不了 passed 凭据；因此 L06 当前不作为通过声明 |
| 当前外部自然场景 | `passed_targeted_engineering_evidence` | E17/E19/L04 在 archive `20260727T162913.553817Z-9428-c723ad92` 中通过；进一步移除 Prompt 内预期答案后，E16/E18 2/2 passed，archive `20260727T165211.554901Z-17344-3e4bc060`。用户只表达数据源或深度研究结果，不指定 MCP Tool、Agent ID、Artifact、答案或执行顺序 |
| Conversation clarification | `passed_targeted_engineering_evidence` | E01 baseline `20260729T033100.290836Z-35328-02db4988` 证明模糊新请求被旧答案冒充完成；同输入修复后通过，archive `20260729T033304.468248Z-28272-e91b6630` |
| Conversation governed save | `passed_targeted_engineering_evidence` | B01 证明旧 Conversation 无可恢复操作；B02 archive `20260729T031804.415533Z-15972-214cb81c` 证明控制语义污染；E14 exact-span 修复后 22.00 秒通过，archive `20260729T033339.065714Z-22692-16415241` |
| Goal-entry workspace recall | `passed_targeted_engineering_evidence` | baseline `20260803T142413.474927Z-4864-39fedcf5` 无 Observation 即误报未找到；补 canonical list capability 后 L01 `20260803T152242.957743Z-388-d0850c85` 通过 |
| Goal-entry governed delete | `passed_targeted_engineering_evidence` | baseline `20260803T142932.564456Z-23720-19ba8517` 只能文字确认；E22 `20260803T152242.957743Z-388-d0850c85` 覆盖当前条目选择、确认、scope 与 replay |
| Goal-entry durable handoff | `passed_targeted_engineering_evidence` | baseline `20260803T143007.354551Z-26256-84d0bf1d` 幻觉不存在的 specialist；E23 `20260803T151935.921382Z-27308-be5eadbf` 创建一个 canonical Project 并返回引用 |
| Research boundary paired eval | `diagnostic_boundary_evidence` | E24 `20260803T143230.864789Z-6460-dbd005fd` 未证明 ResearchRun 对开放调查优于 Conversation/Project；保持 Scheduled Intelligence 边界 |
| Workspace answer verification | `passed_targeted_engineering_evidence` | B04 证明互斥结论被回答组装器误标 supported；E20 独立 Verifier 返回 `needs_revision/conflicted`，archive `20260731T064446.108938Z-8804-52b29d3c` |
| Durable Investigation live closure | `target_passed_release_not_established` | 历史 B03 archive 证明当时 revision 的 verification repair 死锁；IP01 archive `20260729T101501.732689Z-53628-6c5f02f2` 完成 Plan v3、3/3 outcomes、5 条 admitted evidence、可读报告与 Completion Gate。B03 不再对当前实现执行相反断言 |
| Clean revision 发布资格 | `not_established` | 完整 archive 与目标 worktree 均为 dirty；gate 必须 fail closed |

GPT Researcher 已不再依赖原异常 endpoint。正式 `8001` 服务从相邻 `personalAgent/.env`
读取 `STRUCTURED_API_KEY`、`STRUCTURED_BASE_URL` 和 `STRUCTURED_MODEL`，映射到唯一
OpenAI-compatible tokeness Provider；凭据不复制到 GPT Researcher 仓库。当前外部
tokeness 容量故障会使主 Agent 与 GPT Researcher 同时 fail closed。当前只能声明上述
自然用户场景的定向工程证据；完整工程矩阵与发布资格都需要在当前 catalog 上重新建立。

当前生成式模型 canonical fact 为 `STRUCTURED_MODEL=deepseek-v4-flash`，结构化输出 profile 为
`json_object`；该 deployment 还需关闭 thinking 才在 IP01 复杂 typed contract 上稳定通过。
Conversation、Structured decision、Graphiti、LangExtract 以及
GPT Researcher FAST/SMART/STRATEGIC 均从 canonical `STRUCTURED_*` 解析。embedding 仍是
独立的本地/多语种 384 维契约，transcription 也未改变。此前
tokeness 对先前 luna 请求返回 HTTP 404；terra 暴露复杂 RootModel union 与延迟问题。
object-root schema 与 `gpt-5.4-mini` 曾通过完整 23/23 工程矩阵；L01–L06 与 E16–E19
自然用户场景改版后已完成上述定向验证，但当前 catalog 的完整矩阵尚未重跑，不能沿用旧
archive 建立发布声明。

## 本次链路收敛

- Web、CLI、飞书等正式入口统一进入 `ConversationService`，旧
  `Task/GoalGraph/AdaptivePlanner/ExecutiveController` 入口和相应用例已删除，不保留
  alias、fallback 或双轨写入。
- 模型每轮只产生 `FinalMessage | ContinueTurnProposal`；typed ToolResult、Agent
  status/Artifact 和 `DecisionFeedback` 回到下一轮模型上下文。
- Tool 校验、权限和执行统一经过 `ToolExecutor`；Application 通过
  `InteractionToolPort` / `InteractionAgentPort` 依赖执行能力。
- Knowledge delete/restore 使用 immutable governed command、单一 command digest、receipt 和
  restart/replay 约束，错误 digest 与重复副作用均由 E04/E10 反事实覆盖。
- A2A Artifact 不再误路由到 upload-only `inspect_artifact`；cancelled status 不抹除已返回
  Artifact；同一 Agent 已返回 Artifact 后的重复委托被拒绝。最终 E17 trace 自动断言
  `agent_calls == 1`，历史问题链路约 4 分钟，修复后目标用例约 2 分钟，完整矩阵中的
  C04 call 为 87.7 秒。
- Research 成功断言不再接受 `running`；E05/C01/E13 只接受终态，并要求 digest 或明确
  limitation。最近单跑 C01 为 `completed_with_limitations` 且 `digest != null`，160.60 秒。
- GPT Researcher OpenAI-compatible Adapter 支持 tokeness SSE；空 SSE、`[DONE]` 和
  cancellation 文本不能成为成功 Artifact。本地多语种 embedding contract 为 384 维，
  research workload 限制为 1 iteration、1 subtopic、1 result/query 和 400 words。
- OpenAI SDK 内部 retry 已关闭，`max_retries` 的唯一 owner 是
  `RetryingStructuredModelClient` 的 typed-operation retry；release fixture 同时物化
  OpenAI/Structured timeout 与 retry，避免父进程 120 秒 profile 在子进程退回 30 秒。
- OpenAI/httpx 的 connect/read/write/pool timeout 不是整次响应 deadline；持续发送 SSE
  chunk 会重置 read timeout。`OpenAIModelClient` 现对完整 Provider 调用和 structured
  stream 消费执行 wall-clock deadline，超时关闭 client 并返回 typed timeout。E09 从旧
  archive 的 21702.94 秒降至定向 92.27 秒，并在完整矩阵中再次通过。
- debug reset 不再截断 `checkpoint_migrations`；schema migration 事实由迁移器唯一拥有，
  业务/runtime 数据仍按正式 debug API 清理。

## 事实与所有权

| 事实 | Canonical owner / 唯一写入口 | 当前处理 |
| --- | --- | --- |
| Interaction 执行与 trace | `ConversationService` / Interaction journal | 正式入口唯一主循环；只保存 committed inputs，不创建强制 Plan |
| 本地 Tool 定义 | composition root → `ToolExecutor.register` | 从实际 registry 派生，不维护第二份 Tool 表 |
| Tool 调用治理与执行事实 | `ToolExecutor` | Application 只依赖 `InteractionToolPort` |
| MCP 远端名称/schema | MCP `tools/list` discovery | 与 Host mapping、风险和权限分开 |
| A2A profile 与 child lifecycle | `AgentGateway` | status、Artifact 和父级 FinalMessage 分离 |
| Knowledge revision/delete/restore | Knowledge lifecycle aggregate/service | governed command 是唯一副作用写入口 |
| Provider 当前健康 | 实时 credential/health observation | 未观察时不得根据配置推断健康 |
| 生成式模型部署选择 | `STRUCTURED_MODEL` / deployment config | Adapter-specific 值默认确定性派生；当前工作树为 `deepseek-v4-flash` + `json_object` |
| Release eligibility | `evidence_catalog.py` | `claim_kind` 与 `release_eligible` 共同判定 |
| 同 revision 实际通过 | trace manifest/summary/envelope/checksum | dirty、commit 不同、skip、失败或校验错误均 fail closed |
| 发布能力基线 | `release_gate.py` 派生投影 | 不进入数据库、checkpoint 或 Runtime capability state |

`src/personal_agent/orchestration/capability_inventory.py` 只消费 application assembly、
registry、accepted MCP mapping 和 registered Agent profile，返回临时有效能力集合；它不
创造 semantic intent，也不提供 Release trust。

## E2E 验收矩阵

| 分组 | 当前声明 | 当前证据 |
| --- | --- | --- |
| 应用能力 E01–E05、E08–E14、E20、IP01 | 当前完整状态未建立 | 旧 archive 只能作为历史工程证据；当前 14 个产品旅程尚未形成 clean 同 revision archive |
| 复杂主循环 L01–L06 | 各场景定向通过，非单一完整 archive；L06 不稳定 | L01–L05 同批通过；L06 在 2026-07-30 的 9 次真实模型运行中 5 次通过，不作为通过声明 |
| 外部 Profile | E16–E19 定向通过，E21 已入 catalog 未执行 | Profile 是 diagnostic，不单独产生产品发布声明 |

其中：

- E01 覆盖直接回答、澄清、连续会话，并反证没有无意义 Task/Receipt；
- E04/E10 覆盖 governed delete/restore、错误 digest 拒绝、重启恢复和不重复副作用；
- E14 覆盖自然语言选择 user message 中的 exact knowledge span、Admission 逐字来源校验、确认前
  零写入、Command 重启恢复、scope denied、精确结论 Claim、控制语义零写入、Receipt 和 replay；
- E05/E13 覆盖 Research 终态、digest/source 和 limitation；E05 现在拒绝 partial/空 digest；
- E16/E18 使用真实 GitHub/Notion 数据源请求和 MCP gateway，E19 以自然请求覆盖资料源
  未连接时的 limitation；
- E17/L04 使用真实深度研究请求和 GPT Researcher adapter/profile，并在执行后断言
  child Artifact 与父级用户结果分离；
- L01–L06 分别覆盖自然个人知识回忆、最近记录与知识缺口综合、崩溃后从 canonical facts
  恢复、深度安全研究、budget fail-closed，以及用户要求的语义审查与 receipt-reference 修订。
- 两轮 `needs_revision -> passed` evaluator-optimizer 状态机属于 Runtime Conformance，
  由 scripted 低层测试验证；release E2E 不要求真实用户控制 verifier 调用次数。

Phase 3 的通用 MCP Host 边界由 E16/E18/E19 分别取证；不再通过 E06 wrapper 重复执行后冒充
一个额外产品目标。

## 架构与专项门禁

截至 2026-07-26 的实际执行结果：

```text
scripts/check_layers.py: cycles=none, forbidden_edges=0
tests/: 637 passed
Generative provider config contract: passed, 7/7 model slots resolve to gpt-5.4-mini
Minimal luna provider probe: failed, HTTP 404 no available providers
Formal luna E01/E17: failed closed before user result / A2A delegation
Minimal terra plain/strict-object probes: passed
Formal terra E01: passed, 110.30 seconds
Formal terra E17: failed, HTTP client timeout at 300 seconds after schema retries
AgentTurnDecision schema: passed, object root with nested anyOf and no oneOf
Formal gpt-5.4-mini E01: passed, 77.16 seconds
Formal gpt-5.4-mini E17: passed, 171.31 seconds
GPT Researcher scoped Ruff: passed
GPT Researcher unit tests: not executed; host dependency resolution requires MSVC link.exe
GPT Researcher container SSE: passed; empty SSE rejection: passed
GPT Researcher local embedding: passed, dimensions=384
Scoped Ruff for changed Provider/E2E/runtime files: passed
Provider wall-clock deadline + interaction regression: 39 passed
Formal E09 after deadline fix: passed, 92.27 seconds
Previous full release engineering matrix: 23 passed, 0 failed, 0 skipped, 1777.44 seconds
Previous full archive: 20260726T011631.187395Z-20684-4a62da6a, exit_status=0
Current natural L01-L05 batch: passed; L06 user result passed but obsolete two-call assertion failed
Current L01-L06 batch archive: 20260727T163802.147366Z-12512-71873e6b, exit_status=1
Current corrected L06: passed, 73.73 seconds
Current corrected L06 archive: 20260727T164815.081968Z-14456-e1196ad4, exit_status=0
Current natural E17/E19 plus L04 batch: passed within 5/5 batch
Current external base archive: 20260727T162913.553817Z-9428-c723ad92, exit_status=0
Current answer-free-prompt E16/E18: 2 passed, 135.43 seconds
Current E16/E18 archive: 20260727T165211.554901Z-17344-3e4bc060, exit_status=0
Current scoped low-level/catalog tests: 57 passed
Full-repository Ruff: 13 pre-existing findings outside this change scope
```

上述命令块是截至 2026-07-26/27 的历史工程证据，不是当前工作树的实时门禁。2026-07-30
重新执行 `uv run python scripts/check_layers.py` 得到：

```text
packages=14 edges=53
unknown_packages=none
missing_packages=none
cycles=none
forbidden_edges=0
OK: explicit package DAG satisfied
```

此前的 `unknown_packages=['context', 'skills', 'verification']` FAIL 是假阳性：三个目录只剩
`__pycache__/*.pyc`，是已删除包的编译残骸，而 `discover_packages()` 以“目录存在”定义 package。
已删残骸并要求目录内至少有一个 `.py`。因此现在可以声明 package DAG gate passed。即使架构检查通过，
也只说明依赖图没有循环或 forbidden edge，不能替代上面的用户结果 E2E。

2026-07-31 当前工作树实际门禁：

```text
tests/: 720 passed, 4 warnings
E2E catalog contract: 8 passed
Release catalog collect-only: 26 collected, 18 deselected, complete matrix accepted
Full-repository Ruff: passed
compileall src/evals/tests: passed
canonical document local links: 16 documents, no broken links
release gate: fail closed
release gate reasons: target_revision_dirty, missing_same_revision_passing_trace
```

Graph evidence 边界的 baseline、Provider 删除和净复杂度见
[ADR 0012](../adr/0012-graph-retrieval-evidence-only-boundary.md)。这些结果是当前 dirty
worktree 的工程证据，不能升级成 release eligibility。
本次 GPT Researcher 修复只改变 compose Provider 配置，通过 `--no-build --force-recreate`
重建容器，没有产生冗余镜像。当前 8001 容器的 non-streaming tokeness 路径已由 E17、
E07 和 C04 验证。此前 clean build 在 Docker Hub base-image metadata 阶段超时，因此
clean build reproducibility 尚未建立，但不影响本次已执行容器 profile 的工程证据。

## 执行命令与发布门禁

完整工程验收命令：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
```

发布投影命令：

```powershell
uv run python -m evals.e2e_quality.release_gate --trace-root data/e2e_traces
```

门禁只接受同时满足以下条件的交集：

1. catalog 条目分类正确且 `release_eligible=true`；
2. 从真实 HTTP 进程进入，使用真实模型、PostgreSQL 和场景要求的真实 Provider；
3. manifest commit 等于目标 revision，manifest 与目标工作树均为 clean；
4. summary `exit_status=0`，具体 test outcome 为 `passed`，不是 skip；
5. 对应用例至少有一个 passed trace envelope；
6. archive run identity 一致且全部 JSON checksum 有效。

上一完整矩阵曾满足第 2、4 条，但当前已删除 E06/E07/C01–C04，并新增 E14/E20/IP01/E21，
因此不再匹配当前 catalog；
当前定向场景也不是完整矩阵。第 3 条仍不满足，因为 archive manifest 与目标工作树均为 dirty。因此
release gate 缺少 same-revision complete matrix 并 fail closed 是预期结果。

## 剩余风险

1. 必须在提交后的 clean revision 重跑当前完整矩阵，才能建立发布资格；旧 23/23 与本次
   自然场景定向通过都只构成各自 dirty worktree 的工程执行证据；
2. Docker Hub metadata 网络恢复后应按当前 Dockerfile clean build GPT Researcher，
   重建正式 8001 容器并至少重跑 E17；
3. GPT Researcher PDF 生成日志有中文字体 `.notdef` 警告；文本 Artifact 与 E2E 断言通过，
   但 PDF 中文视觉可读性尚未验证；
4. `conversation_id`、`interaction_run_ref` 等仍在部分 Interface/Application 边界以受格式
   约束的字符串传递，尚未全部收敛为独立 Value Object；不得把当前实现描述成 typed
   identity 目标已经完全闭合。

## 决策所有权

Capability inventory 是确定性 Runtime Projection，只反映实际注册与观察事实，不新增
intent。Release gate 是确定性 Completion/Admission：它只接受或拒绝能力发布声明，缺
证据时返回原因，不补 catalog、不重写 trace，也不使用 Runtime availability 兜底。
