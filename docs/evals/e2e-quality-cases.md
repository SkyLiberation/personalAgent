# E2E Quality 用例汇总

> 状态: 已落地现状 · 定位: E2E Live Behavioral Diagnostic · 目标目录: `evals/e2e_quality/` · 运行入口: `uv run pytest evals/e2e_quality -v`

`e2e_quality` 当前是全量 live E2E behavioral diagnostic，覆盖 29 个真实环境 case。它跑真实入口、真实 workflow、真实 Postgres 测试库、真实 Evidence Engine、真实 `DefaultIntentRouter` / `LlmClient`、真实 ToolExecutor / ToolGateway，并使用当前环境中的真实 web / capture / graph / langextract 配置。测试不再裁剪 P0、不再关闭真实配置、不再 mock Graphiti disabled，也不再用 fixture tool 替换真实工具。

这套 suite 的定位不是 deterministic golden gate。真实 LLM、真实 web、真实 graph 和真实外部抓取会漂移，所以当前 baseline 使用“软整体阈值 + 少量 critical case 严格阈值”。Research 聚类、URL canonicalization、controlled failure degrade 这类算法/控制流能力仍应由 fixture / replay gate 承担 baseline=1.0 的稳定回归职责。

如果未配置 `OPENAI_API_KEY` / `OPENAI_BASE_URL` 以及 router 可用配置，测试会 skip，不会用假 LLM 冒充通过。其他真实环境能力缺失或降级不应被绕过；它们应该体现在 scorer 失败、tool trace、research state、verification / grounding 结果或日志诊断中。

## 当前得分

最近一次验证命令：

```powershell
uv run pytest evals\e2e_quality -v
```

可选局部运行：

```powershell
$env:E2E_QUALITY_CASES="E2E-ASK-002,E2E-ART-001"
uv run pytest evals\e2e_quality -v
Remove-Item Env:\E2E_QUALITY_CASES
```

或按分支运行：

```powershell
$env:E2E_QUALITY_BRANCHES="ask,artifact"
uv run pytest evals\e2e_quality -v
Remove-Item Env:\E2E_QUALITY_BRANCHES
```

设置 `E2E_QUALITY_CASES` 或 `E2E_QUALITY_BRANCHES` 时，suite 会记录分数和 baseline diagnostics，但默认不因为 baseline 失败而让 pytest 失败；如需对子集也强制门禁，可设置 `E2E_QUALITY_ENFORCE_BASELINE=true`。

最近一次旧版 18 case 全量真实环境运行已经完成，无 pytest 外层 timeout；`data/e2e_quality_traces/latest.jsonl` 中 `graph_search 执行超时` 诊断计数为 0。本轮新增 workflow case 后，已使用 `E2E_QUALITY_CASES` 对新增子集做局部真实验证，未重跑完整 29 case 全量。当前失败/漂移主要集中在 live web 结果、模型措辞、research case 假设漂移，以及 delete 候选检索受 Graphiti probe timeout 影响，不是 pytest 外层长时间卡死。

| 指标 | 当前得分 | Baseline | 说明 |
| --- | ---: | ---: | --- |
| `overall_score` | 0.8574 | 0.8000 | 最近一次旧版 18 case 全量结果；29 case 全量待下次重跑刷新 |
| `artifact` branch score | 1.0000 | 1.0000 | 2 个 artifact case |
| `ask` branch score | 0.8524 | 0.8000 | 7 个 ask case |
| `research` branch score | 0.8296 | 0.7500 | 9 个 research case |
| case pass rate | 11 / 18 | >= 9 / 18 | 最近一次旧版 18 case 全量结果；新增 workflow 子集已单独验证 |

新增 `workflow` 分支最近一次局部真实验证命令：

```powershell
$env:E2E_QUALITY_BRANCHES="workflow"
uv run pytest evals\e2e_quality -v
Remove-Item Env:\E2E_QUALITY_BRANCHES
```

结果：11 个新增 workflow case 全部执行完成，`workflow=0.9636`，pytest 通过；唯一未满分 case 是 `E2E-WF-DELETE-001`，当前表现为路由正确但候选检索失败/跳过，没有稳定进入 `waiting_confirmation`。

Baseline 定义在 `evals/e2e_quality/baseline.json`：当前是 live diagnostic 阈值，要求 overall / branch 达到软地板，同时 `E2E-ASK-002`、artifact 基础路径、router 边界和 tool budget 等 critical cases 保持满分。

