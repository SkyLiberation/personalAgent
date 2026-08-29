# 运行、归档与发布

**当前 E2E 数量以测试收集与 `evidence_catalog.py` 为准；已撤回的 Investigation Project 及其 scripted conformance 不再属于当前执行矩阵。**

## 收集当前矩阵

```powershell
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=release
uv run pytest evals/e2e_quality --collect-only -q --e2e-scope=diagnostic
```

当前实际结果：

```text
release selection: 9
diagnostic selection: 19
retired Investigation conformance: 0
catalog total: 28
```

## 执行机器 release selection

日常修改先用影响路由决定最小 live selection：

```powershell
uv run python scripts/e2e_impact.py
```

当变更必须覆盖完整矩阵时，路由同时输出两个用途不同的命令：

- `iteration command` 带 `-x`，仍在 collection 阶段检查完整 release catalog，但首个失败后停止；当本地存在 checksum 有效且包含全部 release case 的历史 archive 时，命令按最近一次实测 duration 从短到长列出全部 node，并打印排序证据坐标；没有完整历史时回退到目录收集顺序。排序只改变迭代反馈时间，不改变 case、预算或断言，也不能作为发布证据；
- `release evidence command` 不带 `-x`，执行并记录全部 case outcome，保持下面的完整发布证据契约。

`--quiet` 为已有调用方保持原行为：完整矩阵路由只输出不带 `-x` 的 release evidence command。

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

- 真实外部 Provider profile：`E16/E18/E19/E21`；
- 真实模型 + frozen provider 的 HTTP conformance：`CTX-001/GOV-001/RUN-001`；
- 已撤回机制的 `LT` scripted Investigation 用例已删除；需要解释旧结论时只读取 checksum 有效的历史归档，不把它们作为当前测试矩阵。

`diagnostic` 不是一个同质测试层级。

## 执行横切验证套件

横切套件不创建第二套 E2E。`validation_catalog.py` 只引用 canonical catalog 中的既有节点，并为 Tool Calling、MCP dispatch、A2A Artifact 返回或窄范围研究路由预先声明关键检查点。同一节点可以进入多个套件；原始 pytest 结果、Product E2E 结果和发布门禁判断保持不变。

先列出套件节点并完成 collect-only、impact routing 与成本估算：

```powershell
$nodes = uv run python -m evals.e2e_quality.cross_cutting_validation `
  --suite tool_calling_protocol --list-nodeids
uv run pytest $nodes --collect-only -q
```

需要新 live 证据时，把节点放在同一次 pytest run 中，不使用 `-x`，让整例失败仍能封存供关键检查点读取的 Trace。运行前仍须遵守单样本 `60s`、cohort `10min/200,000 tokens` 和数学早停门禁：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E = "true"
$env:PERSONAL_AGENT_E2E_TRACE_DIR = "data/e2e_traces/tool-calling-validation"
uv run pytest $nodes -q -s
```

pytest 可以因用户结果失败返回非零；随后对控制台打印的单一密封 run 目录生成横切报告：

```powershell
uv run python -m evals.e2e_quality.cross_cutting_validation `
  --suite tool_calling_protocol `
  --archive <sealed-run-dir>
```

报告中的 `pytest_outcome` 是整例事实，`capability_passed` 只表示该套件预先声明的关键 Runtime Mechanism 检查点。比如真实 MCP 返回 `401` 时，动作解码与 MCP dispatch 可以通过，而 Provider availability 和用户结果仍失败。缺失节点、重复节点、checksum 失效或 repository/evaluation identity 不一致都会使报告失败；禁止从不同 revision 或 cohort 挑选局部成功样本拼成套件通过。

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

### 逐样本晋级门槛与早停

高成本、重复采样的独立 target 可以使用 typed promotion spec。门禁在每个 `ProductEvidenceRecorder` archive 封存后计算；只在门槛已经数学上不可达到时提前拒绝，绝不因 partial target 暂时良好而提前通过。示例：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_interaction_intent_delegation_boundary_001.py `
  --product-promotion-spec `
  evals/promotion_specs/interaction_intent_target_001.json `
  --product-promotion-output `
  data/e2e_traces/promotion_gates/interaction-intent-target
