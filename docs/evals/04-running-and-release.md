# 运行、归档与发布

**当前 E2E 执行分为 9 条 Product E2E 和 25 条 supporting evidence；12 条 scripted Investigation Runtime Conformance 在独立 suite。**

## 收集当前矩阵

```powershell
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=release
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=diagnostic
```

当前实际结果：

```text
release selection: 9
diagnostic selection: 25
runtime conformance selection: 12
catalog total: 46
```

## 执行机器 release selection

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces"
uv run pytest evals/e2e_quality --e2e-scope=release `
  --e2e-require-complete-matrix -q -s
```

该命令需要真实 PostgreSQL、真实 structured model，并按 case profile 需要 Web Search、Firecrawl、GitHub MCP、Notion MCP 或 GPT Researcher A2A。skip 在强制 live 模式下会转为失败。

## 执行 diagnostic selection

```powershell
uv run pytest evals/e2e_quality --e2e-scope=diagnostic -q -s
```

该 selection 同时包含三种不同成本和语义：

- 真实外部 Provider profile：`E16–E21`；
- 真实模型 + frozen provider 的 HTTP conformance：`CTX-001/GOV-001/RUN-001`；
- Investigation 的 12 个 `LT` 用例（`LT01–LT08、LT10–LT13`）已迁移到 `evals/runtime_conformance/investigation_project`，用独立命令执行；`LT09` 已删除。

`diagnostic` 不是一个同质测试层级。

## Archive 当前内容

每次 run 生成：

- `manifest.json`：commit、branch、dirty、Python/platform、MeasurementProfile；
- `*.trace.json`：case trace、test outcome、可选 CaseMeasurement；
- `summary.json`：pytest phase outcome 和 duration；
- `checksums.sha256`：全部 JSON 的完整性封印。

Archive 保存执行证据；Persona、需求/contract 来源、baseline 引用、用户结果和反事实由 catalog 的 typed `UserOutcomeContract` 拥有，release gate 必须同时取得该 contract 与同 revision archive。

## 独立变更准入证据

**`evals/product_baselines/` 不再写 `conv-*-baseline.json` 这类可覆盖文件；每次执行都生成独立且 checksum 封印的 archive。**

目录结构为：

```text
data/e2e_traces/product_baselines/<case-id>/<baseline|target>/<run-id>/
```

每条 trace 的 `product_evidence` 记录 case、role、证据类别、正式入口、交互模式、principal、用户输入 digest、初始事实 digest、配置 cohort 和 grader 版本；manifest 记录 commit、dirty 状态与 dirty digest。测试默认记录 `target`，需要在旧实现保存 baseline 时显式设置对应 role，例如：

```powershell
$env:PERSONAL_AGENT_CONV_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_CONV_001_EVIDENCE_SEED = "same-pair-seed"
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conv_001_working_plan.py
```

target 必须使用相同 seed、用户输入、principal、正式入口、初始事实和 grader，再执行机械配对校验：

```powershell
.\.venv\Scripts\python.exe -m evals.product_baselines.evidence `
  <baseline-run-dir> <target-run-dir>
```

校验会拒绝 checksum 失效、role 错误、输入/身份/入口/交互模式/初始事实/grader 不一致，以及代码与配置身份完全相同的伪配对。旧的固定 `conv-*.json` 只能视为历史调试产物，不能作为 paired baseline/target 或发布证据。

## Release gate

```powershell
uv run python -m evals.e2e_quality.release_gate `
  --trace-root data/e2e_traces
```

gate 当前检查：

1. catalog 计算为 `release_eligible`；
2. archive checksum 有效；
3. manifest commit 等于目标 revision；
4. archive 和目标工作树 clean；
5. test outcome 为 passed 且存在 trace；
6. capability 所需 evidence id 均 trusted。

gate 还会 fail closed 拒绝缺少 `UserOutcomeContract`、错层或使用 test double 的产品声明。重叠关系由 `evidence_audit` 输出；它不会只因共享断言就删除仍有独有不变量的用例。即便 trusted，也只证明该用户结果在固定 profile/revision 成立，不证明架构最初有产品必要性。

## 当前发布状态

实际运行 release gate 后：目标 revision dirty，所有 native/loop capability 均为 `unverified`，原因均包含：

```text
target_revision_dirty
missing_same_revision_passing_trace
```

当前不能引用历史完整矩阵或定向 archive 声称当前 revision release ready。