## 运行口径

| 层级 | 当前实现 |
| --- | --- |
| 存储 | 使用真实 Postgres 测试库，并通过 `clean_postgres_business_tables` 隔离数据 |
| 路由 | 使用真实 `DefaultIntentRouter`；router LLM 从环境配置构建，artifact / research 仍保留生产确定性规则 |
| Ask 生成 | 使用真实 `LlmClient.generate_answer`，不覆盖 `service.runtime._llm.generate_answer` |
| Ask 验证 | 走真实 Ask verification / repair telemetry / Evidence Engine claim grounding |
| Artifact 多模态 | 走真实 `analyze_artifact` workflow 与 `inspect_artifact` tool；文本附件解析正文，图片按当前视觉模型能力真实执行或降级 |
| Graph | 使用当前环境中的真实 Graphiti / graph tool 配置；不可用时必须暴露为真实降级原因 |
| Research 外部工具 | 使用当前环境中的真实 `web_search` / `capture_url` / `graph_search` 工具 |
| Research 行为 | 走真实 request understanding、source collection、event extraction、satisfaction、digest compose |
| Workflow 行为 | 覆盖 direct answer、capture text/file、summarize、solidify、review digest、consolidate、gap inspect、workflow inspect、delete HITL diagnostic、复杂 capture+ask |
| LLM 边界 | answer / router / planner / research text generation / langextract 按当前环境真实配置执行 |
| 评分 | `evals/e2e_quality/scorer.py` 计算 case / branch / overall 分数 |

ASK 的 web fallback 语义需要区分两类问题：

- 公共时效事实必须允许联网，例如天气、最新资料、公开 API 文档。
- 私有记忆无证据问题不应自动联网，例如“我的 Phoenix 项目上线窗口是什么？”这类只能由本地记忆回答的问题；证据不足时应保守拒答。

## Trace 口径

全量真实环境运行时，测试会写入 case-scoped trace：

| 文件 | 作用 |
| --- | --- |
| `data/e2e_quality_traces/latest.jsonl` | 最近一次运行的流式 trace；pytest 超时或被中断后优先看这个文件 |
| `data/e2e_quality_traces/<UTC timestamp>.jsonl` | 本次运行的持久 trace 快照 |

每条 case 至少写入：

| 事件 | 含义 |
| --- | --- |
| `case.started` | case 已开始；如果 timeout，最后一条 started 通常就是卡住的 case |
| `case.completed` | case 完成，包含 duration、LLM usage、产物摘要、diagnostic logs |
| `case.failed` | case 抛异常，包含 error、traceback、diagnostic logs |
| `suite.scored` | scorer 汇总分数与 baseline failure |

case trace 会捕获 router / LLM parse / verifier / artifact / web provider / research / tool audit 等诊断日志，并把 LLM 调用次数、LLM latency、token usage 写入 `E2EQualityRun.metadata.trace`。这不是替代 LangSmith，而是保证本地 pytest timeout 后仍能定位到 case 级别。

## 已落地用例