```

spec 固定 `case_id`、target role、stage、`expected_samples` 和 typed constraints。当前约束支持 boolean minimum/maximum count、numeric maximum sum、nearest-rank percentile 上限和 conditional rate 下限；`result_report_missing` 与 `test_failed` 是 recorder/pytest 产生的 boolean 执行事实。runner 还会机械拒绝：

- source archive checksum 无效；
- case/role、正式入口、交互模式、代码/config、grader 或 evidence class 不同；
- 同一 archive 被重复消费（相同自然输入的独立重复运行仍合法）；
- 指标缺失、类型错误或 conditional numerator 不蕴含 denominator；
- 测试全部结束但仍未收齐预声明样本。

该命令必须只选择一个专用 cohort，不与 `--maxfail` 组合。pytest 自身测试失败、internal error 和 usage error 不会被 promotion pass 覆盖。输出 archive 的 evidence class 是 `evaluation_promotion_decision_not_product_e2e`；它能证明 cohort 晋级决策，不能替代 baseline、单变量消融、完整真实 target 或 release gate。

历史 archive 可只读回放，不重新调用 Provider：

```powershell
.\.venv\Scripts\python.exe -m evals.e2e_quality.promotion_gate `
  evals/promotion_specs/interaction_intent_target_001.json `
  <target-archive-root> `
  --output-root data/e2e_traces/promotion_gates/replay
```

默认一次性 `capture` 仍适用于没有 pre-capture 失败 baseline 的用例。已证明昂贵调用可能在结果报告形成前失败时，必须在调用前 enrollment，再在完整 grader report 形成后提交结果：

```python
product_evidence_recorder.enroll(nodeid=nodeid, identity=identity)
result = invoke_formal_entrypoint()
product_evidence_recorder.capture_report(build_grader_report(result))
```

enrollment 只冻结可在执行前知道的 case、role、正式入口、身份、输入、初始事实、config cohort 和 grader version，不得预填用户结果。call phase 异常会封存 `enrolled_without_result_report`；如果测试返回成功但没有 `capture_report`，pytest 会被强制置为 failed。fixture/setup 在 test body 前失败时仍没有合法场景 identity，不进入 cohort，禁止从 nodeid 或 stdout 补造。

当前已迁移的 Agent 委托 cohort 使用：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_agent_perf_delegate_001.py `
  --product-promotion-spec `
  evals/promotion_specs/agent_delegate_target_001.json `
  --product-promotion-output `
  data/e2e_traces/promotion_gates/agent-delegate-target
```

该 spec 对 `result_report_missing` 和 `test_failed` 都要求零容忍，因此任一正式样本在调用阶段失败即可停止余下 cohort。它不改变产品 target 门槛，也不把执行失败解释成用户结果失败类型。

同一逐样本门禁也接受 `role=baseline`、`stage=failure_baseline`，用于昂贵 A0/baseline 在预声明结论已不可逆时停止后续样本。baseline 仍必须收齐其 spec 要求的样本才能判定 `passed`；门禁不会把提前观察到若干失败自动升级成完整 cohort，也不允许 baseline 与 target 混合。

受控本地 MCP 文件边界 baseline 的可执行入口为：

```powershell
$env:PERSONAL_AGENT_LOCAL_MCP_FILESYSTEM_SANDBOX_001_EVIDENCE_ROLE = "baseline"
.\.venv\Scripts\python.exe -m pytest -q `
  evals/product_baselines/test_local_mcp_filesystem_sandbox_001.py `
  --product-promotion-spec `
  evals/promotion_specs/local_mcp_filesystem_sandbox_baseline_001.json
```

该用例只创建 pytest 临时根中的随机 `ALLOWED`/`PRIVATE-CANARY`，不枚举或读取真实用户文件。2026-08-28 的正式 cohort 在第 `9/20` 项已无法达到预声明 `18/20` 最终答案泄露门槛，同时超过 `200,000` token 总预算；门禁拒绝并停止余下 11 项。`9/9` 模型可见越界读取只作为 Runtime 风险证据，不能替代产品失败 baseline 或触发沙箱实现。

长短 Conversation 历史配对 baseline 使用短控制优先、四类旅程交错的 40-item 顺序：

```powershell
$env:PERSONAL_AGENT_CONVERSATION_CONTEXT_PRESSURE_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_CONTEXT_PRESSURE_SEED = "<本次冻结 seed>"
.\.venv\Scripts\python.exe -m pytest -q `
  evals/product_baselines/test_conversation_context_pressure_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_context_pressure_baseline_001.json `
  --product-promotion-output data/e2e_traces/pg
```

短控制最多允许一个失败；只有至少 `19/20` 短控制交付后才有资格执行 24 回合、48 条消息的长路径。2026-08-28 的交错正式运行在第 `7/40` 项出现第二个短控制失败，停止余下 33 项，未把短路径错误归因给 Context 增长。长输出根曾使 Windows 原子临时文件越过路径上限；`TraceArchive` 现使用同目录短临时 basename 后再原子替换，最终文件名、checksum 和 archive 契约不变。同一批密封证据已在原长输出根成功重放并写出完整门禁 archive。

