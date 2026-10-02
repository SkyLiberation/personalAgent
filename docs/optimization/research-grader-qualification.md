# 研究答案独立评分的参考覆盖与验收映射

`RESEARCH-ANSWER-GRADER-QUALIFICATION-001` 拥有当前评分语义的资格问题，准入由[Future 队列](../future/design-optimization-backlog.md)拥有。输出截断机制见[预算固化记录](completed/research-grader-output-budget.md)。此前 v5 的中文协作任务尚无完整正反例资格，本次恢复输出后审查实际判据，保持原用户结果契约。

## 已确认的输入与判断差异

[实际原请求恢复](../../.tmp/research-grader-budget-20261001/diagnostic/result.json)消费上一正式入口真正交付的完整答案。有效报告判为未通过，人工审查见[判据分类](../../.tmp/research-grader-budget-20261001/semantic-review.json)。

| 边界 | 实际差异 | 归因 |
| --- | --- | --- |
| 评分参考覆盖 | 用户答案与生产来源包含 `tools-connectors-mcp` 和 MCP 规范入口；独立参考集只含 function-calling、server/tools、schema | 报告对这些页标记“给定依据无法核验”说明评分输入缺确认依据，不能据此认定生产引用无支持 |
| 用户要求映射 | 原 goal 要求协作、选择调用、权限检查、结果校验和层次区分；报告额外要求明确讲 `strict`、`allowed_tools` 等配置 | 参考中的具体细节被扩大为必须交付项；这些附加缺项不能直接作为原任务失败依据 |
| 结果校验覆盖 | 用户确实问“结果由谁校验”；答案写服务端符合 schema，却没有参考集已有的客户端结构校验 | 该缺项与用户目标相关，须独立审查生产覆盖判断和取证选择 |
| 声明范围 | 答案把 `you` 身份限制为所引句本身、不对整页作判断；报告用全页概括认定该限定为事实错误 | 局部断言是否错误和角色交付是否充分分别判断，现有归类尚不足成立 |

预算版本未改 Prompt、Schema 或参考资料；上述语义问题是实际报告暴露的独立边界，未把预算恢复的 shape 通过计作评分资格。既有普通稿件、来源判据及停用机制保持。

## 本轮候选设计与验证

原用户 goal 唯一拥有应交付事项；参考资料提供可核实依据。本轮候选 `research-answer-task-support-zh-v7-goal-grounded` 在共用评分入口验证后未取得资格，代码已[独立封存](../../.tmp/research-grader-qualification-20261001/candidate/evals/e2e_quality/research_answer_outcome.py)并撤回接入。候选缺项由 `ResearchRequirementGap` 提交用户原话 `requirement_quote` 与具体未交付内容 `missing_content`，读取边界确定性检查原话确实是当前请求的连续片段。模型负责判断缺失是否影响用户结果，资料中的配置、示例和建议依据实际目标使用。

候选参考集以五个官方页面的带坐标原文替换人工事实摘要，包含正式答案实际引用的两个新增页面。原文条件、主体和义务强度按快照保留，评分模型不读取生产通过结论。来源快照、摘录范围与原始执行归属由[资料溯源](../../.tmp/research-grader-qualification-20261001/fixture-provenance.json)拥有；它们只进入评测输入。

候选报告将明确事实矛盾、已核实引用支持缺陷与评分依据缺口分开。`evidence_gaps` 记录缺少的页面或原文范围；依据不足时聚合为 `inconclusive`，存在已确认用户缺项或错误时为 `failed`，完整满足且主要引用可确认时为 `passed`。E2E 消费者只接受 `passed`，同时记录三态原因，避免将依据不足归成已证实的产品错误。旧缺项字符串与摘要契约在所有受影响消费者一次替换，撤回也按同一边界恢复。

[本轮预声明](../../.tmp/research-grader-qualification-20261001/plan.json)固定原 goal、实际旧答案、模型、thinking 开启、32768 输出额度和生产预算。验证覆盖不含额外配置的完整正例、单删客户端校验/服务器访问控制、义务强度扩大或弱化、来源错配、评分缺页及句内限定；人工标签不进入模型请求。8 条控制各一次、旧真实答案一次；首个资格反例后停止新增样本，保留失败并重审责任。资格成立后只运行原显式验收请求正式 E2E 一次。两项候选输入同时变化的整体效果分别记录，不作单变量归因，不沿用旧任务 20/20。

## 本轮结果与下一责任边界

[实际结果](../../.tmp/research-grader-qualification-20261001/diagnostic/summary.json)执行 2/9，资格正确 1/2。完整正例没有 `strict/allowed_tools` 等配置细节，真实评分通过；旧完整答案被判 `failed`，核心缺项正确映射到客户端校验和服务器访问控制，但其报告的范围归类没有通过预声明审查。两次均一次 Provider 完成、无重试，已知总 44,770 tokens。

[旧答案报告](../../.tmp/research-grader-qualification-20261001/diagnostic/actual-sealed-answer.json)仍把“评分输入有整页”推成“作者引用片段覆盖整页”，据此对明确限定的取证范围判事实错误；它还为作者已保留未知的产品映射、未作肯定断言的后续校验条款列出 `evidence_gaps`。参考范围与作者实际取证范围被混用，输出契约的形状和原话绑定没有保证这一语义区分。核心缺项、实际引用错配与这些错误归类分别保留。

按本轮停止线，其余 7 条控制及 1 条新正式 E2E 未执行；未增加同向 Prompt 补丁、预算、重试或改标签。v7 未通过资格，3 个 eval 源码与 2 个 fixture 已[恢复到本轮开始前的逐字内容](../../.tmp/research-grader-qualification-20261001/rollback.json)，继承工作树修改保留，生产 src 字节保持。现行评分器仍为 v6，资格问题继续开放。下一准入需先明确独立评分只拥有外部内容支持判断，取证行为属于执行事实，未知边界与需要查证的肯定论断分别定位；以本次真实报告作为责任边界反例，再预声明新方案及验证身份。
