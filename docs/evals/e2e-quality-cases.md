# 正式环境核心用户结果 E2E

`evals/e2e_quality/` 从原始 `EntryInput` 开始，使用 `Settings.from_env()`
装配的真实模型与正式运行时，验证用户请求能否形成真实、可验证、可恢复的结果。

这里禁止替换 `_analyze_with_model`、注入 `TaskAnalysis`、Mock Store 或预先提供
Plan。PostgreSQL 测试库、临时目录和 Graphiti 独立 group prefix 只负责数据隔离，
不替换业务组件。

## 验证链路

```text
raw EntryInput
  -> live Task Analysis
  -> TaskContract / GoalGraph
  -> TaskRuntimeProjection
  -> live Planning / Executive Proposal
  -> Governance Admission
  -> Confirmation / ExecutionGrant
  -> Gateway Execution
  -> Observation
  -> Goal VerificationReport
  -> CompletionReport
  -> EntryResult + durable terminal checkpoint
```

E2E 直接读取生产 checkpoint 中的 canonical state，并输出
`LIVE_E2E_TRACE=<json>`，同时默认落盘到 `data/e2e_traces/<archive-run-id>/`。
归档包含输入、模型调用次数、Task Analysis、Contract、Runtime、AgentEvent、
ExecutionEvent、Verification、Completion、最终输出和 pytest 断言结果。

每次归档包含：

- `manifest.json`：Git commit/dirty state、Python/平台、模型和 Prompt 版本；
- `*.trace.json`：逐用例、逐阶段 canonical trace；
- `summary.json`：通过/失败/跳过数、各阶段耗时和失败 traceback；
- `checksums.sha256`：全部 JSON 文件的 SHA-256 完整性校验。

归档器只存在于 `evals/e2e_quality`，不修改生产 checkpoint、业务 Model 或
Store。输出目录位于已有 `.gitignore` 覆盖的 `data/` 下，CI 将整个目录上传为
Artifact。

## 当前用例

| 场景 | 必须证明 |
| --- | --- |
| 简单回答 | 真实模型参与 Task Analysis；生成单 response Goal；返回非空回答；Goal verified 后 Task 才完成；没有伪造 ExecutionGrant |
| 复合写入再回答 | 真实模型拆出 external_state + response；第二 Goal consumes 第一 Goal 输出；确认前零写入；确认后使用精确 Grant 写入测试库；两个 Goal verified 后才完成 |
| 缺少输入的不支持副作用 | 真实模型可以 clarify、reject、暂停等待能力/输入，或交给能力边界终止；无论路径如何都不得产生写入、VerificationReport 或 `task_completed` |

专项 Task Analysis、RAG、Research、MCP、A2A 等 suite 仍负责各自的统计指标；
但不能代替本套从原始输入贯穿最终结果的 live E2E。

## 运行

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality -v -s
```

普通本地运行在缺少 PostgreSQL 或正式 structured model 时会 skip。设置
`PERSONAL_AGENT_REQUIRE_LIVE_E2E=true` 后，缺失配置必须失败；CI 使用强制模式，
不能再以打桩或全部 skip 冒充 E2E 通过。

## 失败归因

- Task Analysis 输出错误 Goal、依赖或资源语义：真实模型 / Prompt / Schema。
- ProcedureGrant、InvocationJournal 跨 checkpoint 丢失：Runtime state update。
- 未确认就产生写入：Governance / Procedure / Gateway。
- Action 成功但 Goal 未验证：GoalVerifier。
- Run 结束但 Task 仍 active：Executive loop / EntryResult 状态映射。
- 缺少能力或输入却产生成功：Capability / completion boundary。
