# 模型服务传输失败阻断核验

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
