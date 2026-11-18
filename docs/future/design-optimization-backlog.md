# 设计优化队列

**本文件唯一登记尚未解决的问题、准入级别与设计入口，数量以当前队列表为准。** 候选机制正文由对应 `optimization/to_verify/` 文档拥有；Future 专题只补充产品准入与剩余门禁，不复制第二份方案或状态队列。

当前生产事实由[当前核心架构](../architecture/core-architecture-current-state.md)和对应专题文档拥有；当前样本、结果与证据边界由[当前评测用例盘点](../evals/02-current-case-inventory.md)拥有；评测入口与发布门禁由[评测执行与发布](../evals/04-running-and-release.md)拥有。本文只引用这些事实，不建立第二份结果台账。

表中的编号表示优化项；引用评测用例时必须写出具体场景，例如 `E2E-USER-OUTCOME-CONTRACT-001/ASK-001B`，避免把优化项闭环与单个 E2E case 混称。

## 1. 当前队列

| 编号 | 尚未解决的问题 | 当前准入 | 设计与推进记录 |
| --- | --- | --- | --- |
| `CONVERSATION-LOOP-BOUNDARIES-001` | 历史无核验流程已验证，原 C6 尚有未覆盖反事实，轮次身份已切换 | 原生正文／动作已接入，LongDS 36/36 轮交付及跨进程接续通过。REST、Step、Toolathlon Session 和 Bash 资源归属已切换。服务端历史、SQLite 及迁移仍待实施和验收 | [统一 Schema 结果](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)、[历史压缩](../optimization/to_verify/conversation-loop-boundaries.md#311-context-压力与压缩)、[生命周期替换及证据](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期) |
| `KNOWLEDGE-DECISION-DELIVERY-001` | 长程目标解释与核验仍待用户结果验收，完整交互卸载与压缩取得局部连续证据 | `A2` 保留目标维护、已成立的核验职责分离及[单正文工具契约](../optimization/completed/conversation-goal-contract.md)。最新无生产改动连续链交付20/34，5次自然压缩及107次主请求审计取得局部证据；外部重启后已补齐20份答案原评分，7/20通过，目标范围及多报仍有错误。完整34轮语义和后续压力尚未验证，历史成绩保持；不追加任务专属提示 | [现行修订§9.20](../optimization/to_verify/analysis-goal-maintenance.md#920-结果卸载与完整交互压缩)、[实际结果](../evals/02-current-case-inventory.md) |
| `RUNTIME-POLICY-AUDIT-ISOLATION-001` | 审计绑定修复已接入且真实阶段回放通过，原完整对话 target 未交付 | `A2`：baseline 0/1、target 0/1、审计阶段反事实 1/1；完整产品验收未过，停止新增模型样本 | [修复证据与剩余边界](../optimization/to_verify/runtime-policy-audit-isolation.md) |
| `MODEL-PROVIDER-DIAGNOSTICS-001` | 原 HTTP 错误体真实条件尚未触发 | `A2`：错误体及传输异常诊断均已接入，局部固定反事实通过；本轮传输交接已关闭，不再作为剩余门禁。原 429 具体原因无法追溯，真实错误体条件保留未覆盖 | [Provider 失败诊断交接](../optimization/to_verify/model-provider-diagnostics.md) |
| `MODEL-PROVIDER-TRANSPORT-001` | MiMo 工具流式已接入，新完整轨迹因供应商过滤停止 | `A2`：工具 SSE／完整用量／auto 已接入，required 校验保持；四个完整阶段及正式 Web 故障回放通过。真实 target 已取得完整过滤响应，已知消费正确保留，未出现此前断流；完整任务仍未交付，过滤原因未知，失败段评分准入待修正。旧失败／未知不改写，不主张网络根因已解决 | [传输规格与验收](../optimization/model-provider-transport.md#2026-10-23-mimo-工具流式接入规格) |
| `CONVERSATION-RESEARCH-STOP-001` | 网页工具分离及其他既定研究边界尚未全部闭环 | `A2`：旧研究目标正式续验按原身份通过；网页工具分离和现行答复质量分别验收 | [网页工具分离](conversation-web-research-tools.md)、[来源语义与修订设计](conversation-verification-false-positive.md)、[验证推进记录](../optimization/conversation-source-support.md) |
| `CONVERSATION-RESEARCH-SOURCE-AUTHORITY-001` | 官方正文抓取失败后，Final 把社区讨论引用为官方工具文档依据 | `A1`：取证后的来源判断与答案合成待归因，没有活动候选 | — |
| `AGENT-DELEGATION-DELIVERY-001` | 用户明确要求委托外部研究智能体时，子级运行与父级最终交付都不稳定 | `A1`：子级超时与父级未交付是独立失败阶段；当前没有活动候选 | — |
| `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` | 当前响应内的前台委托仍可能被误判为响应后的后台持续工作 | `A1`：Provider 语义方差仍存在；当前没有活动设计 | — |
| `BACKGROUND-CONTINUATION-LIMITATION-001` | 明确要求响应后继续时，系统仍不能稳定保持类型化 `limitation` 与零后台执行 | `A1`：最早失败仍属于 `InteractionIntent` Semantic Decision；当前没有活动设计 | — |
| `E2E-USER-OUTCOME-CONTRACT-001` | `ASK-001B` 尚未验收回答是否基于官方来源解释工具使用机制 | `A1`：概率性语义 grader 按约定后置；当前没有活动候选 | [E2E 用户结果契约对齐方案](e2e-user-outcome-contract-alignment.md) |
| `CITATION-SOURCE-ATTRIBUTION-001` | 来源绑定修复后的正式交付及因果回归尚未验收 | `A2`：确定性修复已接入目标代码；局部证据与原始 E2E 分开，完整门禁未过 | [引用来源修复的剩余验收](citation-source-binding.md)、[过程记录](../optimization/citation-source-attribution.md) |
| `CITATION-COORDINATE-CONFUSION-001` | 新协议正式稿使用目录外编号；原文行号与临时引用号并存，同位置重读有多个引用身份 | `A2`：全部生成端引用已统一为文档行坐标并删除结果号，支持连续整行范围；仅 Offline 验证，按新代码身份累计的正常 E2E 观察仍为 0 | [统一坐标后的剩余验证](citation-coordinate-identity.md)、[问题记录](../optimization/citation-coordinate-confusion.md) |
| `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` | 统一答复针对来源归属、范围及目标判据仍需现行轨迹验证 | `A1`：依赖旧 claim writer 或统一研究报告的候选已撤回；沿用真实失败的判据，先确认是否在当前答复核验复现，无新生产候选 | [现行核验准入](conversation-verification-false-positive.md)、[旧链失败证据](../optimization/claim-revision-nonconvergence.md) |
| `TOOL-MODEL-USAGE-HANDOFF-001` | 普通核验已接入计量，历史合法接受及契约失败的当前版本回放待验 | `A2`：逐调用绑定已实施，真实语义拒绝、未知停止及整条已知用量等式成立；不向其他工具／Agent 外推 | [当前机制与剩余边界](../optimization/tool-model-usage-handoff.md) |
| `ANSWER-NORMATIVE-SCOPE-001` | 回答的具体来源归属和否定范围仍有历史反例 | `A1`：旧研究核验候选已撤回，引用恢复局部结论及原正式 0/1 保留；先查当前答复是否复现 | [已验边界](../optimization/completed/source-proof-boundary-isolation.md)、[真实反例](../optimization/normative-scope-attribution.md) |
| `ANSWER-ENUMERATION-SCOPE-001` | 修订会把有范围的列举写成完整范围 | `A1`：旧研究阶段已撤回；其拒稿、真实修订及独立通过保留原身份，当前答复是否复现须另查 | [原修订反例](../optimization/claim-revision-nonconvergence.md#独立阻塞恢复与原方案续验) |
| `CONVERSATION-RESEARCH-SAVE-MISROUTE-001` | 整体 Context 候选的研究任务误转保存确认；当前保留组合是否复现及候选因果责任尚未确定 | `A0`：仅执行当前正式入口 baseline，不准入实现 | [研究任务误转保存确认的准入审计](conversation-research-save-misroute.md) |

`A0` 项进行基线准备、事实审计、对应 baseline 及 [EVD 探索边界](../devSpec/change-evidence.md#13-探索与生产准入边界)内的隔离诊断，不创建生产接口、共享状态、表、配置开关或测试旁路。具体问题已声明的更窄范围仍适用。`A1` 项进行失败归因、设计和候选准入。`A2` 项实现已获准最小切片并执行预声明门禁；失败时按 EVD 归因，不扩大同方向补丁或运行无增益 E2E。没有活动实现候选时，不把诊断脚本或草案投入生产；文档存在不等于实现获准。

## 2. 准入顺序

按 [EVD 开发流程](../devSpec/change-evidence.md#7-强制开发与设计流程)取得分类依据、定义因果边界与指标，再实施和验证；外部比较只在 EVD 指定范围适用。完成按 [REL](../devSpec/migration-release.md#3-完成检查表)判断，不在队列复制另一套执行门禁。

## 3. 队列维护

- 本文件的每个队列项只能保存编号、问题、当前准入、独立设计与对应推进记录链接。禁止在表格或正文展开 Schema、对象、文件、实施步骤、测试命令、指标门槛、消融方法、外部机制比较或退出条件。
- 产品准入专题位于 `docs/future/`，机制候选位于 `optimization/to_verify/`；两者回链本清单并明确覆盖边界。没有活动设计时链接列写“—”，可附问题证据入口，不以队列表格代替候选正文。
- 一个设计覆盖多个队列项时，链接文字必须标明覆盖边界；设计文档不得把局部前置条件冒充为其他队列项已经解决，也不得维护第二份优先级或状态表。
- 问题被当前 baseline 否定、没有达到准入门槛或根因归属不成立时，直接从本文件删除；诊断结论和经验按 [optimization 记录规则](../optimization/README.md)集中保留，原始证据独立封存。
- 局部机制或完整问题的关闭按 [Future 状态收敛](README.md#状态变化必须在同一变更收敛)处理。仅接入代码不能移除仍未闭环问题；已证明局部成果按 [completed 规则](../optimization/README.md#已解决问题的固化规则)固化，不把独立问题混作原机制残留。
- 本文件只保留判断问题能否继续推进所需的最小事实。过程、命令与结果在 optimization 对应专题集中记录，活动设计与过程记录双向链接；正式评测和发布状态由评测权威文档维护。