| ID | 入口 | 覆盖分支 | 前置数据 | 评价点 |
| --- | --- | --- | --- | --- |
| E2E-ASK-001 | `execute_entry` | `ask` | 先 `execute_capture` 注入一条“服务降级”笔记 | 命中证据；answer 包含“服务降级 / 核心链路”；verification score 达标；grounding 至少 `weak_evidence` |
| E2E-ASK-002 | `execute_entry` | `ask` 私有无证据 | 不注入业务笔记；问题为“我的 Phoenix 项目上线窗口是什么？” | 返回保守回答；matches/citations/evidence 为空；不触发 web fallback；不消耗 LLM 生成 |
| E2E-ASK-003 | `execute_entry` | `ask` 多笔记证据 | 注入 pytest / unittest / nose2 三条笔记 | 保留多个 matches/citations/evidence；answer 覆盖三类测试框架；grounding supported |
| E2E-ASK-005 | `execute_entry` | compound capture + ask | 单次输入同时“记一下蓝绿发布...”并提问 | workflow 保持 capture -> ask 依赖顺序；ask 使用本轮刚写入笔记回答 |
| E2E-ASK-006 | `execute_entry` | `ask` source filter | 上传/写入带 `deploy.md` 来源的部署内容及干扰来源 | 检索受 source filter 约束；answer 引用 deploy.md，不混入 `example.com` |
| E2E-ASK-SEM-002 | `execute_entry` | `ask` 冲突证据 | 注入 Feature X 默认开启 / 默认关闭两条冲突笔记 | answer 必须显式表达冲突和不确定性，不能武断选择某一边 |
| E2E-ASK-WEB-002 | `execute_entry` | `ask` web fallback | 本地无 Kappa API 笔记；使用真实 web_search 工具链 | 仍停留 ask 分支；触发有界 web fallback；citation/evidence 来自工具结果；不升级为 research_once |
| E2E-ART-001 | `execute_entry` | `analyze_artifact` 文本附件 | 上传 `release-notes.txt` | workflow 跑过 `artifact-inspect -> artifact-compose`；answer 基于附件文本回答蓝绿发布第一步；不声称保存 |
| E2E-ART-002 | `execute_entry` | `analyze_artifact` 图片附件 | 上传真实 1x1 PNG 文件 `chart.png` | workflow 跑过 `artifact-inspect -> artifact-compose`；不能识别图片时保守说明能力边界；不幻觉蓝绿发布内容、不声称保存 |
| E2E-WF-DIRECT-001 | `execute_entry` | `direct_answer` | 无前置数据；输入简短问候 | 路由到 `direct_answer`；workflow 跑过 `direct-compose`；简短直接回应 |
| E2E-WF-CAPTURE-001 | `execute_entry` | `capture_text` | 输入“记一下：Atlas 项目的值班窗口...” | 路由到 `capture_text`；workflow 跑过 `cap-structure`；写入至少 1 条笔记 |
| E2E-WF-CAPTURE-FILE-001 | `execute_entry` | `capture_file` | 上传 `gamma-runbook.txt` 并要求保存到知识库 | 路由到 `capture_file`；workflow 跑过 `cap-file-inspect -> cap-file-store`；附件内容入库 |
| E2E-WF-SUM-001 | `execute_entry` | `summarize_thread` | 注入 thread loader 返回 Orion 缓存讨论 | 路由到 `summarize_thread`；workflow 跑过 `sum-compose`；总结包含 Orion / 缓存主题 |
| E2E-WF-SOLIDIFY-001 | `execute_entry` | `solidify_conversation` | 同一 session 先写入 DNS 结论，再要求固化 | 路由到 `solidify_conversation`；workflow 跑过 `sol-1 -> sol-2`；产生 DNS 知识笔记 |
| E2E-WF-REVIEW-001 | `execute_entry` | `review_digest` | 写入一条复习笔记并添加 due review card | 路由到 `review_digest`；workflow 跑过 `digest-generate -> digest-compose`；输出知识简报/复习内容 |
| E2E-WF-CONSOLIDATE-001 | `execute_entry` | `consolidate_knowledge` | 写入两条 Redis 相关笔记 | 路由到 `consolidate_knowledge`；workflow 跑过 `consolidate-run -> consolidate-compose`；整理后笔记数增加 |
| E2E-WF-GAP-001 | `execute_entry` | `inspect_knowledge_gaps` | 写入冲突/孤立知识片段 | 路由到 `inspect_knowledge_gaps`；workflow 跑过 `gap-inspect -> gap-compose`；输出缺口/冲突/薄弱连接分析 |
| E2E-WF-INSPECT-001 | `execute_entry` | `inspect_workflow` | 先执行一次 direct run，再询问该 run_id 步骤情况 | 路由到 `inspect_workflow`；workflow 跑过 `workflow-inspect-decide -> workflow-inspect-compose`；返回 run/步骤诊断 |
| E2E-WF-DELETE-001 | `execute_entry` | `delete_knowledge` | 写入 Delta 临时笔记后请求删除 | 路由到 `delete_knowledge`；workflow 投影 `del-1 -> del-2 -> del-3`；当前作为 HITL / 候选检索 diagnostic |
| E2E-WF-COMPLEX-001 | `execute_entry` | complex capture + ask | 单次输入“先记 Gamma 发布窗口，再直接回答，不要调研” | 前置复合规则拆成 `capture_text -> ask`；ask 使用同轮写入笔记回答；不升级为 `research_once` |
| E2E-RES-001 | `run_research_once` | `research_once` 主路径 | 使用真实 research 工具链调研 Agent Runtime SDK 最近发布 | research 完成；source/event/digest 达标；digest 包含 Agent Runtime SDK 关键事实；satisfaction 停止 |
| E2E-RES-002 | `execute_entry` | ask/research 路由边界 | 同一 user 先问“什么是 Agent Runtime SDK？”，再要求“调研最近重要发布” | 第一问不污染第二问；第二问必须路由到 `research_once` |
| E2E-RES-004 | `run_research_once` | verification query | 使用真实 research 工具链 | 单源证据不足时应追加官方确认查询；`web_search_queries` 可从 `ResearchState.query_history` 评分 |
| E2E-RES-GAP-001 | `run_research_once` | evidence gap | 临时降低 verification budget | 当无法补齐验证来源时记录 `single_source` / `missing_primary_source` gap |
| E2E-RES-005 | `run_research_once` | URL canonicalization | 使用真实 research 工具链 | source collection 应规范化重复 URL variant，避免 canonical URL 重复 |
| E2E-RES-CLUSTER-001 | `run_research_once` | same-event clustering | 使用真实 research 工具链 | 多个不同标题但同一事件的来源应聚为一个 event |
| E2E-RES-CLUSTER-002 | `run_research_once` | distinct-event clustering | 使用真实 research 工具链 | 相似主题但不同事件应保持分离，至少形成两个 events |
| E2E-RES-008 | `run_research_once` | tool budget | 临时降低 research tool budget | tool budget exhaustion 必须可观测并成为终止原因 |
| E2E-RES-FAIL-002 | `run_research_once` | tool failure degrade | 使用真实 research 工具链 | tool failure 必须来自真实工具执行并被 trace；不能人工注入 fixture failure |

