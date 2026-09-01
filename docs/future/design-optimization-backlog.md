# 设计优化队列

**当前活动实现候选为 1，条件详细设计为 3。** 本文件只登记尚未解决的问题、准入级别和详细设计入口；模型、E2E、消融、复杂度预算、实施步骤与退出条件只能写入对应的独立设计文档。详细设计不得建立第二份状态队列，准入状态以本文件为准。

当前生产事实由[当前核心架构](../summary/core-architecture-current-state.md)和对应专题文档拥有；当前样本、结果与证据边界由[当前 E2E 用例盘点](../evals/02-current-case-inventory.md)拥有；评测入口与发布门禁由[评测执行与发布](../evals/04-running-and-release.md)拥有。本文只引用这些事实，不建立第二份结果台账。

## 1. 当前队列

| 编号 | 尚未解决的问题 | 当前准入 | 详细设计 |
| --- | --- | --- | --- |
| `CONVERSATION-RESEARCH-DELIVERY-001` | 普通 Conversation 研究不能稳定交付满足来源与结论要求的用户结果 | `A2`：原子 `HARNESS-003` target 已交付，Tool Calling 影响验证为 `4/4 capability passed`；当前只剩独立代码身份的单变量验证，尚未达到发布或移除条件 | [普通对话研究交付与 Plan 边界优化方案](conversation-research-delivery.md) |
| `CONVERSATION-RESEARCH-EFFICIENCY-001` | 已交付的广泛研究样本仍累积较多搜索结果和动作定义，尚未建立可公平比较的成功路径成本 baseline | `A1`：单样本确认 Context 增长；机制责任主体与重复样本门槛尚未准入 | [普通对话研究效率优化方案](conversation-research-efficiency.md) |
| `AGENT-DELEGATION-DELIVERY-001` | 用户明确要求委托外部研究智能体时，子级运行与父级最终交付都不稳定 | `A1`：子级超时与父级未交付是独立失败阶段；当前没有活动候选 | — |
| `INTERACTION-INTENT-DELEGATION-BOUNDARY-001` | 当前响应内的前台委托可能被误判为响应后的后台持续工作 | `A1`：正反方向错误均已复现；当前候选已撤回 | — |
| `BACKGROUND-CONTINUATION-LIMITATION-001` | 用户明确要求响应后继续、稍后领取结果时，系统不能稳定保持类型化 `limitation` 与零后台执行 | `A1`：最早失败属于 `InteractionIntent` Semantic Decision；当前候选已撤回 | — |
| `E2E-USER-OUTCOME-CONTRACT-001` | 部分用例声明的用户结果强于可执行断言，支持性流水线事实也可能被误述为内容质量证据 | `A1`：两条 Product E2E 的结果契约缺口已确认；两条 supporting evidence 的结论边界需固化 | [E2E 用户结果契约对齐方案](e2e-user-outcome-contract-alignment.md) |

`A0` 项只能执行对应的需求或失败 baseline；不得创建接口、模型、状态、表、队列、配置或测试旁路。`A1` 项只允许继续做当前失败归因、详细设计和候选准入。`A2` 项只允许实现已获准的最小纵向切片并执行预声明门禁；门禁失败时停止扩大修改和 E2E。表中没有活动实现候选时，不得把诊断脚本、提示词草案或局部补丁投入生产。独立设计文档存在不等于实现已获准。

## 2. 准入顺序

每个队列项必须按以下顺序推进；完整门禁由[变更证据与设计准入](../devSpec/change-evidence.md)和[迁移、ADR 与完成门禁](../devSpec/migration-release.md)拥有：

1. 从正式入口执行当前最简单路径，冻结自然输入、身份、初始事实、服务提供方、预算、评测器和关键反事实。
2. 用 `Trace`、`AgentRun`、`Artifact`、Admission feedback 和服务提供方事实定位一个最早失败阶段，明确事实 owner、决策 owner 与唯一写入口。
3. 按机制域核对至少两个独立 A 级实现；外部实现只说明机制可行性，不能替代本工程 baseline。
4. 提交 Complexity Justification，声明唯一变量、生产消费者、计划删除内容、target 门槛和退出条件；声称 Application Capability 或 Runtime Mechanism 改善用户结果、成本、延迟或恢复时还必须声明消融方法。未通过评审不得编码。
5. 缺陷修复在 target 达标后执行必要回归；机制收益候选还必须执行同输入单变量消融。对应 target、回归或消融失败时删除候选，不保留 flag、fallback、alias 或双轨入口。

## 3. 队列维护

- 本文件的每个队列项只能保存编号、问题、当前准入和独立设计链接。禁止在表格或正文展开 Schema、对象、文件、实施步骤、测试命令、指标门槛、消融方法、外部机制比较或退出条件。
- 进入详细设计的队列项必须使用 `docs/future/` 下的独立文档；该文档必须反向链接本清单，并把状态 owner 明确留在本文件。没有活动设计时链接列写“—”，不得在清单中用下一步说明代替设计文档。
- 一个设计覆盖多个队列项时，链接文字必须标明覆盖边界；设计文档不得把局部前置条件冒充为其他队列项已经解决，也不得维护第二份优先级或状态表。
- 问题被当前 baseline 否定、没有达到准入门槛或根因归属不成立时，直接从本文件删除；诊断结论只保留在 `docs/evals/` 或密封证据归档。
- 机制被接受并落地后，把当前事实写入摘要、专题、固定流程或运维文档，再删除对应详细设计项并从本文件移除；跨模块取舍按需写入 ADR。
- 结果数字、归档坐标、测试命令和发布状态只在各自权威文档维护。本文件只保留判断该问题能否继续推进所需的最小事实。
