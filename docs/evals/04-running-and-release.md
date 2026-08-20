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

### CONV-002 Provider 公平 cohort

比较不同 structured Provider/model 时，必须保持应用 transport 为 `json_object`，并让评测在配置不符时直接失败。下面的命令只替换 Provider、base URL 和 model；API key 由当前 shell 的密钥注入，不写入命令或 archive：

```powershell
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_CONV_002_EXPECTED_TRANSPORT = "json_object"
$env:STRUCTURED_API_KEY = $env:MIMO_API_KEY
$env:STRUCTURED_BASE_URL = "https://api.xiaomimimo.com/v1"
$env:STRUCTURED_MODEL = "mimo-v2.5"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "tavily"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.tavily.com"

1..3 | ForEach-Object {
  $env:PERSONAL_AGENT_CONV_002_SAMPLE_ID = "mimo-json-object-$($_)"
  uv run pytest -q -s `
    evals/product_baselines/test_conv_002_agent_initiated_working_plan.py
}
```

`config_cohort` 会记录 model、structured provider host、output transport、extra body、预算、交互策略和 Web Search Provider；API key 不进入 digest。不同 transport（例如 `json_schema`）或不同 provider endpoint 的 archive 不得合并到这个 cohort。

### PLAN-STAB-001 重复稳定性 baseline

该用例固定来源比较、产品变更和事故分析三类自然请求，每类独立执行五次。它使用正式 Conversation HTTP、真实模型、
Postgres、Tavily、服务重启和 checksum 归档；一次完整执行包含 15 个真实外部样本，成本较高，不属于普通回归套件：

```powershell
$env:PERSONAL_AGENT_PLAN_STAB_001_EVIDENCE_ROLE = "baseline"
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_PLAN_STAB_EXPECTED_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "tavily"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.tavily.com"

uv run pytest -q -s `
  evals/product_baselines/test_plan_stab_001_working_plan_stability.py
```

2026-08-20 的 `deepseek-v4-flash + json_object` 有效样本组为 `14/15 delivered` 和一次官方证据不足，没有 Plan 语义
失败。该组包含 105 次模型调用、75 个模型轮次、39 次工具调用和 999,389 个令牌，模型调用延迟 P95 为 99.95 秒。
预声明生产变更门槛是至少 `3/15` 次 Plan 语义失败且覆盖至少两类场景；本轮未达到，不能继续追加样本直到碰到阈值。
只有新的用户契约、独立线上问题或模型、服务提供方及交互契约变化时才能预声明新组，并归入新的对照身份。

### PLAN-REAL-001 真实恢复实验

该用例从正式 Conversation HTTP 取得官方资料，重启 Web 进程后以同一 conversation 增加展示要求，并检查旧 Plan、
官方来源、未完成义务、恢复阶段重复 Web Search 和最终用户结果。完整 cohort 为三类请求各五次：

```powershell
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_PLAN_REAL_EXPECTED_TRANSPORT = "json_object"
$env:STRUCTURED_API_KEY = $env:MIMO_API_KEY
$env:STRUCTURED_BASE_URL = "https://api.xiaomimimo.com/v1"
$env:STRUCTURED_MODEL = "mimo-v2.5"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "tavily"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.tavily.com"

uv run pytest -q -s `
  evals/product_baselines/test_plan_real_001_real_provider_recovery.py
```

有效 v2 target-minus-mechanism archive 位于 `plan-real-001/baseline/*-36028-*`，结果为 `9/15 delivered`、
`3/15 semantic_recovery_failure`、`3/15 insufficient_official_evidence`；draft-step 绑定 target 位于
`plan-real-001/target/*-33492-*`，结果退化为 `6/15 delivered`、`5/15 semantic_recovery_failure`、
`2/15 insufficient_official_evidence`、`2/15 provider_failure`。两组恢复 Web Search 都为零。target 未通过预声明
`>=14/15 delivered`，候选已撤回；该命令现在只用于新 comparison identity 的复核，不得把已否决机制重新解释为优化。

### PLAN-REPLAN-001 义务修订 baseline

有效 v3 使用默认审阅模式，首轮必须真实取得官方资料并返回仍有 pending step 的 Plan；Web 重启后用户以自然业务语言
否定候选、撤回并新增结果或收紧验收，最终答案必须修订同一 Plan、完成新义务且不保留撤回结果：

```powershell
$env:PERSONAL_AGENT_PLAN_REPLAN_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_REPLAN_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_replan_001_obligation_revision.py
```

2026-08-20 的有效样本组为 `10/15 delivered`、`4/15 stale_obligation_failure` 和
`1/15 semantic_pending_plan_missing`。四次可归因计划修订失败全部出现在撤回并新增结果场景；另一次失败伴随大型结果重读
与预算耗尽，归入结果物化和预算责任主体。可归因失败未覆盖第二类场景，故未达到 A1，不执行生产消融。该组包含 124 次
模型调用、95 个模型轮次、75 次工具调用和 1,205,254 个令牌，模型调用延迟 P95 为 100.29 秒。执行期间代码身份变化的
归档，以及历史零工具首轮和 `auto` 模式归档，只用于评测脚手架诊断，不能与有效样本合并。

### PLAN-COMP-001 完成真实性 baseline

该用例固定 Structured Outputs 事实正确性、MCP Tool result 的 exactly-once/完整交付、durable execution 的业务通知
零重复三个边界，每类五次。grader 直接检查最终回答是否给出用户要求的章节、官方 URL、否定性边界和无保留强结论：

```powershell
$env:PERSONAL_AGENT_PLAN_COMP_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PLAN_COMP_EXPECTED_TRANSPORT = "json_object"
uv run pytest -q -s `
  evals/product_baselines/test_plan_comp_001_completion_truthfulness.py
```

2026-08-20 的有效样本组为 `14/15 honest_boundary` 和 `1/15 erroneous_success`。唯一错误成功出现在 Structured
Outputs 事实正确性场景，其余两类均为 `5/5 honest_boundary`，未达到跨两类 A1 门槛。该组包含 62 次模型调用、47 个
模型轮次、35 次工具调用和 515,546 个令牌，模型调用延迟 P95 为 44.75 秒。执行期间代码身份变化的归档与历史错误 grader
归档只作为诊断，不能参与门禁或结果合并。

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
