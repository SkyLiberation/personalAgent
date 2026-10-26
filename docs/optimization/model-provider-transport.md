# 模型服务传输失败阻断核验

## 2026-10-24 MiniMax medium 完整流程的响应头前断连

用户提高思考档位后，新36轮轨迹在首轮因传输未知停止，未交付回答；完整运行及预算由[研究 Spec §9.12](to_verify/knowledge-decision-delivery.md#912-minimax-medium-的完整36轮验证)拥有。本节只读定位，不修改生产传输或自动重跑已关闭轨迹。

实发请求121f2723315a40c48a8009b1b869ca19使用MiniMax-M3.1-Flash、adaptive＋medium、非流式工具调用、32,768输出上限；23条完整消息，109,823字符，不把字符数当tokens。诊断链为openai.APIConnectionError→httpx/httpcore.RemoteProtocolError（Server disconnected without sending a response）；http11.receive_response_headers.failed，285.4905秒，body_bytes=0／body_chunks=0，实际连接127.0.0.1:7892。当前urllib.getproxies读取的是Windows系统代理，环境HTTP_PROXY等并未显式设置。证据说明本机代理路径在响应头之前断开，不能认定是哪一端主动关闭、发生了内容过滤或达到了输出／上下文上限。

后继f99f7260c379403cbd89e700f7d75322与该失败请求逐字段完全相同，属于既有有界重试；7.234秒返回完整tool_calls及已知usage，但不能覆盖前次未知消费。其read_artifact提议未成为已接受执行；当前run保留provider_usage_complete=false并返回limitation。原始采集13物理请求、479,230已知tokens、未知1均不改写；观察器按准入规则拒绝评分，是预期停止而非新的评分器缺陷。

须区分触发故障与最终停止责任：网络曾断开，但重试已恢复模型响应；该轨迹最终不再推进的是当时“出现未知用量即停止”的预算／验收规则。原预声明执行正确，不说明恢复后的提议不可执行。用户于 2026-10-24 明确取消这一停止线，当前改为保留未知费用、按已知消费阈值继续；实施、验收和新的完整运行由[研究 Spec §9.13](to_verify/knowledge-decision-delivery.md#913-用量未知不再单独停止并继续完整验证)拥有。不新增费用估算或预留账本，旧关闭轨迹和一次未知消费仍保持原身份。

停止审计最初错误地要求这份未知终止轨迹的全部原生调用已配对；实际末尾含上述未执行提议，project_model_history明确拒绝缺结果／拒绝的续接。审计修正为报告该未决尾部和原拒绝，不删原文或补造tool结果，也不将此终止场景记为恢复／完整配对通过；已冻结的7份程序原字节和输入绑定、SDK实际档位及源码身份另行核对。

零模型只读探测：沿默认系统代理与关闭系统代理读取的 `trust_env=False` 对照访问同一未认证 `GET https://api.minimax.cn/v1/models`，均返回 401，分别约 0.422／0.266 秒；未携带凭据、未改系统配置、未发送生成请求。关闭 HTTPX 的代理读取不能排除 TUN 接管，单凭该 GET 也不能证明长请求稳定。源码、诊断与探测在[本次归档](../../.tmp/minimax-medium-longds-e2e-20261024/network-readonly-probes.json)，完整失败响应原件位于 l2-prefix-17/sdk/121f2723315a40c48a8009b1b869ca19.candidate.response.json。

用户增加直连规则后，北京时间 2026-10-24 15:13—15:18 的[只读复查](../../.tmp/minimax-proxy-check-20261024-0715/report.json)确认默认应用仍连接 `127.0.0.1:7892`，系统 DNS 将 API 域名解析为 TUN 虚拟地址。进一步以同一本机代理建立三次 CONNECT＋已校验证书的 TLS 握手，[出站连接记录](../../.tmp/minimax-proxy-check-20261024-0715/tls-outbound-correlation.json)每次都出现代理核心进程直接连接 `101.132.45.96:443`，该地址属于同次独立 DNS 查询返回的 MiniMax API 地址。当前路径因此是应用经本机代理后直接连接 MiniMax；不等于应用绕过本机代理，也不证明先前断连根因或长请求稳定性。客户端保存的新增规则为 `DOMAIN,https://api.minimax.cn,DIRECT`；按 [DOMAIN 完整域名匹配规则](https://wiki.metacubex.one/config/rules/#domain)，应去掉协议头，使用 `DOMAIN,api.minimax.cn,DIRECT`。未获取运行中核心的命中规则，不能把当前直连归因于这条新增规则；本次没有修改配置或调用模型。

用户要求让请求绕过代理后，先进行隔离网络诊断，不改变生产 Adapter 或全局代理。当前物理网卡为 `WLAN 2`，而真实 API IP 与虚拟 IP 的系统默认路由均指向 TUN；仅关闭 HTTPX 环境代理不能完全绕开本机代理核心。采用 [Windows `IP_UNICAST_IF`](https://learn.microsoft.com/en-us/windows/win32/winsock/ipproto-ip-socket-options)在连接前指定物理网卡，直接向公共 DNS 的 HTTPS 接口查询当前 API IPv4，再向其中一个地址发送一次未认证的 `GET /v1/models`；两段 TLS 均保留原域名和证书校验，不固定生产 IP。判据为 API 返回 HTTP 响应、请求进程持有由物理网卡 IP 到真实 API IP 的连接，并保存套接字选项与连接证据。每个阻塞网络操作超时 8 秒，失败即结束，不重试、不生成模型、不改变路由、DNS 或代理配置。产物独立保存在 `.tmp/minimax-direct-request-20261024/`；只证明该隔离请求的网络路径，不计完整 E2E 或长请求恢复。[HTTPX `NO_PROXY`](https://www.python-httpx.org/environment_variables/#no_proxy)是正式客户端可复用的标准域名排除机制，但本机 TUN 与 DNS 排除仍需另行处理，当前不引入自定义生产解析器。

北京时间 15:25 的[实际绕过报告](../../.tmp/minimax-direct-request-20261024/report.json)通过上述判据：公共 DNS HTTPS 返回 200；API 返回未认证请求预期的 401。两段连接都读取到物理网卡索引 27；API 连接由请求进程持有，源为 `192.168.3.34`，对端为当次解析的 `101.132.45.96:443`，TLS 校验开启，代理核心在探测前与过程中均没有该目标地址的连接。新增模型调用、生产代码和系统网络配置改动均为零。已经证明独立请求能完全绕过本机代理；正式 E2E 客户端尚未迁移，原长请求的稳定性与断连根因仍未验证。

服务端用量查询也已核实：[MiniMax 官方 M Plan FAQ](https://platform.minimax.cn/docs/m-plan/faq)提供只读 `GET https://www.minimax.cn/v1/token_plan/remains`。使用当前配置凭据的[实际查询](../../.tmp/minimax-usage-inquiry-20261024/quota-query.json)返回 HTTP 200、业务状态码 0，五小时额度剩余 92%、周额度剩余 97%。它提供套餐窗口额度，不是失败请求的 token 明细；返回的计数字段为 0，不能据此推断消费为 0。当前公开文档未找到按失败文本请求 ID 补查精确 token 的接口，且原失败未收到响应头或服务端请求 ID；重试响应的 `usage` 仍只归重试请求。此查询不能补齐旧请求的未知费用，也不构成套餐耗尽导致停止的证据。

本轮重复阻塞复审复用已核对的[优秀智能体请求／重试机制](../agentRef/runtime-recovery.md#32-单请求超时重试与任务截止)：OpenHands固定SDK实现区分单次attempt、流式空闲和任务截止，Gemini固定实现按异常及尝试数处理取消／重试；它们都不能证明本地代理可靠或允许清除未知用量。与此前MiMo的HTTP200后正文断流不同，本次没有响应头，不能把两次失败视作相同断连根因。[MiniMax官方协议](https://platform.minimax.cn/docs/api-reference/text-chat-openai)提供stream／stream_options，[HTTPX配置](https://www.python-httpx.org/environment_variables/)提供trust_env及代理控制。流式覆盖或隔离代理路径是可区分的后续候选，需要以本次完整失败阶段分别验证；当前只记录待证方向，未准入新生产补丁或付费实验，不把同时改变网络路径与协议后的成功归因于medium。

## 2026-10-23 原生工具会话续接规格

状态：用户授权按服务方文档补齐，生产候选已接入并完成实际阶段与协议局部验证；新的完整流程已在第 3 轮按停止线结束，完整长任务未通过。目标是恢复完整工具会话协议，不同时提高思考强度、调整业务 Schema 或放宽权限。参数正确率、完整回答和长任务继续按实际结果计分。

### 问题、依据与需求

MiniMax low 正式首轮在两次 Python 参数拒绝后停止，三键及 16 文件齐全，最新反馈已实际送达；错误是空字符串程序引用与字符串版本号重复。五个工具决策请求都重新发送 `system/user/system` 状态快照，没有上一轮原生 assistant／tool 历史。同轨迹已有 `reasoning_content`，但未被正式续接消费。完整审计见 [Python Spec §3.6](to_verify/python-data-analysis-tool.md#36-minimax-首轮的参数修复再次失败2026-10-23)。这证明协议覆盖缺口，不证明它是参数错误的唯一原因。

2026-10-23 核对 [MiniMax 工具循环](https://platform.minimax.cn/docs/guides/text-m3-function-call)、[DeepSeek thinking 工具续接](https://api-docs.deepseek.com/guides/thinking_mode/)、[OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)、[Claude thinking 工具工作流](https://platform.claude.com/docs/en/build-with-claude/thinking-tool-workflows)与 [Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking)：保留原生动作消息并关联工具结果是共同方向，思考正文、完整内容块、签名或 reasoning items 的具体要求随协议和模型不同。本轮只实现现有 OpenAI 兼容 Adapter 的实际续接，不新增 Anthropic／Gemini Adapter。既有 AutoGen／OpenHands 的实际工具装配来源继续复用[参数参考](../agentRef/tool-execution-and-safety.md#10-python工具的参数结构与字段说明)，不以外部能力代替本地验证。

| 需求 | 可观察契约 |
| --- | --- |
| H1 | Adapter 返回并保存实际 assistant 消息的完整服务方字段，保留 reasoning、原 tool_calls 和原参数字符串；不从解码后的 Proposal 重造模型响应，不修改错误参数 |
| H2 | 下一模型请求按顺序带回 assistant 消息，并以原 tool_call_id 一一配对真实执行结果、拒绝或控制动作接纳结果；拒绝不表示执行，准备提交不表示回答完成 |
| H3 | Journal 是当前 run 的响应和执行事实唯一持久写入口；恢复不重调模型或重执行工具来补历史，模型／服务方或主体不匹配时拒绝续接 |
| H4 | 模型消息使用当前合法可见输入及原预算；已移出 Context 的旧结果不能经原生历史再次进入。压缩按完整已结算交换移出，最近拒绝、未决执行和未配对调用保持保护，不产生孤立 tool 或 assistant |
| H5 | structured 最终提交仍消费前一轮原生工具结果；Plan、只读、Python、并行兄弟拒绝与 prepare_final 均沿同一续接契约，不形成 Python 特例或第二套模型循环 |

### 架构分析与最小方案

正式路径仍为 Conversation → 原模型 Port／治理及计量包装 → 既有 OpenAI 兼容 Adapter。服务方消息是外部拥有的数据，由 Adapter 在 SDK 边界验证并返回 host/model 绑定的 typed envelope；Application 不识别或拼装 reasoning 字段。Port 的既有 request／response 增加必要的 typed 会话续接字段，不新增 Provider Registry、模型路由或部署开关。

Conversation Journal 保存同一次实际决策的响应及其输入边界。工具执行、拒绝、Plan 和提交状态继续由原 owner 产生；原生 tool 消息是这些 canonical facts 的只读投影，不成为第二份可独立修改的执行账本。独立的 Conversation 续接物化模块负责按 ID 配对、结果分组及已压缩交换选择，主循环只在真实响应提交、控制动作接纳及请求物化点调用；Adapter 负责服务方 wire。需补齐当前控制动作没有配对结果的缺口，所有接纳都在实际准入之后产生，不用泛化“已执行”或缺失默认为成功。

保留 typed 当前状态说明作为事实、权限和预算依据；已在原生结果中物化的相同正文不重复塞入全量状态块。已有历史压缩机制继续唯一拥有摘要与覆盖键，续接物化服从该选择，不让完整原始消息绕过压缩。由同一 Journal 恢复当前 run 的协议记录；历史封存未保存这些字段时不得猜补后冒称可恢复。迁移检查当前运行与存量消费者，旧只用状态快照替代原生续接的路径在本轮受影响入口替换。跨模块契约与恢复决定记录 ADR。

反事实：移除原生响应投影时，同一真实阶段仍无 assistant／tool 配对；换 host/model、缺结果或破坏配对时在 HTTP 前明确拒绝；合法已结算交换恢复后原参数、消息及原回执保持且新增模型／执行为零。保留现状不能满足服务方要求；只提高 think 也不能补齐协议。全量改写工具 Schema 或开放 Shell 会扩大范围，本轮不采用。新增 envelope、run 内响应记录和一个直接消费的续接物化模块是本协议代价，不增加模型必填输出。

独立 builder check 已核对七个实际分支。落地契约据此固定为：Port 的 assistant envelope 绑定 host/model，携带外部完整 payload 及经校验的调用 ID；exchange 按原顺序携带 typed 结果文本。Journal 的决策记录绑定 turn、输入起点及原始响应；控制处置只补当前缺失的 call_id、接纳／延期、计划 id/revision 或提交准备事实。工具结果和拒绝仍从当前 canonical 输入按调用 ID、decision_turn 查找；整轮门禁的既有反馈作用于本轮尚未处理的调用，不把计划已接纳改为失败。不用下一记录的输入起点截断恢复后补回的结果。

具体写点为：模型响应与用量在任何执行或提前 continue/return 前一并提交；planning_safe 预取分支明确记录计划本轮延期，实际计划接纳点才写接纳；prepare_final 仅在当前实际相位切换点接纳，恢复从同一控制事实恢复相位。save/delete 提前返回从既有 operation/ref 表达准备或待确认，不表达业务已完成。Adapter 内部有界协议修复也必须带回首响应及配对拒绝，不能只补 Application 外层。

控制结果的语义说明沿 Prompt 注册表版本化，三个状态为已接纳、延期和已准备，不要求模型复述状态。动作、最终提交、研究 writer 及压缩的输入构造契约同步升版，Trace 记录实际 Prompt 版本及原生历史字符量；正文任务目标、Schema 和核验装配保持。

完整真实阶段回放另定位容量边界把 assistant 的 `audio=null` 当成音频输入，阻止原生完整消息续传。该字段只是 SDK 保留的空可选值；本轮保留原字段，仅在既有容量校验中把明确 null 与实际多模态内容区分，真实非 null 音频／图像／视频拒绝保持。以同一完整原请求先复现本地拒绝，再验证完整消息容量检查，不裁掉字段来绕过校验。

压缩增加已覆盖决策 turn 集合；既有覆盖键继续处理继承输入。一个调用集合中任一成员受保护或未结算，整个原生交换保留；容量缩减按完整组截断。导出原件及来源 digest 同时覆盖被淘汰的 assistant 原文和来源关系。该调整只落实 H4，不追加压缩收益主张或改自然压力门槛。不存在有效模型历史的旧封存只读保留，不生成猜补原文；当前无运行中的任务，新轨迹使用新契约，恢复校验覆盖新增字段。

完整激活回放准备时发现候选的导出序列化仍按旧 list 遍历；来源已改为含 inputs／model_decisions 的对象，直接遍历会只导出两个键名。该候选尚未准入正式运行。先用 MiMo 已封存首轮的完整 Journal 阶段、真实首批并行调用及 prepare_final 响应，在隔离 FileJournal／ArtifactService 消费历史真实摘要回执，验证原件可以完整还原来源、控制续接和恢复相等、受保护成员使整组保留。外部摘要回执仅用于激活协议回放，不声称它总结了新输入或自然压力成功；模型／工具新增均零。先保留导出失败，再将唯一原件改为完整对象 JSON，不新建格式或旁路。

独立最终审查确认另外三项候选缺陷，进入同一次有界修正：调用 ID 可在拒绝后被重用，反馈必须按 decision_turn 归属，执行结果按响应输入起点与未被拒绝的实际决策归属，不能让后轮 duplicate_action_id 拒绝改写旧成功；合法恢复后补结果仍可关联原未拒绝调用。SDK 完整响应含非法角色或调用 ID 时，必须先保留原完整回执与已知用量，再通过既有 typed failure 拒绝，禁止原生 envelope 校验覆盖费用。续接身份绑定实际请求端点与请求模型，服务方返回的 model 名称继续保存在原回执中，不拿别名解析结果拒绝原模型续接。使用同一完整真实阶段及明确外部反事实，先复现后三项再验证；不新增单元测试或付费模型。

### 实施与验证顺序

1. 保存改前源码、MiniMax 实际五次决策的完整请求／响应及相应 Journal 输入，固定原件 SHA-256。先以当前生产装配证明没有原生续接。独立 builder check 核对控制分支、恢复及压缩，再落地同一设计。
2. 接入 typed Port、SDK 完整响应保留、Journal 不可变响应绑定及 Conversation 物化；迁移受影响生产与有效评测消费者，同步架构、Context 正文及 ADR。保持当前 MiniMax adaptive＋low、原 Schema／输出额度／权限／停止线。
3. 零新增模型地消费上述完整真实阶段以及历史实际控制／并行调用轨迹，经正式物化与 SDK 边界检查：原响应保真、拒绝及成功配对、无重复正文、prepare_final 后 structured 消费、恢复不新增执行、身份错配拒绝和完整交换压缩。只验证实际覆盖边界，不建立逐函数单元测试替代套件。
4. 原完整失败阶段的保真、配对和容量检查通过后，以该相同边界做一次真实 MiniMax 续接，最多原有两次协议物理请求、500k 已知 tokens、15 分钟、原 480 秒单请求。本阶段仅调用 SDK，不执行模型新提议的工具；其没有前置控制动作，因此独立于控制／压缩回放，后两者及代码审查仍是正式 E2E 的前置条件。只改变历史投影；如需要前置实际决策，连续消费其真实输出，不注入期望的正确参数。任一未知、协议拒绝或预算停止保留失败，不补样或提高 think 求通过。该次只判 wire／响应及实际修复边界，不凭单例宣称参数可靠性提高；若要关闭参数语义缺口，另按 QLT 固定至少十次的组级计划。
5. 完成代码审查和相关静态／文档检查，再恢复原 E2E 的新身份准入。现有采集侧 role 字段异常单独修复并验证，不能绕过封存／消费门禁直接启动完整轨迹；保持 36 轮和 17→18 恢复目标，无核验流程仍标为 unverified_flow_capture、release_eligible=false。

**独立采集准入修正。** 已定位 `retrieval_capture_audit.ObservedProviderCompletion.choices` 直接复用 SDK 的 `Choice`，从而把计量审计不消费的 `message.role=assistant` 约束当作整份用量的准入条件。真实首轮的六份完整响应含一份 SDK 拼接的异常角色，但 usage 完整且与 Journal 同为 113,642；不能因为这个角色异常丢弃已知费用，也不能改写角色来制造合法 assistant。本轮仅由该只读外部响应 DTO 按实际消费者声明 message／choice 字段，role 原样保存为外部字符串，content 和 usage 保持 typed，剩余外部字段完整保留；生产 Adapter 的消息身份与配对校验不放宽。实现前保留旧 `_wire_groups` 的实际拒绝，之后分别对该完整失败段及旧 MiMo 成功两轮各审计一次：期望六次／113,642／未知零及二十八次／1,227,299／未知零，异常角色原文不变；新增模型、工具和评分均零。不回填旧失败段的正式 report/seal，仍保留原采集失败身份。该修正只恢复独立费用／封存消费者，不诊断 SDK 角色拼接来源，也不声称生产响应协议通过。

### 当前实现、证据与下一轨迹

实现已经覆盖 Model Port、SDK、Conversation Journal、原生历史物化及完整交换压缩。四项独立审查问题均保留先失败后通过的证据：压缩对象完整导出；重复 ID 的跨轮反馈隔离；非法消息保留费用与 typed failure；实际请求 host／模型别名绑定。[完整真实五阶段回放](../../.tmp/native-tool-history-20261023/offline-v5/report.json)为 5/5，[SDK 四例](../../.tmp/native-tool-history-20261023/sdk-protocol-v3/summary.json)为 4/4；[控制／压缩阶段](../../.tmp/native-tool-history-20261023/boundaries-v2/report.json)验证真实 prepare_final 解码及相位恢复、完整原件、覆盖退出、保护整组与新实例恢复；[审查反事实](../../.tmp/native-tool-history-20261023/review-green/report.json)为 5/5。以上新增付费模型与工具执行均为零。控制／压缩回放仅重建旧首批并行响应和 prepare_final 原响应；外部摘要复用历史回执验证确定性激活，不能声称其总结新输入正确，工作清单及 save/delete 分支仍仅经代码审查。

固定 low 的[一次真实失败阶段续接](../../.tmp/native-tool-history-20261023/actual-stage/report.json)返回合法 Python 提议，program_ref 为 null、版本为整数，15 份文件引用均可见。实际一次请求、36,568 tokens、未知零、18.359 秒；未执行新程序。它证明该完整输入的一次续接，不证明参数可靠性提升或完整长任务。独立采集计量回放对旧两段原件核对为 6／113,642／未知零与 28／1,227,299／未知零，异常 role 字节保持，原失败报告及封存不回填。

当前真实流程使用独立目录 `.tmp/minimax-native-history-e2e-20261023/`，从原第 1 轮自然请求进入，原 36 轮、17→18 新进程恢复、16 CSV、固定镜像、MiniMax adaptive＋low、direct＋none、60M／36 小时及每 run 10M／40／256／4 保持。原 113,642 tokens 失败、MiMo 历史未知和本次 36,568 阶段消费分别保留，不称原失败 run 恢复。只在局部、独立审查和静态／文档门禁通过后启动；同一失败再次出现即按原停止线封存，不提高 think 或自动追加整轮。观察器继续等待实际 PID 退出，只有完整、已封存且通过既有准入的 answer 进入独立官方评分，使用新的评分身份，原 Judge 2M 共享阈值及历史 26,050／未知零保留。仍为 unverified_flow_capture、release_eligible=false。

当前原生历史 target 于北京时间 2026-10-23 21:43:50 启动，约 21:51:58 已停止，21:52:43 完成独立评分。实际 3 轮请求、2 轮回答、33 轮未执行，11 次 Python 为 10 成功／1 失败，第 1 轮已有 9 次 program_ref 调用；第 3 轮先漏 program_ref，收到按原调用 ID 配对的原生 tool 拒绝后，第二次又漏 input_files，按既有连续无效动作线返回 limitation，所有拒绝调用未执行。当前原生协议缺口已覆盖，但参数生成／恢复尚未解决；单次局部成功没有扩大为可靠性结论。本轮没有新增候选、提高 think 或自动整轮重跑。

两份原始 answer 经独立官方标准评分均为 0。第 1 轮搜索国家数为 14／期望 15，电影时长缺失的统计口径也不符；第 2 轮前五市场及顺序正确，但需求缺口和机会分数不符。生成 27 次物理请求、2,035,196 tokens；新增 Judge 2 次、10,818 tokens，二者未知均零，Judge 共享历史累计为 36,868、未知零。最大实际单请求输入 149,368 tokens；无自然压缩、第 17 轮检查点或恢复，不把累计 2M 消费当作单窗口压力。采集、完成审计、评分及原局部档案 seal 均已核对；[最终报告](../../.tmp/minimax-native-history-e2e-20261023/complete-audit/report.json)是原始结果，旧运行中快照另存后[状态入口](../../.tmp/minimax-native-history-e2e-20261023/running-status.json)已改为停止。

## 2026-10-23 MiMo 工具流式接入规格

用户在诊断补齐后明确要求采用官方方法优化并继续 E2E。本轮修复的是普通工具调用仍等待非流式完整正文的传输覆盖缺口；依据为 LongDS 首轮第四次完整真实请求、HTTP 200 后约 361 秒读取异常，以及此前结构化请求已采用 SSE 的实际调用链。具体断连方仍未知，不将候选写成已证实的网络根因修复。

| 需求 | 行为与验收 |
| --- | --- |
| T1 | 已核对的 MiMo 官方 API／中国区 Token Plan 工具调用使用 SSE，并请求完整用量；保留模型、全部消息／工具、thinking、输出额度、超时及重试预算 |
| T2 | MiMo 工具请求的 wire `tool_choice` 使用接口支持的 `auto`；原 `StructuredModelRequest.action_choice=required` 保持，完整结果没有动作仍由现行解码及有界修复处理 |
| T3 | SDK 只合并完整工具增量，参数 JSON 与动作校验仍归现行 Adapter；部分参数不执行。真实非法 JSON 可到达原修复链，完整响应的实际 usage 保留 |
| T4 | SSE 读取失败沿原 `ModelInvocationUnavailable`、诊断、未知用量及停止链交接；不可把已经收到响应头或部分字节当作成功。原诊断请求隔离及重定向修复保持 |

架构分析：正式路径仍为 Conversation → governed/observed/usage/retry 模型 Port → `OpenAIModelClient`。provider 协议投影及完整 SDK 响应合并归同一 Adapter，动作要求归原请求与解码器，执行、Journal、预算及 Final 仍归现行 owner。仅在 `_chat_kwargs` 对已核对的 `api.xiaomimimo.com`、`token-plan-cn.xiaomimimo.com` 做协议适配，不新建 Port、Registry 或配置；其他服务方和普通文本调用保持。沿用 `_create_chat_completion` 的 deadline／capacity／客户端关闭及 SDK 流对象；SDK strict 工具自动解析会提前 `json.loads`，而真实 L1 已有非法工具 JSON，因此工具流复用其公开导出的 `ChatCompletionStream` 合并，`input_tools=[]` 仅关闭本地自动参数解析，实发工具 `strict` 与 Schema 保持。合并后归一为普通 `ChatCompletion`，移除 SDK 派生解析空字段，交回现行唯一参数校验和修复。SDK 原生结构化流路径保持。实际 HTTPX 传输异常也归入原模型不可用转换，不改重试次数。

2026-10-23 已实际打开 [MiMo Chat API](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)与[接入 FAQ](https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration)，确认流式、工具增量及 `auto` 协议；本地 `openai==2.36.0` 的 `ChatCompletionStream`、`parse_function_tool_arguments` 和原生 Stream 源码用于核对装配及异常边界。采用 SDK 已有合并机制，不自行拼接第二套工具结果。此处同时改变 SSE 与服务方本来按 auto 处理的字段投影，不主张两者各自的独立收益。

实施前固定局部回放三例，各一次，使用 LongDS 失败的完整阶段请求、同运行已有完整响应，以及 L1 实际非法 JSON 的完整阶段原件：正常 SSE 分段参数和完整 usage；非法 JSON 后原修复消费；SSE 中途断流。只替换外部 HTTP 为本机服务，原 wire 除 T1/T2 声明差异逐项相等；局部不执行工具、不付费、不代表 Product E2E。保留候选前源码及输入摘要，任一必要判据失败停止受影响路径，先定位，不能反复重跑整任务。

通过后按同一正式 LongDS 入口启动一条独立 36 轮 target，从第 1 轮进入，在第 17 轮真实完成后停止服务、沿同一新许可／消息／Journal 启动 18—36 轮。原失败运行没有检查点且消费未知，保持封存；本次明确继续授权用于新的验证身份，不清除原 Journal 或冒称原轨迹恢复。新运行仍为 MiMo Flash、direct+none、60M 停止阈值、36 小时许可、每轮 3600 秒、每 run 10M／40 主决策／256 工具／4 委派。任一非 answer、服务失败、未知消费或原预算终止即封存，不挑成功重跑；真实完成答案在生成停止后独立官方评分，不回灌模型。旧已知消费与一次未知在历史累计中单列，不能把新运行已知数当作所有尝试完整成本。

归档为 `.tmp/mimo-tool-stream-20261023/`。局部通过后才能启动新 target；原长任务方案及评分标准保持，流程仍不计带 Verification 的产品／发布通过。[研究 Spec](to_verify/knowledge-decision-delivery.md#910-切回-mimo-的长任务验证)、当前架构、评测记录及队列同步消费本规格。

独立评审确认 T3 的完整过滤响应计量缺口：同一完整历史阶段仅把外部 `finish_reason` 改为 `content_filter`，SDK 已完整收到 28,239 tokens，`get_final_completion()` 最终解析却抛出不带 completion 的异常，Adapter 无响应可交接。评审为两次本机 HTTP，付费／工具零，未启动 E2E。修正前源码保存在 `before-filter/`。追加第四例完整过滤响应，各一次：只发一次请求，零有效动作／工具、provider_rejected、不可重试，完整 usage 沿 Adapter → 原错误 Port → Conversation 保留；真实断流例继续未知，不能用已知过滤响应覆盖它。

实施决定：工具流使用 SDK `until_done()` 与 `current_completion_snapshot`，只合并，原生结构化流保持。完整 filtered completion 在动作解码前由 Adapter 拒绝，原 `.response` 保存同次真实完成响应与已知用量；错误 Port 增加 `provider_response_complete`，只表达已取得完整 ChatCompletion，不等于 usage 必填或语义成功。Conversation 沿同一 typed 字段交接；完整回执按原计量器读取实际 usage，缺字段仍未知，未取得完整回执时仍标未知。原错误对象和 Journal 各自保留事实归属，不另建状态或计量 owner。该字段默认 false，历史中断和旧未知状态不迁移、不清除；完整过滤继续停止、不重试，不进入动作修复或执行。先跑修正前第四例失败，再修正并完成四例后才可启动 target。

第四例已先失败、修正后四例 4/4。启动前追加一次正式 Web 入口的外部过滤故障回放：同一自然首轮、16 CSV、真实 Composition Root／模型 Port／Journal，只由本机 SSE 服务返回既有 intent 响应及完整过滤工具响应。固定一例一次，预算沿原 L1／480 秒／零服务重试；期望 Web 503、provider_rejected 不重试、无工具接受或执行，Journal 与 SDK 实际已知用量相等且不误加未知。它仅证明错误消费边界，是 Offline Eval，不能冒充真实模型 E2E；实际 MiMo 36 轮仍在此检查通过后另启动。

该 Web 故障回放已通过：两次本机模型 HTTP，Journal／SDK 均为 31,352 已知 tokens，未知零、工具零、HTTP 503，完整拒绝事实已到达实际消费点。另观察到正常 SSE 在 `[DONE]` 后关闭生成器时，HTTPcore trace 会用 `GeneratorExit` 触发 `.failed`，旧诊断把正常关闭记成网络失败。它不影响 SDK 或消费，但会误导故障定位。本轮保留原始日志，固定修正为忽略该生成器关闭事件的传输失败投影；真实 `RemoteProtocolError` 仍记录。原四例追加“正常关闭无 GeneratorExit 失败事件”的断言，先失败再修正；不改变流、关闭和异常行为，不另跑整任务。

最终 `offline-v3` 四例 4/4，包括过滤消费及正常关闭诊断；两项评审／诊断问题均保留先失败后通过的证据，未再扩展协议重试。静态依赖、导入、规范及本机执行镜像核对通过。正式 Web 过滤回放的原计量消费者、错误契约和源码保持，后续只改了可选 HTTP 观测的 GeneratorExit 投影；该回放保持原版本身份复用，不能重标为新版本真实模型 E2E。实际 MiMo target 已在首轮收到完整 `content_filter` 后按原停止线封存；已知消费到达 Journal，没有此前断流异常，具体过滤原因未知，不主张断流根因已解决。完成观察器另暴露失败段评分准入缺口，需先按实际错误响应修正评测控制，再考虑后续验证；本轮未追加重跑。真实结果及成本由[评测登记](../evals/02-current-case-inventory.md#2026-10-23-mimo-工具流式接入后的完整流程验证)拥有。

### 内容过滤的定位与既有反馈

本次不是首次出现或首次有人报告内容过滤。仓库 10 月 16 日的[原始报告](../../.tmp/research-unified-production-e2e-20261016/REPORT.json)已记录 `ContentFilterFinishReasonError`，原日志第 224—225 行保留异常；提交 `a67364c` 已将它归入 `provider_rejected`。此前汇报只说明本次停止，没有关联既有记录与公开反馈，信息不完整。旧错误映射解决的是失败交接，不代表供应商过滤已经消失。

2026-10-23 核对的外部依据分为官方契约和使用者报告，不能混作服务方根因确认：

| 来源 | 已报告的现象及适用差异 |
| --- | --- |
| [MiMo 官方 Chat API](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)、[错误码](https://mimo.mi.com/docs/zh-CN/api/guidance/error-codes) | SSE 和非流式均允许 `content_filter` 终止；错误码另列 421 内容审核。文档没有解释本次触发项，本次供应商 HTTP 为 200，公开 Web 503 是本工程错误映射 |
| [MiMo #45](https://github.com/XiaomiMiMo/MiMo/issues/45)，2026-05-22 | 使用者报告 MiMo 2.5 图像推理返回相同 high risk 拒绝，部分相同请求后来成功；这是该使用者的记录，不能外推本工程发生率或本次必属误拦截 |
| [MiMo #76](https://github.com/XiaomiMiMo/MiMo/issues/76)，2026-07-05 | 使用者在同一 Token Plan CN 端点报告 system 合规文字触发零用量拒绝，模型为 2.5 Pro。“按关键词匹配”是报告者分析，未见服务方确认；本次 2.6 Flash 已产生推理，用量并非零，不能直接套用该归因 |
| [AstrBot #8644](https://github.com/AstrBotDevs/AstrBot/issues/8644)，2026-06-07 | MiMo 2.5 的 Anthropic 兼容过滤响应缺少 usage，导致消费者崩溃；该消费错误由 PR #8647 关闭。这证明其他客户端也遇到过滤及后续错误，不能解释本次 OpenAI 兼容响应的触发项 |

本次完整 SDK 回执的拒绝正文为 `The request was rejected because it was considered high risk`。实际输入 25,343 tokens、输出 6,162 tokens，其中推理 6,161 tokens；调用耗时 169.907 秒，随后 `content_filter` 终止。已核对本机 `openai==2.36.0`：`ChatCompletionStream` 将增量中的 `finish_reason` 直接赋给快照，采集器在 Adapter 动作解码前保存该快照，没有本地生成该终止码。由此定位到服务方完整内容过滤回执，未观测到本次断流、超时、容量拒绝、`length` 或参数解码失败。归档没有保存原始 SSE 帧，只保存完整 SDK 响应及字节计数；不能声称已有原始帧复核。

失败前后两次主决策的实际 wire 对照表明：19 项工具及其他服务方参数完全相同，用户消息相同，首条 system 仅实际剩余额度变化；执行输入由 16 项附件元数据增加为 18 项，新增的是成功读取 Netflix 目录第 1—30 行、澳大利亚搜索热度第 1—25 行。目录片名和简介包含犯罪、暴力等影视描述，生成内容也讨论评级与市场名称；这些只能列为候选输入因素，不能凭词语出现或推理末句判定过滤触发项。三条消息仍为 system／user／system，没有缺失原生 assistant/tool 历史的 400 错误证据。

此前 MiMo 两轮流程的 28 份完整 SDK 响应均未出现过滤，同一自然首问已实际成功；它与本次的物理请求、动态材料、生成内容和流式配置不同，不能当作同请求消融或随机误拦截证明。原先断流的完整任务没有终止回执，是否涉及过滤仍未知。当前只能确认“产生推理后被过滤”，尚不能区分输入异步审核、输出审核或误拦截；需要服务方按响应 ID 解释审核结果，单纯重跑不能给出确定归因。

停止后审计另修正工具计数口径：`accepted_tool_requests` 为空只表明该持久请求集合为空，不代表全部工具未执行。本次 Journal 的执行顺序和实际输入记录了两次成功 `read_artifact`，Python 执行零。此前状态文档中的“工具执行零”已修正，原始封存保持。此次只读定位新增付费模型／Agent 工具执行均为零，原件校验及源码坐标见[诊断归档](../../.tmp/mimo-content-filter-20261023/report.json)，未取得完整长任务成绩。

## 2026-10-23 LongDS 工具调用断连与诊断覆盖

本轮完整任务已在首轮第 4 次 MiMo 请求停止：HTTP 200 后正文未完整交付，HTTP 观察器记录 `RemoteProtocolError`、361.421 秒；没有 Final 或完整用量。原结果和停止事实见[评测登记](../evals/02-current-case-inventory.md#2026-10-23-mimo-两轮流程及独立评分)，此前两轮通过保持。当前可区分两层结论：诊断丢失位置已由源码定位；导致此次断连的具体环节尚未确定。

原 [HTTP 错误体诊断](to_verify/model-provider-diagnostics.md#2026-10-23-传输异常诊断缺口)没有覆盖底层读取异常链；原正式观察器也没有保存响应字节和首末包时间。本轮已补齐请求内观测，并完成完整真实 SDK 阶段的本机 HTTP 反事实；结果由诊断记录拥有。原失败缺失的消息、响应头及中途进度仍无法从归档恢复，不能只按异常类型判断是服务端、代理还是本机网络。HTTP 503 是应用对模型不可用的转换，不是 MiMo 返回了 503；HTTP 200 也不代表完整模型结果已经到达。

此前 10 月 15 日的流式修复没有覆盖本次入口：当前 `_create_structured_completion` 对结构化回答设置 `stream=True` 和用量返回，普通 `_generate_chat` 直接调用 `_chat_kwargs`，工具调用未设置流式。本次实发载荷确认含 19 个工具、`tool_choice=required`、thinking enabled、32,768 输出额度，且没有 `stream`。它仍在等待整个非流式正文，因此原结构化 SSE 的交付证据不能外推到工具调用。源码见[同一个模型 Adapter](../../src/personal_agent/infra/structured_model.py)，不是另有模型循环。

10 月 13 日的同类失败为 361.69 秒，与本次时间接近，值得优先核对约 360 秒的链路截止；它只是待证假设，不能替代网关、代理或服务端日志。当前只读检查仍发现 HTTP／HTTPS 系统代理指向本机 7892、目标域名不绕过代理；本次失败没有保存实际 socket 路由，所以当前配置不能追认故障时的连接路径，也不能证明代理就是原因。本例异常类别也不支持直接认定为本地 480 秒总时限触发。

2026-10-23 已实际打开 [MiMo API 接入说明](https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration)和当前[中文 Chat API](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)。`stream` 默认为 false，官方建议长响应使用流式；协议支持流式工具参数增量。这些依据不证明改为 SSE 必然消除断连；10 月 16 日的 SSE 中断仍保留为反例。

官方还明确：非 `auto` 的 `tool_choice` 会被后端移除，行为按 `auto`；本次发送 `required` 只能证明客户端意图，不能证明服务方强制选择工具。`strict` 只支持 JSON Schema 子集，文档仍要求调用方验证生成参数；这不能替代本工程对具体参数错误的输入审计。本次失败尚无完整模型响应，上述差异不是已证实断流原因，本轮未改工具选择或 Schema。多轮思考工具调用建议保留历史 `reasoning_content`，但原失败请求只有 system/user/system 三条消息，没有原生 assistant/tool 历史，不能直接按缺少该字段归因；当前以完整 Context 重新提交执行事实的设计另按语义证据评价。

本轮按原有[字节观察机制](../../.tmp/provider-body-diagnosis-20261010/run.py)采用官方 hook、透明流包装和原因链，将最小计数／白名单投影接入原 Adapter；未保留第二套原始正文存储。回放也实际捕获到系统代理承接本机请求，说明目标 host 与连接对端必须分别观察；它不能追认原 MiMo 故障时的路由。下一次有界隔离观察须另固定调用／费用和停止线，以同一真实失败请求取得新的非流式进度，再决定是否需要单变量流式对照。原一次未知消费保持；本轮新增付费模型／工具执行为零，未恢复完整 36 轮，也未准入生产传输策略修补。

## 2026-10-16 正式写作被供应商过滤中断

统一研究正式 E2E 运行 4,174.80 秒后为 0/1。四份来源报告均完整，最新第 4 版仍有三项实际反馈；下一 writer 调用由 SDK 抛出 `ContentFilterFinishReasonError`，未形成提议或 usage。已知新增 1,121,470 tokens，一次未知；不能把它记为核验分类失败、网络断流或已成功完成。供应商过滤的具体原因未知。

Adapter 现将该 SDK 异常映射到既有 `provider_rejected`，保留 `content_filter` 诊断，`retryable=False`；不自动绕过拒绝或修改材料。另修复进程恢复时丢弃当前适用研究反馈的边界；真实状态审计证明原第 4 版及三项反馈仍与完整输入相等。按[统一 Spec](to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)只恢复同一任务一次，原目标、模型、thinking、Prompt、Schema 和累计预算保持，新增透明 SSE 字节观察。原 0/1 保留，恢复结果独立记录于 `.tmp/research-unified-resume-20261016/`，不以部分流或已修工程边界代替用户交付。

该次恢复未再次观测到供应商过滤，第 6 版核验返回空报告后因 FinalMessage 缺必填字段而为 0/1；字段修复后的正式续验 1/1、独立评分通过，结果见[评测登记](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。供应商首次过滤的具体原因仍未知，不因后续成功追认为网络原因。评分期间隔离观测器误挡一次发送前修复请求，已用真实请求零网络反事实定位并修正后续 hook 复用；原运行身份、两次实际评分成本及失败响应保留，不计为供应商拒绝或未知用量。

## 2026-10-16 G2 执行记录修正回放断流

同一研究 writer 已消费真实 a6 反馈并在 v35 核验通过，局部闭环 1/1。随后仅补回 G2 实际零命中执行记录的 v36 回放，原生 SSE 在消息体完成前报 `httpx.RemoteProtocolError`／`incomplete chunked read`，没有完整报告和 usage；本次一物理、一次新增未知，不计模型语义失败。具体输入及当前方案由[统一核验 Spec](to_verify/research-goal-coverage.md#716-执行记录修正的断流与一次恢复)拥有。

沿用本页已核对的原生 SSE、透明字节观察和一次同请求恢复边界，恢复仅接纳第一份完整报告，不修改语义、端点、模型、thinking、32,768 输出或 1,200 秒 deadline；零 SDK／服务／结构重试，一物理、90,000 新已知 tokens、16 MiB 字节观察上限。恢复再失败即停止，不作网络根因猜测或生产传输修补。旧 C1 通过和 G2 的输入保真审计保持，断流具体根因及此次用量未知。

恢复实际在 392.02 秒收到模型 `length` 终止，报告正文仍为零，SDK 以 `LengthFinishReasonError` 结束；不是本地 deadline 或再次观测到远端断流。原始 SSE 已包含实际 usage，86,169 tokens 可核计，恢复不新增未知；最初断流仍保留一次未知。当前累计 25,824,853 已知／四十二次未知。语义报告未形成，按一次恢复边界停止，不追加时限、额度或模型调用；具体证据与部分记录边界见[恢复结果](to_verify/research-goal-coverage.md#717-恢复的输出额度结果与本轮停止)。

## 2026-10-15 整稿 Source 时限复审

首次 480.09 秒超时及原定一次同请求恢复均未取得报告，新增两次未知。恢复确认 HTTP 200、wire body 与冻结 kwargs 一致，首字节 5.07 秒，末次增量 479.96 秒，1,531,686 响应字节；已返回 54,802 个推理字符、零报告正文，随后被 `_run_with_deadline` 本地总时限关闭。没有 429、鉴权错误或空闲等待证据；不能追认首次超时同因，也不能用部分推理计语义判决或推算 tokens。

本日复核 [LangGraph TimeoutPolicy 官方文档](https://reference.langchain.com/python/langgraph/types/TimeoutPolicy)的 `run_timeout`／`idle_timeout` 机制；文档抓取受内容类型限制，机制由 [2026-06-04 官方工程文章](https://www.langchain.com/blog/fault-tolerance-in-langgraph)复核，按 B 级使用。总时限限制单次尝试，进度时限区分持续流输出与无进展；本工程已具硬截止及原生 SSE，无需引入框架或新超时配置轴。MiMo [深度思考说明](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/other/deep-thinking)的检索摘要确认当前模型支持 thinking 开关，但正文抓取为空，不据此增设未经核实的推理预算参数。

旧恢复只等相同 480 秒，未区分整稿任务超过旧单条期限与永不收敛。新实际证据准入一次总时限诊断：只把隔离客户端截止改为 1,200 秒，原生 JSON、业务 Prompt、Schema、模型、thinking、完整真实状态均保持；保留透明字节观察器。单物理、80,000 新已知 tokens、1,300 秒窗口、16 MiB，零 SDK／服务／结构重试，生产 `.env` 与代码保持。归档 `.tmp/research-source-goal-unification-20261015/deadline-probe/`；若完整报告到达，沿原 G1 判据计首份结果，不通过或仍无报告时停止新增同向调用并复审。此诊断不预设空 findings 正确，不承诺延长会解决语义漏放，原失败与累计未知不重置。

时限诊断实际在 157.64 秒完整返回，40,944 tokens、`stop`、零结构修复；原生 body 与首次冻结请求相等。完成时间低于原 480 秒，不能证明生产需延长时限，生产超时保持。typed 空 findings 对 G1 仍漏放，语义为 0/1；服务报告返回与语义结果分别计分，后续两者的处理由[统一研究 Spec](to_verify/research-goal-coverage.md#9-2026-10-15-旧整稿候选的报告与停止)拥有。原两次未知不追认成本或同因。

## 2026-10-15 整稿 Source 首次超时与同请求恢复

统一研究核验候选的 G1 在 `480.09` 秒触发现有 `ModelCallDeadlineExceeded`，一物理请求，没有完整报告或可用用量，新增一次未知。原生请求的三条消息、单一 Schema 外壳、模型及 thinking 已预检，目标、完整七条 claims 与真实材料保持；不能计为分类失败，也不能确认超时由候选输入或服务负载造成。原失败位于 `.tmp/research-source-goal-unification-20261015/G1-failure.json`，生产仍未改变。

沿用此前同类恢复的保留边界，仅准入一次同请求恢复，距失败至少六十秒，原生 kwargs 逐字一致。继续通过同一生产 Model Port、SDK SSE 汇总及 canonical 报告校验，复用已有只读 HTTP 字节观察器记录请求协议、状态、首字节、完整响应体及错误；原文、类别和参数不改。官方 [OpenAI SSE 契约](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)与本机 SDK 2.36.0 的 `ChatCompletionStream` 已核对；它们不证明 MiMo 本次服务已正常，也不把部分内容接纳为判决。

恢复归档 `recovery/`，每例仍只接纳第一份完整语义结果。恢复及原失败累计计入原六物理、160,000 新已知 tokens 和 1,800 秒，单次仍为 480 秒、SDK／服务隐式重试零；观察体积上限 16 MiB。G1 恢复仍无完整结果时停止新增模型调用，保留隔离候选及原任务；若完整返回，按原 G1 判据判断，合格才执行 G2。此恢复不重置此前尝试、费用或任何语义失败。

## 2026-10-15 完整报告返回与限流边界

原任务 SSE 续跑已取得第八条完整来源报告及后续真实反馈，随后选证服务失败，正式用户结果仍为 0/1。来源请求正文与此前中断请求除流式参数外相同；推理、终止与用量均保留。它证明本次 Source 的完整交付恢复，不证明所有服务错误已解除，见[原生请求对照](../../.tmp/research-structured-sse-resume-target-20261015/c8-wire-counterfactual.json)和[正式失败审计](../../.tmp/research-structured-sse-resume-target-20261015/formal-result-audit.json)。

后续 Coverage 回放在 SSE 中明确返回 `429 / rate_limit_error / Request rate limited`，7.28 秒、无用量。等待至少 60 秒后的一次同请求恢复完整返回，245.44 秒、27,090 tokens；其语义仍失败，与传输恢复分别计分。MiMo [官方错误说明](https://mimo.mi.com/docs/zh-CN/api/guidance/error-codes)将 429 归为频率或 Token Plan 额度超限，本次没有 `Retry-After` 或更具体额度信息，不能断言是某一种限制。现有调用参数已核对，未改端点、账号、额度或重试策略，历史未知错误不追认同因。结果由[本轮密封](../../.tmp/research-goal-verification-consolidation-20261015/REPORT.json)拥有。

## 2026-10-15 原任务恢复后的结构化传输修复预声明

澄清后的原正式运行 0/1；恢复原 Journal 的正式样本仍为 **0/1**，但原会话、消息、资料和累计预算均已验证保真。前七条来源通过，第八条三次相同非流式请求均在完整响应体交付前报 `APIConnectionError → RemoteProtocolError`，未获得语义判决或用量。恢复新增 417,793 已知 tokens、三次未知、2,127.38 秒，累计 24,494,206／未知三十三次；同一任务已提交 2,766,549 tokens／64 轮及 96 工具额度中的实际进度由真实快照拥有。当前入口 HTTP 503 已被评测如实封存，结果记录修复成立；不把传输失败定为分类失败。见[恢复正式密封](../../.tmp/research-scenario-contract-resume-target-20261015/REPORT.json)。

实际请求为 JSON Object、thinking 开启，未显式设置输出 token 上限，默认未开启 SSE。生产已有流式分支仅在发现异常 SSE 内容后启用，因此完整非流式响应体中断不会自动走到它；旧 collector 又只保留正文、模型与 usage，不能直接作为完整推理和终止记录。重复失败已按本页 MiMo 官方长响应建议复审，并核对 [OpenAI 官方流式协议](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)与本地 SDK：流式协议按增量交付，usage 可能在末块返回，断流缺失用量仍为未知。外部文档只解释机制，不证明本次断流的唯一根因。

最小修复为结构化完成统一请求 SSE，经现有 SDK 流式聚合恢复完整 ChatCompletion；保留正文、推理、终止原因及实际 usage，再交给既有 typed 解析与恢复。普通工具调用入口保持原协议。删除被替代的自动切换状态、旧 collector 与重试式探测分支，不增加业务字段、分类、模型阶段、依赖或配置开关。Prompt、Schema、模型、thinking、默认输出额度、480 秒单次时限、已有有界服务与结构恢复均保持。SDK 聚合须保留兼容端点的推理扩展；正式记录同时观察原生流增量，部分内容不作为完整报告或通过证据。

实现后执行一次既有恢复正式用例，初始条件为上次正式失败的完整真实 checkpoint，归档 `.tmp/research-structured-sse-resume-target-20261015/`。原用户中文消息、同一运行、owner、会话、材料与累计任务额度均保持；不从空资料重做，不注入测试报告或理想答案。4,000,000 tokens／64 轮／96 工具不重置，剩余已提交任务 tokens 为 1,233,451；HTTP 等待 7,200 秒，独立评分另预留 200,000，依据为前两次真实成本及恢复阶段约四十二万新增 tokens。SDK 与模型输出的正常差异不作确定性语义消融，只验证本任务的完整交付及实际结构化传输。

验收分别计分：实际请求正文除流式参数外与原完整阶段输入相符；完整结果进入 canonical typed 校验，推理、终止和用量如实保存；原用户交付继续按既定契约接受独立评分。达到既定条件即认可，不加稳定性重跑。若传输仍失败或 SDK 丢失必要输出，则停止同向修正并撤回本次传输变更，保留旧 Source、真实快照与失败；独立的后续语义反馈不否定已成立的交付机制。旧两项正式 0/1 保留，新恢复单独报告，不外推所有端点或发布资格。

## 2026-10-15 C7 修订后的完整请求流式观察

移除自动反馈复核后，P1 的真实选证、修订及后置 Source 已通过；C7 的选证与第十二版修订完成，但后置 Source 在 437.31 秒后发生 `APIConnectionError → RemoteProtocolError`，没有语义答案和用量。原组按首个服务失败封存，不重做已完成阶段，原一次未知保留。流式续接一次完整返回并通过同一稿的 Source，41,708 新已知 tokens、149.04 秒、新增未知零，累计 16,539,327、未知二十一次。见[续接密封](../../.tmp/source-direct-feedback-c7-stream-20261015/REPORT.json)。生产默认传输未改，历史间歇中断根因仍未知。

重复传输失败先复审调用机制：生产 structured 请求默认非流式；已有 SSE 收集路径仅在发现异常流式响应时启用，完整响应读取中断不会触发它。因此本次不能用连接预检或反复普通重试代替诊断。MiMo [结构化输出说明](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/text-generation/structured-output)明确支持 `stream=True` 并要求完整拼接 JSON 后解析，[超时说明](https://mimo.mi.com/docs/zh-CN/quick-start/faq/api-integration)建议长响应使用流式模式。参考 [LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming)的过程观察机制，保留已完成结果并区分增量与最终结果；不引入框架、自动复核或新业务字段。

执行前声明仅一次隔离观察，归档 `.tmp/source-direct-feedback-c7-stream-20261015/`。复制原 C7 第三次 SDK 请求，只增加 `stream=True`；模型、thinking、完整业务输入、Schema、输出额度和 480 秒 deadline 不变，不增加 SDK、服务或结构重试。最多一物理请求、80,000 已知 tokens、600 秒墙钟和 16 MiB 响应体；任一服务、协议、结构或预算失败即停止。未取得 usage 时计未知，不由文本长度猜成本。

实际 wire 只有流式开关变化；2.91 秒收到首个响应字节、2.96 秒收到推理增量、147.80 秒收到正文，最终得到 `stop`、`[DONE]`、usage 与空 findings。观察脚本把不入模型序列化的内部片段坐标当作可直接恢复字段，完成响应后发生只读归档校验错误；从原 canonical 稿和完整 inputs 恢复坐标后，确认完整 SourceInput 与原 SDK kwargs 相等，同一真实报告通过生产 generator 的引用绑定校验，无新模型调用。SDK 在 `[DONE]` 退出，不以 HTTP 迭代器是否读至 EOF 判定 JSON 完整。

结果只证明“流式传输下的真实阶段续接”成功，不改写原普通请求失败，不证明生产默认传输已修复，也不是 Product E2E。实际报告继续用于既定完整研究验收，保留原选证、修订和成本；没有整轮重跑、改变 Prompt 或新增复核。

## 2026-10-15 c2 新稿核验达到时限

完整研究先取得 c2 有据反馈，真实 selector 与 writer 已将未指明 API 主体改为 API 会尝试获取列表，并绑定 `d6:347`。后置 Source 沿默认非流式路径达到 480 秒，没有完整结果与用量；原组封存，已完成两个步骤共 58,976 新已知 tokens、新增未知一次，累计 16,692,356／未知二十二次。不能把调用未完成定义为核验器分类失败，原真实修订也不重做。

同类问题复审沿用本轮已核实的 MiMo 官方流式 JSON 与 LangGraph 过程观察机制。C7 的 SSE 完成不证明所有长请求已修复；当前待区分的是响应传输不完整与模型本身迟迟未结束。生产现有 SSE collector 不保存完整终止原因与推理增量，不能仅翻转默认开关就声称已具备本次诊断能力，也不因历史调用中断而改语义 Prompt。

预声明隔离诊断 `.tmp/source-direct-feedback-c2-stream-20261015/` 仅复制原 c2 第三次 SDK 请求、加 `stream=True`，保留同一原始输入、模型、thinking、Schema、额度和 480 秒；一物理、80,000 已知 tokens、600 秒、16 MiB，零 SDK／服务／结构重试。持续保存原生增量、到达时间、终止原因及 usage；达到时限时保留部分结果，但不接纳不完整报告。完整 `stop`／`[DONE]`、typed 解析及 canonical 引用绑定通过才单列真实阶段续接；失败则停止受影响验收，不追加相同恢复。

一次实际续接成功：1.08 秒首字节、1.15 秒推理增量，68.08 秒结束，完整空报告通过生产 Source generator；41,569 新已知 tokens、未知零，累计 16,733,925／未知二十二次，见[续接密封](../../.tmp/source-direct-feedback-c2-stream-20261015/REPORT.json)。本次有 4,697 推理 tokens，不能由它还原原超时请求的生成过程或认定唯一历史根因。保留原普通请求失败、生产传输与目标预算，同轨迹真实报告继续用于剩余研究，没有重做选证、writer 或已通过核验。

2026-10-13 真实 c6 修订后的引用核验发生响应体中断，约 361.69 秒后报 `RemoteProtocolError: incomplete chunked read`，并由既有边界转为 `provider_transport`；这是传输失败，未取得语义答案或响应用量。原 selector、writer、canonical 第九版编辑及范围判断都已实际完成并封存，新增一次未知，见[阶段密封报告](../../.tmp/source-c6-feedback-consumption-20261013/REPORT.json)。原组按服务首错停止，没有改 Prompt、模型、代理或重试。仅恢复原未完成引用请求后，SDK kwargs 逐字相等，取得完整真实报告；原已完成阶段没有重做。该恢复两次实际调用、23,265 tokens、186.30 秒，新增未知零，见[同请求恢复密封](../../.tmp/source-c6-transport-continuation-20261013/REPORT.json)。其后正确发现 schema 指代前提缺证，属于语义反馈，不是传输恢复失败。此前复核 LangGraph 官方恢复机制，只采用保留已完成结果这一边界；未新增框架或重试。旧间歇传输根因仍未知，不把未返回记为核验失败。

2026-10-12 P1 输入与恢复四格诊断的首个完整普通请求收到 HTTP 429，1.20 秒结束，正文及用量均未取得，剩余三格按预声明停止。随后独立的一次服务观察沿完全相同请求正常返回，60.36 秒、37,149 tokens、零 SDK／服务／结构重试，新增未知零。生产既有脱敏诊断未因本次正常返回触发，不证明旧 429 具体原因。见[密封服务观察](../../.tmp/provider-p1-429-diagnosis-20261012/REPORT.json)；当前服务可用，未切换端点、购买额度或改配置，先前四格原失败保持。MiMo [官方错误说明](https://mimo.mi.com/docs/zh-CN/api/guidance/error-codes)将 429 列为频率或 Token Plan 额度超限；现有错误体缺失，不能确定属于其中哪种。恢复得到的完整真实输出只按[原四格诊断](completed/source-proof-boundary-isolation.md#失败尝试与取舍)消费，不追加服务重试。

`MODEL-PROVIDER-TRANSPORT-001` 拥有服务调用返回前的传输与 deadline 阻塞；语义候选由各自设计拥有。2026-10-11 恢复 Docker 后的正式 Source 复核两次达到 480 秒时限，最后一次既有恢复取得完整报告并继续原链；三份完整请求逐字相同，条件流式诊断未触发，见[正式复核超时](#2026-10-11-正式-source-复核超时的条件诊断)。2026-10-10 的完整追问曾在 41.57 秒正常返回并捕获约五秒一次的换行保活；两轮恢复均未定位间歇故障根因。无响应不计语义接受或拒绝。

## 失败事实与责任边界

2026-10-08 首轮实际请求前三项返回有效报告，第 4 项同义部分列举完整输入经现有两次重试仍无结果。三次 SDK 请求分别为一次 `provider_transport`、两次 480 秒 `ModelCallDeadlineExceeded`，总耗时 1,259.88 秒，用量未知。实际请求与候选源码在[首轮归档](../../.tmp/current-draft-verifier-20261008/plan.json)封存；错误转换未保存底层连接异常原因，所以不能追认某个具体网络根因。原 SDK 的重试关闭，重试由生产 typed-operation wrapper 唯一拥有。

## 恢复机制与验证预声明

用户要求优先解除独立阻塞并继续原方案。新结果封存于 `.tmp/current-draft-verifier-resume-20261008/`，先读取当前配置身份、SDK 和代理配置的非敏感信息，进行 DNS 和最多一次短时只读模型列表连接预检；该预检不计付费语义样本，也不能替代原边界。再复用原第 4 项业务输入、Schema、模型、thinking、480 秒 deadline 和重试策略发出真实核验，保留实际 SDK 请求、响应、异常类型链、耗时和已知用量。

连接和原边界均恢复时，记录为当前服务恢复，具体历史根因仍保持未知，然后继续原候选。原边界再次失败时，先封存、审查最早连接或响应边界，再选择有依据的传输修复；不能靠扩大重试、关闭 thinking、缩短真实依据或替换中间结果规避。必要生产修复须另具失败证据、最小机制和回放判据；恢复与语义验收分别计分。底层异常记录只保留类型、状态与有界非敏感诊断，密钥和代理凭据不入归档。

原候选的责任主体、三个模块差异、用户结果、局部判据和连续依赖保持。已知成本累计复核线由原候选拥有；本问题只解决服务调用可返回的前置边界，不声明最终核验可靠性或用户交付完成。

## 实际恢复结果

只读模型列表首次请求返回，包含当前配置模型；DNS 可解析，无环境变量代理。原失败业务消息、Schema、版本、输出预算与温度字段逐项相同，首次 SDK 请求在 72.56 秒返回合法语义报告，无重试，24,200 tokens。随后四项请求全部返回；新增五个逻辑操作均只有一次 SDK 请求，共 123,824 tokens、346.08 秒。证据见[连接预检](../../.tmp/current-draft-verifier-resume-20261008/transport-preflight.json)、[原边界响应](../../.tmp/current-draft-verifier-resume-20261008/calibrate-call-1-response.json)及[输入与成本审计](../../.tmp/current-draft-verifier-resume-20261008/input-and-cost-audit.json)。

上述结果证明原失败请求在续验时可正常返回，原方案据此继续；没有生产传输修补或配置变更。历史三个无响应请求的具体网络根因和用量仍未知，不能据此宣称永久消除服务超时。校准结果及候选准入由[原问题记录](claim-revision-nonconvergence.md#独立阻塞恢复与原方案续验)拥有。

## 正式轨迹中的复现与路径排查

原正式 E2E 于 2026-10-08 12:49 启动。13:23:31 的取证动作请求收到 HTTP 200 后没有形成完整 SDK 响应，约 302 秒后转换为 `provider_transport`；现有第一次重试正常返回，实际读取缺失原文后继续修订。失败请求没有返回用量，底层异常链仍未记录，不能用 HTTP 200 认定业务响应完成，也不能确定是网关断连、代理或推理耗时。该阶段尚未调用本候选修改的最终 Verifier，传输复现不是当前稿判断的语义反例。实际请求、重试响应及运行日志分别保存在[正式请求归档](../../.tmp/current-draft-verifier-resume-20261008/product-model-calls/)和[辅助日志快照](../../.tmp/current-draft-verifier-resume-20261008/product-runtime-log-snapshot.log)；辅助快照不替代正式 Trace。

进一步读取已安装 HTTPX 源码，确认 Windows 下 `urllib.request.getproxies()` 会读取系统代理。无代理环境变量不等于没有实际代理：当前 HTTPS 系统代理为本机 `127.0.0.1:7892`，生产进程的连接也指向该端口。随后按预声明分别经现有代理和仅在诊断客户端关闭 `trust_env`，各做一次 20 秒以内、零重试的模型列表查询，两条路径均返回且包含当前模型，耗时分别为 0.46 秒与 0.12 秒。该只读结果排除当时完全无法连通，不能证明长响应断连由代理导致；没有改变系统代理、生产客户端或运行中的样本。证据见[连接路径排查](../../.tmp/current-draft-verifier-resume-20261008/network-path-probe.json)。

同一正式轨迹在 13:40:47 的来源请求收到 HTTP 200 后仍未完成，达到 480 秒 deadline；现有第一次重试在 72.99 秒返回合法报告。两次未完成尝试均没有响应用量。全轨迹 62 次 SDK 尝试、60 份完成响应，已知生产用量 1,697,702 tokens；两次未知用量不按零计。最终达到 32 个决策回合，原用户结果 **0/1**，在研究修订阶段结束，最终 Verifier 未到达。正式结果与计量由[本轮审计](../../.tmp/current-draft-verifier-resume-20261008/product-audit.json)拥有。

服务重试后可继续返回，故障根因仍保持未知；本轮终端阻塞由[正文与新增引用修订](completed/claim-atomic-evidence-revision.md)独立处理。后续真实调用启用独立只读异常观察器，捕获同一失败请求的有界异常类型链及响应边界，再依据证据选择传输修复。局部恢复、间歇故障和最终用户结果分别报告；没有改生产代理、deadline、重试或模型配置。

## 2026-10-10 实际调用与响应字节诊断

用户要求持续定位超时并确认调用本身正确。本轮先复审[最近追问失败](../../.tmp/source-triad-context-resume-20261010/question-error.json)：完整请求已封存，HTTP 200 在 9.3 秒到达，480.1 秒时整体 deadline 关闭客户端，没有答案及用量。现有观察未保存正文增量；接收失败发生于取消时，不能据此证明取消前网络已断。此前相同模型及非消息参数的中性追问可在 77.1 秒返回，最新 Source 可在 126.6 秒返回，这些事实排除持续完全不可用，不定位间歇故障根因。

已核对当前配置及[MiMo 兼容接口](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)、[Token Plan 中国入口](https://mimo.mi.com/docs/zh-CN/tokenplan/Token%20Plan/quick-access)（2026-10-10 读取）。模型、`/v1/chat/completions`、两条 system／user 文本消息、Bearer 鉴权及 `thinking.type=enabled` 均有协议依据。`max_completion_tokens` 省略合法，官方当前默认上限包含推理及正文；较高默认只提示需观察生成，不能直接认定此次长等待由推理造成。当前系统代理仍指向本机 7892，既有短请求连通证据不能替代长响应诊断。

隔离目录为 `.tmp/provider-body-diagnosis-20261010/`。先逐字复用上轮 `question-request.json`，由同一生产 `OpenAIModelClient._create_chat_completion` 调用相同模型与客户端配置。唯一变化是 HTTPX 响应流的只读观察：逐块落盘原始字节及到达时间，原字节不改写后交回 SDK。请求 hook 校验实际 JSON 与冻结 kwargs 展开 `extra_body` 后完全相同，核对方法、路径、内容类型及鉴权存在；归档保留模型载荷，不保存密钥、认证值或代理凭据。响应只记录状态、有界 Content-Type 等诊断头、字节数与首末包，正常返回后核对原始正文和 SDK 解析结果。

本轮预声明两个条件阶段。A 为一次原非流式请求、零重试及结构恢复，沿原 480 秒整体 deadline。完整 ChatCompletion、正常 `stop`、非空答案及实发载荷一致即确认该输入的调用可完成，并结束本轮付费调用；历史超时及根因未知保持。A 若没有完整有效结果，先封存字节和错误并同步此文，再执行 B：完整 messages、model、thinking 及其他参数保持，只增加 `stream=true`。B 使用同一 SDK 的原生 SSE 迭代，在整体 480 秒内保存每项原始 chunk、正文及服务方实际返回的 `reasoning_content`，记录结束原因及可取得用量；部分内容只作定位，正常结束与完整有效结果分开记录。A 为确定性本地输入或脚手架失败时先修复自身边界，不据此发 B；A 出现明确参数或授权拒绝时先按原始服务错误复审请求，也不盲目换传输。

最大两个逻辑及物理模型调用，SDK 及服务重试均零，80,000 新已知 tokens，首调用起 1,200 秒，单调用响应落盘上限 16 MiB；达到边界安全取消并保留部分事实。组窗口覆盖原失败 480 秒及必要的单变量 SSE 观察，不扩大生产 deadline。累计从 5,822,989 已知 tokens、十一次未知继续，不重置重复阻塞。语义输入保持，模型采样仍不构成确定性时延消融。脚本先执行 lint，归档输入、代码、配置与旧封存校验和；实际结果审计及文档链接、结构检查后封存。

本轮属于 EVD 探索边界的传输诊断，执行系统拥有请求、字节与异常事实，服务方拥有生成结果；业务核验及原六项判据保持，不新增生产字段、状态、开关或流式旁路。A／B 的观察用于决定后续最早责任与修复准入，不能当作真实核验优化通过或完整用户结果。

A 由生产客户端发出一次原 SDK 调用，实际载荷与冻结 kwargs 展开后相等，POST 路径、JSON 类型及 Bearer 存在性已核对。9.09 秒收到 HTTP 200，正文为 gzip 压缩的 chunked JSON；9.10 至 39.10 秒解压后的增量均为换行，约每五秒一次。41.56 秒首次收到非空白正文并结束读取，41.57 秒得到完整 ChatCompletion、非空中文说明及 `stop`；HTTPX 解压后的原正文与 SDK 解析结果一致。等待主要发生在有效正文到达之前，读取结束至解析、校验及客户端关闭完成约 0.014 秒，本次未见请求构造或解析阻塞。证据见[实发协议](../../.tmp/provider-body-diagnosis-20261010/A-wire-protocol.json)、[原请求结果](../../.tmp/provider-body-diagnosis-20261010/A-result.json)及[正文增量审计](../../.tmp/provider-body-diagnosis-20261010/A-body-analysis.json)。

按预声明，A 完整返回后 B 条件不成立，本轮不再发 SSE 付费请求。一个逻辑及物理调用、零重试与结构恢复，新已知用量 5,394 tokens（其中返回的推理计量 1,221），新增未知用量零；累计 5,828,383 已知 tokens、十一次历史未知。请求、完整回答及服务方实际返回的推理记录已归档，同一追问的当前服务阻塞解除，未改变 Prompt、模型、deadline、代理或生产源码。输入源自条件诊断，不记真实语义用例通过。

新信息是非流式响应也会收到保活字节；它们只证明当时仍有数据到达，不代表模型已经输出答案或推理。此前 480 秒失败没有保存正文，故不能追认其也收到相同保活，更不能据当前恢复区分服务排队、推理耗时、上游阻塞或间歇传输故障。HTTPX 单次 read timeout 可能被保活延后，生产整体 deadline 仍正常生效；当前调用可完成不等于历史超时根因已修复。本轮不增加重试、扩大等待或迁移生产 SSE。若后续同边界再失败，须保留该次实际字节及时间，再依据最早失败边界准入修复；需要观察真实生成增量时，由独立预声明以完整输入审计 SSE 的 `reasoning_content` 和 `content`。

## 2026-10-11 正式 Source 复核超时的条件诊断

原中文正式样本 `irun_136c545f011740b3` 已到达真实研究稿、分类反馈及多轮 writer 修订。当前 c2 第四版复核的物理请求 `0034`、`0036` 均达到 480 秒整体时限，没有完整答案或用量；`0038` 是原配置最后一次恢复。完整消息、Schema、Source v19 及模型参数逐字相同，SDK 重试关闭，恢复仅由生产模型客户端拥有。请求和异常在[正式捕获](../../.tmp/source-production-target-20261011/product-model-calls/25752/)持续保存。最后一次恢复取得正常 `stop` 与完整 Source 报告，49,000 tokens，其中服务方返回的推理计量为 13,119；真实选证继续处理其一项缺证反馈。当前共 19 份完整响应、561,809 已知 tokens及两次新增未知；原链未结束，这不是最终用户结果。

若最后一次恢复正常返回并继续原链，本节不触发付费诊断。只有该正式样本最终因同一服务边界失败，冻结原结果并审计请求后，才准入一次 SSE 观察；不另跑正式样本，也不再次重发普通非流式请求。

隔离归档 `.tmp/provider-source-stream-20261011/`。逐字复制正式失败的完整物理请求，仅在 `kwargs` 增加 `stream=true`；消息、`response_format`、模型、thinking、全部四类输入和输出 Schema 保持。使用同一生产客户端配置及原生 SDK 流式迭代，复用上一已封存观察器的请求／响应 hook，只读记录线上实际 JSON、响应头、原始字节、原生 chunk、正文及服务方返回的 `reasoning_content`。线上载荷须等于原载荷展开 `extra_body` 后仅增加的流式字段；不保存认证值或代理凭据。

一个逻辑及物理调用，SDK、服务与结构修复均零重试，480 秒整体时限、600 秒诊断窗口、80,000 新已知 tokens、16 MiB 响应字节上限。正常 `stop`、完整非空正文及实际输入一致分别记录；部分正文、推理或保活只用于定位。完整 JSON 由原 Source 类型解析，解释其实际发现，但不计局部优化或 Product E2E 通过。明确的参数、授权或本地构造失败直接停止，在自身边界复审；仍无完整结果时保存部分证据，不追加第三种调用或扩大预算。

累计用量从原 7,107,612 已知 tokens，加本次正式调用最终实测值继续；历史十一次未知及本次无用量尝试分别保留。脚本执行前固定来源请求、全部生产源码、`.env` 与观察器身份，执行 lint；诊断后同步本页及正式接入设计，检查实际输入、返回边界和封存校验和。此项属于 EVD 隔离诊断，不修改 Source、writer、恢复策略或生产 SSE 装配；原局部六项、四项和三项成绩保持。