普通 Conversation 研究 cohort 也使用逐样本归档。`19/20 delivered` 已不可达到时，门禁停止余下昂贵请求；单条通过不能提前晋级：

当前生产路径与 corrected-grader v3 的 baseline 入口为：

```powershell
$env:PERSONAL_AGENT_CONVERSATION_RESEARCH_DELIVERY_001_EVIDENCE_ROLE = "baseline"
$env:PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR = `
  "data/e2e_traces/product_baselines/conversation-research-v3-current"
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conversation_research_delivery_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_research_baseline_003.json `
  --product-promotion-output `
  data/e2e_traces/promotion_gates/conversation-research-baseline-v3
```

v3 把每个必需复合概念定义为预声明原子词集合，并要求原子词出现在同一句或同一标题；跨句散落的原子词负控制必须失败。旧 v2 archive 保持原 grader 结果，不能用 v3 离线重放事后晋级。2026-08-28 的新 baseline 在 `0/2 delivered` 后拒绝并停止 18 项，说明修正 grader 后当前生产失败仍成立。

只有获得已准入的生产候选后，才运行 target spec：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_conversation_research_delivery_001.py `
  --product-promotion-spec `
  evals/promotion_specs/conversation_research_target_002.json `
  --product-promotion-output `
  data/e2e_traces/promotion_gates/conversation-research-target-002
```

当前 per-sample 入口收集 20 个 pytest item，每项只执行一次正式 HTTP 请求并形成一份 checksum archive。历史 v1 聚合 archive 保持只读，不能与新 cohort 合并。

后台持续能力边界已采用同样的逐样本结构，当前可执行入口只保留参数化 v2：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -s `
  evals/product_baselines/test_background_continuation_limitation_001.py `
  --product-promotion-spec `
  evals/promotion_specs/background_continuation_target_002.json `
  --product-promotion-output `
  data/e2e_traces/promotion_gates/background-continuation-target-002
```

该命令收集 20 个 pytest item，而不是在一个 item 内循环 20 次。每项只执行一个正式 HTTP 请求并生成一个 archive，因此零容忍失败可以在样本边界立即停止。历史 `grader-v1` 聚合 archive 只服务已经关闭的 ADR 0015 证据；不能与 `v2-per-sample` 合并计算稳定性或晋级结果。

### CONV-002 Provider 公平 cohort

复现历史 `CONV-002` 公平同配置样本组时，必须保持该组的应用 transport 为 `json_object`，并让评测在配置不符时直接失败。下面的命令只替换 Provider、base URL 和 model；API key 由当前 shell 的密钥注入，不写入命令或 archive。新的服务提供方评测应使用其已准入的能力配置档案，不能把本节的历史 transport 当作全局规则：

```powershell
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_CONV_002_EXPECTED_TRANSPORT = "json_object"
$env:STRUCTURED_API_KEY = $env:MIMO_API_KEY
$env:STRUCTURED_BASE_URL = "https://api.xiaomimimo.com/v1"
$env:STRUCTURED_MODEL = "mimo-v2.5"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

1..3 | ForEach-Object {
  $env:PERSONAL_AGENT_CONV_002_SAMPLE_ID = "mimo-json-object-$($_)"
  uv run pytest -q -s `
    evals/product_baselines/test_conv_002_agent_initiated_working_plan.py
}
```

`config_cohort` 会记录 model、structured provider host、output transport、extra body、预算、交互策略和 Web Search Provider；API key 不进入 digest。不同 transport（例如 `json_schema`）或不同 provider endpoint 的 archive 不得合并到这个 cohort。

### PLAN-STAB-001 重复稳定性 baseline

该用例固定来源比较、产品变更和事故分析三类自然请求，每类独立执行五次。它使用正式 Conversation HTTP、真实模型、
Postgres、AnySearch、服务重启和 checksum 归档；一次完整执行包含 15 个真实外部样本，成本较高，不属于普通回归套件：

```powershell
$env:PERSONAL_AGENT_PLAN_STAB_001_EVIDENCE_ROLE = "baseline"
$env:STRUCTURED_OUTPUT_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_PLAN_STAB_EXPECTED_TRANSPORT = "json_object"
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

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
$env:PERSONAL_AGENT_WEB_SEARCH_PROVIDER = "anysearch"
$env:PERSONAL_AGENT_WEB_SEARCH_BASE_URL = "https://api.anysearch.com"

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
