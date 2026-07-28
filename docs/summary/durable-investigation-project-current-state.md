# Durable Investigation Project 当前实现

## 1. 结论与证据边界

Investigation Project 已成为独立的 durable 产品入口，而不是 Conversation 的隐藏模式。
正式 API 可以异步创建、只读查询、steering、审批、暂停、恢复和取消；worker 从 PostgreSQL
journal 重建 Project，并按 accepted Plan 计算 ready set、dispatch、join、coverage 与
Completion。

当前已执行的 LT01–LT13 使用生产 Domain、Application、PostgreSQL store、worker queue 和
Artifact owner，但 semantic model 与外部 Provider 是 scripted/frozen Port。它们属于
diagnostic E2E，不是 live model/provider release evidence。当前不得声称该能力已通过发布门禁。

## 2. Canonical owners

| 事实 | 唯一 owner/写入口 |
| --- | --- |
| Project definition、Plan、SubGoal、waiting、budget、verification、completion | `InvestigationProject` aggregate + `InvestigationProjectService` |
| Project persistence | `PostgresInvestigationProjectStore` definition + append-only events |
| child Agent definition、submission binding、projection | `AgentGateway` + `PostgresAgentRunStore` |
| Artifact 正文与私有路径 | `ArtifactService` |
| Tool 执行事实、policy、idempotency、audit | `ToolGateway` |
| queue lease/retry/dead letter | `PostgresWorkerQueueStore` |
|开放语义 Proposal/Assessment | Project structured-model Ports |

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
SecurityScope 校验。

## 5. Project state and control

Project 状态为 `planning -> active -> paused/cancelling/completing -> terminal`。steering 只修订
未冻结 SubGoal；accepted/running/completed work 不被 revision 覆盖。审批绑定
AuthorizationDigest；取消会调用已关联 child run，并将终态后返回的 Artifact quarantine，
不会重新打开 Project。

暂停原因是 Project journal 的 canonical fact。`resume` 只解除 `user_paused`；预算、能力、
审批或修复条件造成的系统暂停必须由对应 typed condition 解除。恢复扫描不会重新入队任何
paused Project。

预算按 planning、execution proposal、external delegation、verification 和 synthesis 分类，
先 reserve 再调用外部能力，最后 charge/release。Tool/Agent success、Artifact 存在、Verifier
单独通过都不能直接完成 Project；Completion Gate 要求全部 active requirement 已 verified 或
由用户显式 waived，且 final Artifact 与 assessment evidence 齐全。

## 6. Conversation boundary

普通 Conversation 保持短生命周期 ReAct，只持久化 messages、Observation/Feedback、usage、
execution order、并发批次和 final message。旧 `WorkingPlanSnapshot` 输出、恢复 admission 和
trace 字段已删除。恢复后模型直接消费 committed typed inputs；它不会隐式创建 Project。

## 7. 已执行验证

- 最终代码状态全仓 `uv run pytest -q tests`：651 passed、0 failed、4 warnings，
  187.95 秒；
- LT01–LT13 diagnostic matrix：13 passed；
- AgentGateway quality gate：1 passed；
- durable Agent uncertain-submit/restart reconcile 自动断言 Provider submit count=1；
- user pause/resume、system pause non-bypass、OutcomeUnknown fail-closed 已通过应用路径测试；
- `completing` 与 `cancelling` 进程崩溃恢复已通过故障注入；恢复不重复 final synthesis，
  Provider cancel effect=1；
- changed Python files `ruff check`：通过；
- `scripts/check_layers.py`：unknown/missing package、cycle、forbidden edge 均为 0；
- Python `compileall`：通过。

发布前仍必须执行并归档：

- live structured model + live GitHub/Notion/Web/A2A 的 LT 正式入口矩阵；
- LT09 同输入 paired baseline 的完成率、错误副作用、模型轮次、token、延迟和恢复结果；
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
