# Provider 失败诊断交接

`MODEL-PROVIDER-DIAGNOSTICS-001` 处理模型服务失败后具体错误事实未进入运行日志的问题，准入由 [Future 队列](../../future/design-optimization-backlog.md)拥有。上位研究问题见[未收敛总览](../claim-revision-nonconvergence.md)。

2026-10-24 发现的本地输出失败与公有 HTTP／SSE 归因问题，已按[整个 Loop Schema 统一设计 §7](conversation-loop-schema.md#7-失败分类与-http-边界)接入生产，原三份失败产物到实际 REST／SSE 注册路由的 4 次 Offline 请求通过。该项处理本地输出和错误呈现，不是新的网络断连诊断；[回放范围](../../../.tmp/loop-schema-redesign-20261024/p5-interface-replay.md)与历史传输结论分别保留。

## 2026-10-23 传输异常诊断缺口

LongDS 的 MiMo 第 4 次请求在响应读取阶段抛出 `RemoteProtocolError`，应用日志只有 `provider_transport`，当前证据足以定位诊断信息的丢失边界，但不能确定断连方。原运行与成本由[评测登记](../../evals/02-current-case-inventory.md#2026-10-23-mimo-两轮流程及独立评分)拥有，本节只分析诊断覆盖。

现行 `_provider_diagnostics` 只读取 SDK 的错误响应 `body`、`response.headers` 和请求 ID。当前 SDK 将读取异常以 `raise APIConnectionError(...) from err` 保留在异常链；该类连接错误没有可供当前提取器消费的错误响应。Adapter 继续以 `raise ... from exc` 保留链，运行日志却只投影分类和上述诊断，不持久化底层异常类型、脱敏消息或原因链。因此本例 `provider_diagnostics` 为空；不能将未写入日志解释为运行时没有底层原因。

另一个缺口在评测观察器：`retrieval_acceptance_server.py` 的 `observed_send` 只有在完整 `Client.send` 返回后才保存状态码，失败时只写 `exception_type`。非流式 HTTPX 会在此期间读取整个正文，所以普通日志已有 HTTP 200，观察侧仍是 `response_received=false`；后者表示没有完整返回，不能解读为未收到响应头。响应头到达、中途字节、首末包时间、底层异常消息和实际连接路径均未在本次归档保存。SDK 层观察器也仅保存包装后的异常类型。

此前两个 429 反事实仅证明 HTTP 错误体诊断链，并未覆盖这类连接／读取异常；原 2/2 成绩保持，本例暴露的是未覆盖边界。已保存证据中的缺失消息和字节不能事后补造。2026-10-23 用户已授权补齐定位信息；本轮先实施下述诊断切片，传输策略及原任务未知消费保持。

源码坐标：[`_provider_diagnostics`](../../../src/personal_agent/infra/structured_model.py)、[`_log_model_failure`](../../../src/personal_agent/application/conversation/service.py)、[正式采集观察器](../../../evals/product_baselines/retrieval_acceptance_server.py)。[本次只读审计](../../../.tmp/mimo-transport-document-audit-20261023/report.json)固定实际请求、失败、源码和当前安装依赖身份。工具调用传输覆盖与下一步取证由[传输记录](../model-provider-transport.md#2026-10-23-longds-工具调用断连与诊断覆盖)拥有。

### 诊断补齐规格与架构分析

目标是让维护者区分未连接、等待响应头、响应体中断及完整读取。业务目标、模型决策、重试、超时、用量和完成判断均沿用原 owner。正式入口仍经 Conversation 的模型 Port、现行包装器和 `OpenAIModelClient`；缺口属于 Adapter 的传输观测，没有新增业务能力或持久状态。

| 需求 | 必须观察到的结果 |
| --- | --- |
| D1 | 连接／读取失败经 SDK、Adapter、Conversation 转换后，内部诊断保留有界异常链的类型和允许的脱敏消息；公有错误保持原值 |
| D2 | HTTP 200 后中断时，仍能读取实际状态、白名单响应头、头到达时间、首末正文块时间、字节／块数和正文是否完整；这些时间以单次请求开始为原点，字节是 HTTPX 交付给消费者的原始正文块，不是 TCP 包或 token |
| D3 | 记录实际 TCP 连接目标及可获得的 socket 对端。连接复用时不虚构新的连接事件；信息不可得时保持未知。代理环境变量不冒充实际路由 |
| D4 | 原请求正文、最终 SDK 返回、异常分类、次数、流式设置和资源关闭责任保持；观测失败不改变调用结果，日志不含密钥、完整错误体、Prompt 或工具参数 |

依据[横切架构](../../architecture/cross-cutting.md)，Adapter 内以 HTTPX 官方 request／response hook 和透明字节流包装组合观测；继续使用 SDK 的 `DefaultHttpxClient` 默认连接池、代理和重定向配置。每个 HTTP Request 的 extensions 持有本请求的 typed recorder，避免 deadline 工作线程和多次修复之间串用状态。响应 hook 在正文读取前固定响应头与实际 socket 对端，流包装只计数并原样 yield／close；不提前读取、不复制正文、不加超时或重试。异常链最多八层，只记录传输异常的脱敏消息；SDK HTTP 错误的完整字符串不记录，原白名单错误体提取保持。

`ProviderFailureDiagnostics` 扩展 typed 异常链和传输快照；同一对象沿原错误 Port 到 retry 和 Conversation 日志。HTTPX／SDK 特有实现集中在 `infra/model_transport.py`，由原 `_client()` 显式装配，契约仍在 `capabilities/contracts/model.py`；Application 不依赖 HTTPX。正式采集观察器消费同一快照，并明确它是 `Client.send` 返回／失败时的观察；SSE 后续读取结果由生产正文日志及最终 SDK 观察拥有。删除观察器仅写异常类型的旧失败投影，保留旧归档的原身份和未知字段，不回填历史值。新增结构仅包含本次诊断所需的快照、异常帧及请求内 recorder，不引入通用事件总线、配置轴或存储。

### 官方依据与取舍

2026-10-23 核对安装源码 `openai==2.36.0`、`httpx==0.28.1`、`httpcore==1.0.9`。HTTPX 的[response hook](https://www.python-httpx.org/advanced/event-hooks/)发生在读取正文前；[trace 和 network_stream 扩展](https://www.python-httpx.org/advanced/extensions/)可提供连接目标、阶段和 socket 对端。trace 事件名随版本变化，只按已核对名称投影白名单值，其他事件不解析完整 payload。SDK 当前源码在连接失败时以 `raise APIConnectionError(...) from err` 保留原因；[官方错误说明](https://developers.openai.com/api/docs/guides/error-codes)说明连接错误需要核对网络及代理，但不能据此判断本例断连方。

已实际打开 [MiMo API 接入](https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration)及[错误码](https://mimo.mi.com/docs/zh-CN/api/guidance/error-codes)：长响应建议流式；思考模式的后续工具轮次建议保留历史 `reasoning_content`；工具语义不稳定另有关闭 thinking 的建议。本例是正文读取失败，尚无语义输出，不能据此关闭 thinking 或更换协议。当前只补取证，不把官方建议当作本工程根因证据。

### 本轮验收与实施顺序

先封存修改前源码和完整阶段输入，再执行同一正式 SDK 调用边界的 Offline Eval。输入采用 LongDS 失败请求 `7e50c5bb4e9748f6b14c4709cdff5ec7.candidate.request.json` 及其原实发 body；正常对照使用该运行前三次已封存的完整 SDK 响应。仅把外部 HTTP 服务替换为本机服务，载荷逐字节核对，正常响应按完整 JSON 值核对；不执行模型生成的工具。

固定两例、修改前／候选各一次：①真实 SDK 收到 200、若干正文块后，由本机服务在 chunked 结束前关闭，检查 D1–D4 及实际 Conversation 失败转换／日志、采集旁路；②返回已封存正常响应，检查正文完成、原值、用量和关闭行为保持。回放只调用真实 SDK 阶段及其实际错误转换，不恢复任务 Journal 或调用预算准入。注入的响应头与断流是外部故障反事实，不声称重现了原 MiMo 缺失消息。每请求 480 秒，SDK 重试零，每例仅一次；只使用回环网络，付费模型／工具执行均为零。候选任一必要判据失败则停止本轮准入，不重跑整任务。静态依赖、导入、文档及 diff 检查另行记录。

首次脚手架在请求前因 Conversation 方法签名变化停止，零网络；修正为直接消费真实 SDK 阶段错误后，`offline-v2` 两组各两次回环请求正常完成。候选已记录异常链、200、37 正文字节与三块、首末时间及实际 `127.0.0.1:7892` 对端，但回放误将目标服务端口当作实际连接端口，导致该断言失败；实际系统代理确实承接了本机请求。该结果保留，不能将观察到代理解释为诊断失败或原 MiMo 根因。修正仅限回放进程设置 `NO_PROXY=127.0.0.1`；`offline-v3` 已观察到直接连接，但脚手架又把 Python tuple 与日志 JSON array 直接比较，造成错误失败。改为按 typed contract 的 JSON 投影比较，两组使用相同隔离环境执行固定两例；这两个评测错误均不调整生产候选或通过标准，历史失败记录保持。

顺序为 D1–D4 契约及最小观测实现、原 Adapter 和观察器迁移、完整阶段回放、当前架构／专题／队列同步及评审。反事实必须显示修改前丢失诊断而候选具备诊断，且正常对照保持。归档为 `.tmp/mimo-transport-diagnostics-20261023/`。

本轮 D1–D4 已实现，有效组 `offline-v4` 修改前 1/2、候选 2/2：旧断流诊断为空，候选保留完整交接；正常对照的值、用量及逐字节请求保持。SDK、HTTP 旁路及 Conversation 日志消费一致，付费模型及工具执行为零。样本、累计本机 HTTP 及原始失败由[评测登记](../../evals/02-current-case-inventory.md#2026-10-23-模型传输诊断真实阶段回放)拥有。该局部诊断缺口已达到固定判据；原长任务及网络中断原因仍独立未解决，旧一次未知消费保持。

独立评审补充了 D4 的真实 SDK 重定向边界：HTTPX 复制 extensions，候选串接旧 trace 会把最终读取失败回写前一请求；SDK 的连接错误仍可引用初始 Request，故交接错取 307 而不是最终 200。评审用同一完整真实载荷、本机 307 后 200 断流已复现，属于本轮观测回归。实施前固定修正：每个新 Request 替换本模块 trace，只继承外部 trace；失败快照从实际底层异常关联的 Request 取得，旁路同样消费失败实际请求。保留 SDK 默认重定向及请求字节。

追加该必要反事实后，固定三例修改前／候选各一次；重定向例预期两次本机 POST、同一正文，最终失败状态 200、未读完整、失败对端与正文计数正确，307 的 recorder 不接收最终 200 的失败事件。复用连接时 `connect_*` 允许未知，实际 `peer_*` 必须对应本机服务。前两例判据不变。独立评审的复现及 v4 成绩保持，修正前源码另存 `before-redirect/`；这是有依据的回归修复，不靠新增重试或全任务重跑验收。

修正前快照回放 `redirect-red` 为 2/3，重定向断流例明确失败；最终 `offline-v5` 修改前 1/3、候选 3/3，修正闭合该评审发现。最终 200 的完整异常与计数进入日志／旁路，前一 307 不再被写入读取失败，正常值、用量及原请求字节保持。本轮仅修正诊断归属，网络故障和长任务的验证边界保持。

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
