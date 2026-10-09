# 研究评分的目标映射、断言范围与依据归属

**`RESEARCH-ANSWER-GRADER-QUALIFICATION-001` 的当前协作任务评分资格已通过限定样本验证，现行共用评分入口为 `research-answer-task-support-zh-v8-grounded-findings`。** 清理后的控制集 13/13 符合预声明；包含两份真实正式答案和 11 个相邻控制。最新答案仍因实际引用错配拒绝，原 Product E2E 0/1 保持。正式结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-02-独立评分的必要性与来源归属校准)拥有。

## 问题与结论

旧报告把资料中的字段或建议扩大为必答项，把作者的局部取证描述解释成全域否定，还把参考未收录的页面列为产品无据声明。用户目标拥有交付范围，参考只提供外部内容依据；评分须证明缺项对用户结果的必要性，并按作者实际断言及上下文核对支持。

输出 schema 可选性不是原用户独立要求。答案若明确把有条件义务写成所有工具的普遍要求，按事实错误拒绝；只有局部引句没有可选性说明，不自动形成独立缺项。服务器权限职责同样按具体用户问题和完整答案判断，逐条复述安全清单不成为固定验收条件。

## 采用机制与责任

- 调用方提供完整用户请求、完整实际答案和带来源的官方原文快照。当前数据补齐实际引用的架构页和远端 MCP 页，原文保留行号与抓取身份；具体资料和控制标签不进入通用 Prompt。
- 模型提交 `missing_requirement`、`factual_error`、`citation_mismatch` 或 `evidence_gap`，选择当前用户、答案与参考的引用，生成理由及实质影响。缺项绑定用户要求；明确错误和引用错配绑定答案及可确认原文；缺少评分依据独立报告。
- 评分 Runtime 从本次权威输入恢复原文。未知、跨角色或重复引用拒绝，零有效评分；原文身份不依赖模型重抄。Runtime 从有效 findings 推导 `failed`、`inconclusive` 或 `passed`，共用 E2E 消费者只接受 `passed`。
- 取证历史由执行记录拥有。独立评分检查正文实际肯定的内容及用户交付；完整参考没有证明作者实际读取了全部原文。来源支持与目标覆盖分别判断。

实现位于[共用评分模块](../../../evals/e2e_quality/research_answer_outcome.py)，由[正式研究 E2E 消费者](../../../evals/product_baselines/test_conversation_research_delivery_001.py)和[真实模型 Offline Eval](../../../evals/e2e_quality/test_research_answer_outcome.py)调用。旧人工事实摘要、无坐标字符串列表及模型总布尔判断已同边界替换。三个 eval 源码净增 14 行、增加四个评测类型；生产源码 262 份逐字保持，没有新增生产阶段、存储或开关。

## 决定性证据与适用范围

[清理控制计划](../../../.tmp/research-grader-review-controls-20261002/plan.json)固定状态标签及相邻语义边界，评分 Prompt、Schema、模型和参考沿同一候选保持。两份真实答案、正例及反例均使用 `mimo-v2.6-flash`、JSON Object、thinking 开启、32768 输出额度和 480 秒超时；每个输入只执行一次。通过输入身份复用已完成报告，不重复采样寻找成功。

[最终结果](../../../.tmp/research-grader-review-controls-20261002/summary.json)为 13/13：正确限定和无需额外字段的回答通过；真实职责缺项、引用错配及义务扩大/弱化拒绝；评分参考缺页为 inconclusive。[SDK 与原文绑定审计](../../../.tmp/research-grader-review-controls-20261002/input-and-cost-audit.json)确认 14 次物理响应、622303 tokens，其中资格样本 578783，剔除的弱控制 43520；全部思考开启、reasoning 保留，无额外重试。两份原始正文末尾带 `parameter`，由现行确定性解析契约取出同一 JSON 对象，无额外模型恢复，原响应保留。

