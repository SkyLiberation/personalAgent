# Durable Investigation Project 当前实现

## 1. 结论与证据边界

Investigation Project 已成为独立的 durable 产品入口，而不是 Conversation 的隐藏模式。
正式 API 可以异步创建、只读查询、steering、审批、暂停、恢复和取消；worker 从 PostgreSQL
journal 重建 Project，并按 accepted Plan 计算 ready set、dispatch、join、coverage 与
Completion。

当前 LT01–LT08、LT10–LT13 使用生产 Domain、Application、PostgreSQL store、worker queue 和 Artifact owner，
但 semantic model 与外部 Provider 是 scripted/frozen Port。B03 已补正式 HTTP/worker、真实模型
和 Web Search baseline，并证明 verification repair 的生产死锁；相关 runtime 缺口已修复。
Firecrawl Web Search Adapter 已删除，生产搜索迁移为 SerpAPI；URL 正文读取仍显式绑定
builtin，不存在运行时 Provider fallback。IP01 已从正式 HTTP/worker 入口经过真实模型、
SerpAPI、URL reader、Verifier、Synthesis 和 Completion Gate 交付最终报告：archive
`20260729T101501.732689Z-53628-6c5f02f2`，`1 passed in 86.42s`，3/3 outcome satisfied，
5 条 admitted evidence，`environment_failed=false`。这证明 IP01 repair 缺口已闭合，但不替代
尚未执行的完整 live GitHub/Notion/Web/A2A 发布矩阵和重复运行方差。

## 2. Canonical owners

| 事实 | 唯一 owner/写入口 |
| --- | --- |
| Project definition、Plan、SubGoal、waiting、budget、verification、completion | `InvestigationProject` aggregate + `InvestigationProjectService` |
| Project persistence | `PostgresInvestigationProjectStore` definition + append-only events |
| child Agent definition、submission binding、projection | `AgentGateway` + `PostgresAgentRunStore` |
| Artifact 正文与私有路径 | `ArtifactService` |
| Tool 执行事实、policy、idempotency、audit | `ToolGateway` |
| Web Search Provider 与凭据 | `Settings.web_search` + `PERSONAL_AGENT_WEB_SEARCH_*`；生产绑定 SerpAPI |
| URL 正文 Provider 绑定 | `Settings.url_capture_provider` + Composition Root；单值绑定，无 runtime fallback |
| repair-to-frozen-gap lineage | accepted `SubGoalDefinitionVersion.repairs_frozen_subgoals`；仅随 Plan 接受写入 |
| Execution Proposal 拒绝事实 | Project journal `ExecutionProposalRejectedData`；仅由 `InvestigationProjectService` append |
| queue lease/retry/dead letter | `PostgresWorkerQueueStore` |
| 开放语义 Proposal/Assessment | Project structured-model Ports |

Project 只保存 Artifact `ResourceRef`；AgentRun 不保存 Provider 正文；Gateway context 只接收
canonical `ExecutionScope`。API key 配置映射到 typed `AuthenticatedPrincipal`，不再使用
`key:user` 字符串映射。

## 3. 生产主链

```text
POST /api/investigation-projects
  -> persist immutable definition
  -> enqueue investigation worker task
  -> 202 + project_id

worker lease
  -> rehydrate Project journal
  -> Planner Proposal -> Plan Admission -> accepted Plan
  -> deterministic ready set
  -> Execution Proposal -> capability/policy admission
  -> ToolGateway | durable AgentGateway | synthesis
  -> Evidence Admission -> semantic Verifier
  -> committed SubGoal Outcome
  -> deterministic Completion Gate
  -> generated final ArtifactRef + CompletionReport
```

GET 只读取 projection，不驱动 worker，不调用模型，也不推进状态。worker 启动到
`investigation` queue 时扫描 recoverable Project 并用稳定 idempotency key 重新入队，覆盖
create 已提交但 enqueue 前崩溃的窗口。

## 4. Durable Agent 与 Artifact

Agent submission 顺序是：

1. 以 stable submission key 和 immutable definition digest 写 reservation；
2. 调用 registered Provider Adapter；
3. 将 provider task id 与同一 run commit；
4. 重启后若 reservation 已存在但 binding 缺失，只允许 `lookup_submission(key)`；
5. Provider 不支持 lookup 或查不到时返回 `AgentSubmissionOutcomeUnknown`，禁止盲目重提。

Grant 的 AuthorizationDigest、ExecutionCommandDigest 和 submission key 写入 canonical child
definition。Provider Artifact 先通过 `ArtifactService.write_generated` 落入 owner scope，
AgentRun 只保存 `ResourceRef`。Conversation 或 Project 读取正文时必须再次通过 principal 和
resource owner 校验。

## 5. Project state and control

