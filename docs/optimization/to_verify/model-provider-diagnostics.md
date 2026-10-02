# Provider 失败诊断交接

`MODEL-PROVIDER-DIAGNOSTICS-001` 处理模型服务失败后具体错误事实未进入运行日志的问题，准入由 [Future 队列](../../future/design-optimization-backlog.md)拥有。上位研究问题见[未收敛总览](../claim-revision-nonconvergence.md)。

## 失败事实与最早责任

2026-10-02 原研究 E2E 的 writer 请求及两次重试均收到 MiMo 429，用户入口返回 503。实发请求、状态和重试时间已保存，日志仅包含 `provider_rejected`。`OpenAIModelClient._provider_unavailable` 从 SDK 异常转换时只传递状态、host 和 retryable，具体错误码、错误信息、请求 ID 与重试提示丢失。旧证据见[原始日志](../../../.tmp/research-joint-goal-20261002/target/preserved/e2e-server-cihe31c2/web-process.log)。

## 解决机制与防护

Provider 拥有外部错误事实。Adapter 在读取边界将 SDK `body` 和白名单响应头转换为不可变 `ProviderFailureDiagnostics`，字段为 `error_code`、`error_type`、`message`、`request_id` 与 `retry_after`。只接受标量并限制长度；密钥、认证值与 URL 脱敏后再进入内部异常。完整响应体、请求正文和其他响应头不复制到日志。不存在的字段保持未知，按实际返回判定错误原因。

`ModelInvocationUnavailable` 携带同一诊断对象，现行唯一 retry owner 记录每次失败的诊断；最后失败传递给 Conversation，由其原日志出口记录。公有 HTTP 响应沿用稳定消息；重试次数、退避、thinking、模型、研究和 Verifier 契约保持。新增结构沿现有正式模型 Port 到日志消费者可达，不增加存储或开关。

## 验证预声明

本轮先执行两个固定 SDK 失败场景，各一次：历史 writer 实发载荷配代表性 JSON 429；同一载荷配非 JSON 429。替代边界仅为外部错误返回，经过真实 SDK、生产 Adapter、retry 及 Conversation 失败转换，分别校验具体诊断保留、脱敏、缺失表达、同载荷重试与稳定公有消息。用本轮前源码消费相同返回作为反事实。该 Offline Eval 只证明诊断链，不用代表性错误信息认定 MiMo 实际原因。

随后执行原中文自然输入的正式 E2E 一个样本一次，预算沿用 2,000,000 tokens、32 回合、48 工具、480 秒模型请求及 7200 秒 HTTP。若实际 Provider 失败，核对实发错误与日志诊断一致；全部原用户结果保留。重现后停止新增付费样本及同方向补丁，按真实诊断归因。预声明及代码身份保存到[本轮归档](../../../.tmp/mimo-provider-diagnostics-20261002/plan.json)。

## 本轮局部结果

两个固定失败场景各执行一次，候选诊断链 2/2 合格；本轮前源码对相同返回均丢失具体诊断，为 0/2。两个版本均保持原载荷、三次请求、2 秒与 4 秒退避、429 分类和稳定公有错误消息。代表性 JSON 返回的白名单诊断经过全部重试及最终 Conversation 日志，秘密值、完整正文及非白名单响应头没有进入日志；非 JSON 返回只保留请求 ID 和重试提示，具体原因保持未知。该回放没有付费模型调用，证据见[局部报告](../../../.tmp/mimo-provider-diagnostics-20261002/offline-summary.json)。

原正式 E2E 一个样本一次为 0/1，全部 93 个 MiMo 请求均返回 200，实际 Provider 失败诊断检查点未触发。第 19 版八条 claim 来源通过，覆盖恢复漏放与最终验收项转录失败分别由原子问题记录拥有；入口达到 32 回合后返回 limitation。原始用户结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-02-mimo-诊断补齐后的正式验证)拥有。保留已成立的诊断链反事实和生产接入，实际 MiMo 错误体条件继续待验证，上次 429 的具体原因保持未知；不追加付费样本。[完整报告](../../../.tmp/mimo-provider-diagnostics-20261002/REPORT.md)保存实发请求、代码身份与成本。