最新真实稿明确把 function calling 的四个流程步骤归到 MCP 架构页。完整架构原文未列该流程，函数调用页有逐步依据；新评分据此拒绝，未沿用字段必答、片段未知等于全域不存在的旧理由。较早真实稿因客户端校验责任未交付及一处 URL 错配拒绝。原 E2E 与新评分身份分开，未重跑未变化的生产研究，也未增加发布分子。十三项资格属于该任务与控制范围，稳定性和其他任务需相应代表性证据。

## 失败尝试与审查修正

| 尝试 | 失败依据与取舍 |
| --- | --- |
| v7 用户原话转录与原文输入 | 实际 2/9、资格正确 1/2；仍把评分参考范围混作作者取证历史，撤回接入。原[报告](../../../.tmp/research-grader-qualification-20261001/diagnostic/summary.json)保持 |
| v8 首轮资格预设最新稿只能以缺项拒绝 | 实际发现有据引用错配，原额外分类约束使资格 1/2、2/13 后停止。原[记录](../../../.tmp/research-grader-review-20261002/summary.json)保持；[审查](../../../.tmp/research-grader-review-followup-20261002/qualification-review.json)纠正人工附加要求，模型输入与报告未改 |
| 复用的单删服务器访问控制反例 | 原总结仍把访问控制归给服务器，未形成完整删除；6/13、正确 5/6 后停止。原[记录](../../../.tmp/research-grader-review-followup-20261002/summary.json)保持，不能据此证明评分漏放。按[反事实审查](../../../.tmp/research-grader-review-controls-20261002/counterfactual-review.json)剔除弱控制，新自然请求明确询问服务器权限义务，正文同步去掉残留；新控制预声明后只执行一次 |

## 实际引用页面与版本的参考资格

`RESEARCH-GRADER-MCP-REFERENCE-001` 已解除本次已定位的依据缺口。唯一[参考fixture](../../../evals/e2e_quality/fixtures/research_answer_official_references.json)保留原七页，补入独立抓取的 OpenAI `/api/docs/mcp` 相关完整读窗及答案实际引用的2025-06-18版 MCP tools 全文，当前参考身份为 `official-sealed-excerpts-20261008-exact-citations-v5`。来源 URL、抓取正文和版本分别有身份；新旧规范页不能互相替代精确引用依据。参考继续属于评测输入，不进入生产研究，也不证明作者已读到相应内容。v8 Prompt、Schema、用户契约和控制标签保持。

固定既有完整正例与客户端校验缺失反例各一次，资格 **2/2**；原实际完整答案重评一次，引用缺口解除、findings为空。三项共192,273已完成tokens，实际请求、绑定和成本见[资格归档](../../../.tmp/research-reference-version-gap-20261008/qualification-result.json)。这是新参考身份下的条件Offline证据；原正式失败、旧评分和未知费用保留，正式用户结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-08-精确引用版本与评分资格复核)拥有。不将原13/13算作新参考版本执行通过，也不据两个固定控制估计判决稳定性。

失败尝试保留两条边界：只追加指南整页时未保留初始r2负标签，原参考资格0/1；指南改为相关完整读窗后，又发现旧版规范缺页，原资格仍0/1。精确引用缺页由独立版本抓取和明确正反控制解决；r2原单次“核心关系缺失”标签在补齐依据后不再稳定，按完整用户问题、各方已交付职责和允许未知的范围复核，未据该标签接入新的覆盖Schema。不能通过要求保证未经取证的内部衔接来迎合旧拒绝。

## 重新打开条件

出现与实际原文冲突的错误归类、把非必要资料升级为必答项、局部范围误读、无法确认的引用直接判产品错误，或干净关键反例被错误放行时，按完整请求与当前输入身份重新审查。语义反例不重开已固化的输出预算机制，也不抹去历史 E2E 失败。

可复用的开发经验见[评分器与控制标签都要受审查](../../interview/10-development-pitfalls.md#13-评分器与控制标签都要受审查)。