Project 状态为 `planning -> active -> paused/cancelling/completing -> terminal`。steering 只修订
未冻结 SubGoal；accepted/running/completed work 不被 revision 覆盖。审批绑定
AuthorizationDigest；取消会调用已关联 child run，并将终态后返回的 Artifact quarantine，
不会重新打开 Project。

暂停原因是 Project journal 的 canonical fact。`resume` 只解除 `user_paused`；预算、能力、
审批或修复条件造成的系统暂停必须由对应 typed condition 解除。恢复扫描不会重新入队任何
paused Project。

Verifier 判定已执行 SubGoal 不满足时，原 Proposal、ExecutionRef 和 Evidence 保持冻结；Plan
revision 必须新增独立可运行 repair work，并把 required mapping 转向其可验证 outcome。
PlanAdmission 接受 remap 后才清除旧 verification wait。拒绝产生的 typed `DecisionFeedback`
按决策范围分别处理：Plan Admission 拒绝由 `ReplanRequest` 返回 Replanner；普通 Execution
Admission 拒绝写入 `ExecutionProposalRejectedData`，在同一 accepted Plan/SubGoal 上局部重提。
等价反馈按不含 event sequence 的 digest 计数，达到 `same_feedback_revision_limit` 后局部
fail closed，禁止用全局 Replan 掩盖来源选择错误或重放原 Tool。

repair SubGoal 必须保存被修复 frozen SubGoal 的 canonical version ref。Execution Proposer 只
获得依赖与递归 repair-lineage 闭包中的 admitted evidence；不同主题的候选不会进入其 schema。
模型对 observed URL 选择 candidate id，确定性代码再绑定 canonical URL，避免要求模型复制 locator。
verification gap 使用独立 `max_evidence_repair_revisions`；steering、assumption、coverage 和
capability 变化继续使用 `max_plan_revisions`，两类预算不相互吞噬。

预算按 planning、execution proposal、external delegation、verification 和 synthesis 分类，
先 reserve 再调用外部能力，最后 charge/release。Tool/Agent success、Artifact 存在、Verifier
单独通过都不能直接完成 Project；Completion Gate 要求全部 active requirement 已 verified 或
由用户显式 waived，且 final Artifact 与 assessment evidence 齐全。

## 6. Conversation boundary

普通 Conversation 保持 request-local ReAct，只持久化 messages、Observation/Feedback、usage、
execution order、并发批次、final message 和跨领域资源引用。旧 `WorkingPlanSnapshot` 输出、恢复
admission 和 trace 字段已删除。用户明确要求跨交互持续和后续控制时，Conversation 可以调用
`InvestigationProjectService.create`，但只保存 `ProjectReference`；Project definition、Plan、状态和
Completion 仍由 Project aggregate 唯一拥有。

## 7. 已执行验证

本轮当前工作树定向验证：

- 历史 B03 live baseline：passed（仅证明当时 revision 的 `delivered=false`），archive
  `20260728T123013.176272Z-42316-76b47a9c`；
- IP01 在无限同反馈问题修复前 600 秒仍 active，archive
  `20260728T125249.466459Z-45552-410f6188`；修复后同反馈有界暂停，未重复原 Tool；
- IP01 搜索质量失败 archive `20260728T130808.632067Z-17988-0d9bfe10`，Verifier 拒绝无关来源；
- strict `json_schema` 与 DeepSeek 不兼容的 baseline 为
  `20260728T135746.012529Z-20360-ce914ffb`；显式 JSON Object Adapter + 关闭 thinking 后，
  `20260728T143217.175037Z-28784-bb0ed0e8` 在 59.7 秒内所有 typed parse 通过，
  `environment_failed=false`，可计 28,828 token；
- 同一最新 archive 仍以 `verification_repair` 暂停：MCP/A2A evidence 不满足时间、版本、来源
  要求，后续 revision 又试图覆盖 frozen work；这是一项新的 Project 行为缺口，不属于
  Provider Adapter；
- Tavily 达到 1000/1000 plan usage 后，运行配置已显式切换至 Firecrawl；archive
  `20260728T154127.518791Z-8584-3899be03` 证明三次生产 Search 成功、无 Tavily 调用且
  `environment_failed=false`；Plan v2 新增并执行一次 repair、未重放原 execution，随后因 evidence
  仍不足和 SubGoal version/supersession 违反 Admission 而暂停，因此 Provider 已解除、repair 有
  局部收益，但用户报告仍未交付；
- `20260729T074104.409971Z-17204-9d2e066f` 证明 `web_search` 的搜索加两次正文读取超过旧
  20 秒治理窗口；契约调整为 60 秒后，相关 Tool 测试 29 passed；
