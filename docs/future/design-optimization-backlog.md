# 设计优化队列

**本文件唯一登记尚未解决的问题、准入级别与设计入口，数量以当前队列表为准。** 候选机制正文由对应 `optimization/to_verify/` 文档拥有；Future 专题只补充产品准入与剩余门禁，不复制第二份方案或状态队列。

当前生产事实由[当前核心架构](../summary/core-architecture-current-state.md)和对应专题文档拥有；当前样本、结果与证据边界由[当前评测用例盘点](../evals/02-current-case-inventory.md)拥有；评测入口与发布门禁由[评测执行与发布](../evals/04-running-and-release.md)拥有。本文只引用这些事实，不建立第二份结果台账。

表中的编号表示优化项；引用评测用例时必须写出具体场景，例如 `E2E-USER-OUTCOME-CONTRACT-001/ASK-001B`，避免把优化项闭环与单个 E2E case 混称。

## 1. 当前队列

| 编号 | 尚未解决的问题 | 当前准入 | 设计与推进记录 |
| --- | --- | --- | --- |
| `MODEL-PROVIDER-DIAGNOSTICS-001` | 模型服务失败的实际错误体诊断仍待真实条件验收 | `A2`：诊断链反事实 2/2，已接入唯一异常与日志路径；原 E2E 未复现服务错误，实际 MiMo 条件继续待验证 | [Provider 失败诊断交接](../optimization/to_verify/model-provider-diagnostics.md) |
| `MODEL-PROVIDER-TRANSPORT-001` | 模型请求间歇传输失败或超过 deadline，具体原因尚未定位 | `A1`：原失败请求续验可返回，正式轨迹再次出现传输与 deadline 失败，现有重试后继续；没有传输修补 | [真实失败、连接路径排查与恢复入口](../optimization/model-provider-transport.md) |
| `CONVERSATION-RESEARCH-STOP-001` | 原预算下取证与交付未收敛；宽预算已自主交付，但 Final 仍存在证据覆盖缺口、旧稿复用、无据结论与不完整产物 | `A2`：网页工具分离尚未闭环；已证实的 Loop 反馈与验证执行预算修复已接入，完整交付未通过；独立来源支持检查已接入，完整语义与修订仍待验证；独立评分资格见完成记录，原用户结果保持失败 | [网页工具分离](conversation-web-research-tools.md)、[来源语义与修订设计](conversation-verification-false-positive.md)、[验证推进记录](../optimization/conversation-source-support.md) |
| `CONVERSATION-RESEARCH-SOURCE-AUTHORITY-001` | 官方正文抓取失败后，Final 把社区讨论引用为官方工具文档依据 | `A1`：取证后的来源判断与答案合成待归因，没有活动候选 | — |
| `AGENT-DELEGATION-DELIVERY-001` | 用户明确要求委托外部研究智能体时，子级运行与父级最终交付都不稳定 | `A1`：子级超时与父级未交付是独立失败阶段；当前没有活动候选 | — |
| `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` | 当前响应内的前台委托仍可能被误判为响应后的后台持续工作 | `A1`：Provider 语义方差仍存在；当前没有活动设计 | — |
| `BACKGROUND-CONTINUATION-LIMITATION-001` | 明确要求响应后继续时，系统仍不能稳定保持类型化 `limitation` 与零后台执行 | `A1`：最早失败仍属于 `InteractionIntent` Semantic Decision；当前没有活动设计 | — |
| `E2E-USER-OUTCOME-CONTRACT-001` | `ASK-001B` 尚未验收回答是否基于官方来源解释工具使用机制 | `A1`：概率性语义 grader 按约定后置；当前没有活动候选 | [E2E 用户结果契约对齐方案](e2e-user-outcome-contract-alignment.md) |
| `CITATION-SOURCE-ATTRIBUTION-001` | 来源绑定修复后的正式交付及因果回归尚未验收 | `A2`：确定性修复已接入目标代码；局部证据与原始 E2E 分开，完整门禁未过 | [引用来源修复的剩余验收](citation-source-binding.md)、[过程记录](../optimization/citation-source-attribution.md) |
| `CITATION-COORDINATE-CONFUSION-001` | 新协议正式稿使用目录外编号；原文行号与临时引用号并存，同位置重读有多个引用身份 | `A2`：全部生成端引用已统一为文档行坐标并删除结果号，支持连续整行范围；仅 Offline 验证，按新代码身份累计的正常 E2E 观察仍为 0 | [统一坐标后的剩余验证](citation-coordinate-identity.md)、[问题记录](../optimization/citation-coordinate-confusion.md) |
| `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` | 最终答案仍有实际来源归属错误，生产核验未拦截；用户目标和断言范围判别仍待验证 | `A2`：evidence-first 与两侧组合保持；最终身份绑定由完成记录拥有，原用户语义结果仍未通过，停止同向补丁 | [Conversation Draft 语义验证隔离设计](conversation-verification-false-positive.md)、[无法收敛的子问题](../optimization/claim-revision-nonconvergence.md)、[研究与覆盖联合候选](../optimization/to_verify/research-goal-coverage.md) |
| `RESEARCH-SELECTION-USAGE-COMMIT-001` | 已完成选证用量在 writer 或选证输出失败时未持久化，预算与恢复缺少该笔成本 | `A2`：及时提交及失败响应交接已接入；真实回放及恢复去重尚未验收 | [计量候选](../optimization/to_verify/research-selection-usage-commit.md)、[失败记录](../optimization/research-selection-usage-commit.md) |
| `TOOL-MODEL-USAGE-HANDOFF-001` | 工具内部已完成模型用量未交回 Conversation 总账 | `A1`：终态逐分项差额已定位，尚未准入实现 | —；[责任边界与证据](../optimization/tool-model-usage-handoff.md) |
| `ANSWER-NORMATIVE-SCOPE-001` | 原正式稿存在流程步骤出处错配；新增非规范性指导被写为协议要求 | `A2`：具体来源归属已正式消费；隔离选证v8、来源v2撤回；追加真实r4的A1条件诊断3/3，已拟定Source任务约束物化及真实取证复验方案；完整输入校准、连续链与生产接入尚未执行，待重新准入 | [具体来源归属候选](../optimization/to_verify/answer-source-attribution.md)、[规范性归属方案复审](../optimization/to_verify/normative-context-acquisition.md) |
| `ANSWER-ENUMERATION-SCOPE-001` | 当前稿核验已正式消费，完整用户结果待已校准参考续验 | `A2`：校准与实际反馈连续链成立，生产 v6 保持；原评分缺页已修复，依据不足的覆盖候选撤回；初始状态问题已固化；正式拒稿、真实修订及当前稿独立通过已成立，完整结果因非规范性章节限定缺失0/1 | [独立核验候选](../optimization/to_verify/final-revision-comparison.md)、[验证记录](../optimization/claim-revision-nonconvergence.md#独立阻塞恢复与原方案续验) |
| `CLAIM-SUPPORTED-SCOPE-REPAIR-001` | 特定主体缺证被改写为更广否定，首次语义修订仍需验证 | `A2`：真实反馈与来源已送达；引用交接由完成记录独立拥有 | [支持范围候选](../optimization/to_verify/claim-supported-scope-repair.md)、[引用交接完成记录](../optimization/completed/claim-atomic-evidence-revision.md) |
| `RESEARCH-SELECTION-OUTPUT-TRUNCATION-001` | 正式选证截断阻断研究，服务方默认额度候选的恢复效果待验证 | `A2`：默认额度契约已接入，真实消费验收尚未执行 | [默认额度候选](../optimization/to_verify/research-provider-output-default.md)、[失败与推进记录](../optimization/claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究) |
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
