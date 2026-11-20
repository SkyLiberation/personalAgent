# 设计优化队列

**本文件唯一登记尚未解决的问题、准入级别与设计入口，数量以当前队列表为准。** 候选机制正文由对应 `optimization/to_verify/` 文档拥有；Future 专题只补充产品准入与剩余门禁，不复制第二份方案或状态队列。

当前生产事实由[当前核心架构](../architecture/core-architecture-current-state.md)和对应专题文档拥有；当前样本、结果与证据边界由[当前评测用例盘点](../evals/02-current-case-inventory.md)拥有；评测入口与发布门禁由[评测执行与发布](../evals/04-running-and-release.md)拥有。本文只引用这些事实，不建立第二份结果台账。

表中的编号表示优化项；引用评测用例时必须写出具体场景，例如 `E2E-USER-OUTCOME-CONTRACT-001/ASK-001B`，避免把优化项闭环与单个 E2E case 混称。

## 1. 当前队列

| 编号 | 尚未解决的问题 | 当前准入 | 设计与推进记录 |
| --- | --- | --- | --- |
| `CONVERSATION-LOOP-BOUNDARIES-001` | 原 C6 的非空未决项保护、压缩后跨进程复用和原 E3 交付仍未覆盖 | `A2`：保留原 C6／E3 剩余验收 | [压缩验收](../optimization/to_verify/conversation-loop-boundaries.md#311-context-压力与压缩)、[实际结果与边界](../optimization/to_verify/conversation-loop-schema.md#16-完整运行结果与实际边界)、[会话与轮次接续证据](../optimization/to_verify/conversation-loop-boundaries.md#320-sessionturn-与-step-生命周期) |
| `KNOWLEDGE-DECISION-DELIVERY-001` | 长程目标解释、约束遵守及完整任务的用户结果仍有失败 | `A2`：目标维护与完整交互压缩已接入，按原场景分别验收语义与交付 | [目标维护](../optimization/to_verify/analysis-goal-maintenance.md)、[实际结果](../evals/02-current-case-inventory.md) |
| `RUNTIME-POLICY-AUDIT-ISOLATION-001` | 原正式对话样本未交付 | `A2`：审计绑定的真实阶段反事实已通过，停止新增模型样本 | [修复证据与剩余边界](../optimization/to_verify/runtime-policy-audit-isolation.md) |
| `MODEL-PROVIDER-DIAGNOSTICS-001` | 原 HTTP 错误体的真实透传未覆盖 | `A2`：诊断交接已接入 | [Provider 失败诊断交接](../optimization/to_verify/model-provider-diagnostics.md) |
| `MODEL-PROVIDER-TRANSPORT-001` | MiMo 正式样本因供应商过滤中止，失败段评分准入待修正 | `A2`：工具流式已接入，完整任务未交付 | [传输规格与验收](../optimization/model-provider-transport.md#2026-10-23-mimo-工具流式接入规格) |
| `CONVERSATION-RESEARCH-STOP-001` | 网页发现与读取分离对原预算下完整交付的独立贡献待证 | `A2`：工具分离已接入，保留原定对照 | [工具分离剩余验收](conversation-web-research-tools.md)、[取证记录](../optimization/evidence-acquisition.md) |
| `CONVERSATION-RESEARCH-SOURCE-AUTHORITY-001` | 官方正文抓取失败后，Final 把社区讨论引用为官方工具文档依据 | `A1`：取证后的来源判断与答案合成待归因，没有活动候选 | — |
| `AGENT-DELEGATION-DELIVERY-001` | 用户明确要求委托外部研究智能体时，子级运行与父级最终交付都不稳定 | `A1`：子级超时与父级未交付是独立失败阶段；当前没有活动候选 | — |
| `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` | 旧前置分类曾把当次答复内的委托误判为跨响应后台工作 | `A1`：需确认统一主循环是否复现 | [原反例](../evals/02-current-case-inventory.md#1-conversation-与-knowledge)、[统一主循环](../optimization/to_verify/analysis-goal-maintenance.md#统一-conversation-主循环) |
| `BACKGROUND-CONTINUATION-LIMITATION-001` | 旧前置分类曾将明确要求响应后继续的请求送入执行 | `A1`：需确认统一主循环能否返回明确限制并保持零后台执行 | [原反例](../adr/0015-withdraw-investigation-project.md)、[现行后台边界](../architecture/core-architecture-current-state.md#4-后台持续运行边界) |
| `E2E-USER-OUTCOME-CONTRACT-001` | `ASK-001B` 尚未验收回答是否基于官方来源解释工具使用机制 | `A1`：概率性语义 grader 按约定后置；当前没有活动候选 | [E2E 用户结果契约对齐方案](e2e-user-outcome-contract-alignment.md) |
| `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` | 旧链对来源归属、列举范围和目标条件的误判在统一答复中是否复现尚待确认 | `A1`：按历史失败判据检查现行轨迹 | [现行核验准入](conversation-verification-false-positive.md)、[旧链反例](../optimization/claim-revision-nonconvergence.md) |
| `TOOL-MODEL-USAGE-HANDOFF-001` | 普通核验合法接受及契约失败的当前版本回放待验 | `A2`：逐调用计量已接入 | [计量证据与剩余边界](../optimization/tool-model-usage-handoff.md) |
| `ANSWER-NORMATIVE-SCOPE-001` | 旧链曾将流程归给错误来源，否定范围也有反例 | `A1`：需确认统一答复是否复现 | [来源归属反例](../optimization/normative-scope-attribution.md) |
| `ANSWER-ENUMERATION-SCOPE-001` | 旧链修订曾把部分列举写成完整清单 | `A1`：需确认统一答复是否复现 | [原修订反例](../optimization/claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举) |
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