- `20260729T074537.177810Z-46796-aeb55489` 证明能力不匹配拒绝分支错误地用位置参数构造
  `DecisionFeedback`，且 Execution Proposal 的开放字符串允许选择未被当前 SubGoal 匹配的 Tool；
  当前 schema 已把 Tool/Agent identity 收窄为 deterministic matching inventory；
- `20260729T075635.355657Z-17460-0a4c21f8` 在 120.5 秒内执行 8 次真实搜索、无重复 proposal，
  并找到含 2025-06-30 与 2025-06-09 变化的 A2A Releases 页面；但 Project 最终因 A2A repair
  证据未被完整物化而暂停。该 archive 同时出现 Firecrawl 429/402，故 release harness 将其标为
  环境失败，不能作为 target acceptance；
- `20260729T080725.690825Z-11020-b4ee8959` 在新显式 URL reader 绑定下仍因 Firecrawl
  `/v2/search` 账户级 HTTP 402 终止，确认剩余重跑阻塞在搜索 Provider 外部状态，而非 URL reader；
- Firecrawl Web Search Adapter 已删除；SerpAPI 真实冒烟取得 GitHub Releases，Provider 合约
  覆盖 Google organic results、合法空结果、错误和 limit；本地密钥只保存于 ignored `.env`；
- SerpAPI IP01 archive `20260729T084450.226963Z-52148-7d7045a6` 已由 Verifier 确认 MCP
  `2025-03-26`、`2025-06-18`；`20260729T085601.806550Z-18988-2e0c1eba` 暴露 repair evidence
  跨主题消费并耗尽 revision 的产品缺口，均未交付报告，不能作为 acceptance；
- 后续同输入失败 trace 依次证明并收敛：repair-of-repair 丢失同主题 ancestor evidence、精确
  capture/search 重放、evidence repair 吞噬 semantic Plan budget，以及模型复制 URL 导致的
  structured parse 假性 `provider_unavailable`；完整因果与 archive 见 ADR 0008；
- IP01 target archive `20260729T101501.732689Z-53628-6c5f02f2`：`completed /
  completion_gate_passed`，Plan v3，3/3 outcome satisfied、5 条 admitted evidence、可读报告存在，
  `environment_failed=false`，`1 passed in 86.42s`；
- 最新封闭环境全仓回归：705 passed、4 warnings、116.10 秒；变更范围 Ruff：通过。

以下完整低层回归不等于 clean release E2E：

- Provider 迁移前全仓 `uv run pytest -q tests`：694 passed、0 failed、4 warnings，
  213.42 秒；本轮第一次未隔离开发机 MCP 的全仓运行为 704 passed、1 个 Notion MCP
  initialize setup timeout。显式关闭外部 MCP 后该节点 1 passed，最终同配置全仓 705 passed；
  MCP contract tests 仍由用例自行启用 fixture。前一次错误保留为测试环境隔离风险；
- 历史 LT01–LT13 diagnostic matrix：13 passed；其中 LT09 后续审计发现没有实际运行 Conversation
  baseline，其对比结论已撤销，当前 catalog 为 LT01–LT08、LT10–LT13；
- AgentGateway quality gate：1 passed；
- durable Agent uncertain-submit/restart reconcile 自动断言 Provider submit count=1；
- user pause/resume、system pause non-bypass、OutcomeUnknown fail-closed 已通过应用路径测试；
- `completing` 与 `cancelling` 进程崩溃恢复已通过故障注入；恢复不重复 final synthesis，
  Provider cancel effect=1；
- changed Python files `ruff check`：通过；
- `scripts/check_layers.py`：unknown/missing package、cycle、forbidden edge 均为 0；
- Python `compileall`：通过。

IP01 不再是开放发布阻塞。完整发布前仍必须执行并归档：

- live GitHub/Notion/Web/A2A 正式入口矩阵和重复运行方差；
- 若要提出 Project 优于 Conversation 的恢复声明，需新增真实同输入 paired baseline，比较完成率、
  错误副作用、模型轮次、token、延迟和恢复结果；
- clean matching revision 的 release E2E、layer gate 和 revision-bound trace archive。

## 8. 运维入口

Project worker 使用独立 queue：

```powershell
uv run personal-agent worker --queue investigation
```

API key 环境变量使用 JSON principal mapping：

```text
PERSONAL_AGENT_API_KEYS={"key":{"tenant_id":"tenant-a","user_id":"alice"}}
PERSONAL_AGENT_ADMIN_API_KEYS={"admin-key":{"tenant_id":"tenant-a","user_id":"root"}}
```

旧 `key:user` 格式会 fail closed，不提供兼容解析。

鉴权启用时，直接 Tool HTTP 入口中的 tenant/user 必须与 authenticated principal 一致；调试
数据库重置只允许管理员 key。