## 当前 Gap

最新全量运行仍未达到 baseline=1.0，主要 gap 如下：

| ID | 当前表现 | 归因 |
| --- | --- | --- |
| E2E-ASK-001 | verification score 偶发低于 0.35，grounding 为 `insufficient` | 生成答案扩写超出单条“服务降级”证据，verifier 判定部分 unsupported |
| E2E-ASK-005 | answer 使用“50%流量”等价表达，但未命中“一半流量”字面锚点 | scorer required term 过窄，需改为语义锚点或补充等价词 |
| E2E-ASK-006 | 真实 router/planner 偶发把 source-filter ask 误投为 artifact inspect，缺少 artifact path 导致步骤失败 | live model planning 漂移；适合作为 diagnostic 观察，不适合作为非 fixture 的 1.0 hard gate |
| E2E-ASK-WEB-002 | 已触发 web fallback 且有 citations/evidence，但回答用“速率限制”而非 `rate limit` | scorer 中英字面锚点过窄；真实 web 结果未稳定命中 Kappa API |
| E2E-RES-001 | live web 结果漂移到 AWS / Strands 等相邻主题，event status 多为 `uncertain` | 真实搜索结果不可控，topic “Agent Runtime SDK” 本身歧义较强 |
| E2E-RES-004 | 只记录 1 次 web query，未出现 `official announcement` 查询 | verification query 触发条件或 query planner 输出不稳定 |
| E2E-RES-CLUSTER-001 | 事件数大于 1，未压到 `max_events=1` | live 结果混入多个真实事件；same-event case 假设与真实搜索不匹配 |
| E2E-RES-FAIL-002 | 未出现 failed `capture_url` trace | 真实 provider 当前没有稳定失败，不能靠 live 网络保证 failure degrade 分支 |
| E2E-WF-REVIEW-001 / E2E-WF-GAP-001 | 首次新增子集运行中，router LLM 曾返回“clarify 但包含 goals”的非法结构，fallback 降级为 ask | 已补确定性 fallback：明确“知识简报 / 知识缺口 / workflow / worker / maintain / research manage / solidify / summary / consolidate”等能力短语在 LLM parse failure 时不再落入 ask；复测通过 |
| E2E-WF-COMPLEX-001 | 首次运行将“先记一下...然后直接回答...不要发起调研”误路由为 `research_once` | 已补前置复合规则，`记一下/记住 + 然后直接回答/再直接回答/并直接回答` 优先拆成 `capture_text -> ask`，先于 research 规则和 LLM；复测通过 |
| E2E-WF-DELETE-001 | 已路由到 `delete_knowledge`，但候选检索受 `Graphiti user data probe failed ... TimeoutError` 影响，当前 run 完成为失败/跳过摘要而非稳定 `waiting_confirmation` | 作为 live diagnostic 保留；后续应让 delete 候选检索在图谱 probe timeout 时稳定回退本地候选，或将 HITL 等待确认覆盖迁移到 fixture/replay gate |

已修复的 timeout 根因：Research 个性化排序不再对每个 event 无条件调用 `graph_search` / `enterprise_knowledge_search`；`graph_search` 对空用户图谱做 cheap probe 后跳过慢查询；个性化 enrichment 不计入主 research tool budget。后续若继续要求 baseline=1.0，research/web 类 case 应改为确定性 provider replay 或受控 fixture，否则 live web 漂移会持续造成非产品回归型失败。

## 评分方式

每个 case 运行真实路径后投影为 `E2EQualityRun`，由 scorer 评价：

| 类别 | 当前评价字段 |
| --- | --- |
| 路由与 workflow | `route_intents`、`workflow_id`、`workflow_steps` |
| Run 状态 | `run_status` 支持允许集合，例如 delete HITL 可期望 `waiting_confirmation` |
| Ask 产物 | `matches_count`、`citations_count`、`evidence_count`、`llm_call_count` |
| Ask 行为质量 | `answer` required/forbidden terms、`verification_score`、`grounding_status`、`claim_statuses`、`web_tried` |
| Artifact 行为质量 | `workflow_id`、`workflow_steps`、`answer` required/forbidden terms |
| Research 产物 | `research_status`、`source_count`、`event_count`、`digest_item_count`、`digest_text` |
| Research 行为质量 | `satisfaction_should_continue`、`satisfaction_coverage_score`、`satisfaction_confidence_score`、`satisfaction_marginal_gain` |
| 证据与可追溯性 | `event_statuses`、`confidence_labels`、`web_search_queries`、`canonical_urls` |
| 可靠性 | `stop_reason`、`tool_call_trace_count`、`failed_tool_call_count`、`tool_error_kinds`、`stage_timing_count` |

每个评价字段会被转成一个 `MetricScore`，当前 gate 使用 0/1 结果：

| 评分函数 | 通过条件 |
| --- | --- |
| `_exact` | 实际值等于期望值 |
| `_one_of` | 实际值在允许集合内 |
| `_intersects` | 实际集合与期望集合有交集 |
| `_min` / `_min_float` | 实际数量或分数大于等于最小值 |
| `_max` / `_max_float` | 实际数量或分数小于等于最大值 |
| `_range` | 实际数量落在 min/max 范围内 |
| `_contains` | answer / digest 包含必需语义锚点 |
| `_contains_any` | answer / digest / web query 命中一组等价锚点中的任意一个，例如 `一半流量 / 50%流量` |
| `_not_contains` | answer / digest 不包含禁用语义锚点 |
| `canonical_url_uniqueness` | `canonical_urls` 没有重复值 |

score 聚合方式：

| 分数 | 计算方式 |
| --- | --- |
| case score | 单条 case 下所有 `MetricScore.score` 的平均值 |
| branch score | 同一 branch 下所有 case score 的平均值 |
| overall score | 全部 case score 的平均值 |
| case pass rate | 达到 `min_case_score` 的 case 数 / 全部 case 数 |

pytest 中只保留最终 gate：

```python
failures = report.check_thresholds(baseline)
assert not failures
```

这个断言表示“评分报告是否通过 baseline”，不是对业务字段做单元测试式断言。

当前 baseline 支持：

| 字段 | 含义 |
| --- | --- |
| `min_overall` | live suite overall 软地板 |
| `min_case_score` | 非 critical 单 case 硬地板；live diagnostic 当前设为 0，避免真实 web / LLM 漂移把整套诊断误杀 |
| `min_branch_scores` | ask / artifact / research 分支软地板 |
| `critical_cases` + `critical_case_min_score` | 少数基础能力 case 必须严格达标 |
| `case_pass_score` + `min_case_pass_rate` | 至少一定比例 case 达到指定分数，保留趋势观察能力 |

新增 `workflow` 分支当前不设置 branch floor，也不加入 `critical_cases`；它用于扩大 live 行为诊断面。若后续某条 workflow case 经过多轮验证稳定，可再提升为 critical 或迁移到 fixture/replay gate 做 deterministic baseline。
