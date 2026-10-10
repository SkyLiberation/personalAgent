# 研究回答来源支持：问题总览与经验索引

**当前推进需要区分来源支持、用户事实覆盖和最终表达保真。** 三者的局部通过不能相互替代，也不能覆盖原用户结果。近期失败集中在[具体来源归属](normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配)、[修订扩大列举范围](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)及[选证输出截断](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)。本轮按[当前稿独立核验的预声明](claim-revision-nonconvergence.md#2026-10-08-当前稿独立核验的预声明)先执行隔离校准。

本文提供跨问题导航，不维护第二份准入或结果台账。当前行为由[验证专题](../topics/verification-and-completion.md)、[ADR 0032](../adr/0032-conversation-research-claims.md)和 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)拥有；准入由 [Future 队列](../future/design-optimization-backlog.md)拥有，原始用户结果由[评测盘点](../evals/02-current-case-inventory.md)拥有。拆分、复合识别及独立文档缺项识别已停用，历史局部收益按原条件保留。

## 当前核心问题与责任边界

先定位责任边界，再决定验证范围。执行系统提供原文、坐标与执行事实；模型提出论断和修订；来源 Verifier 判断依据能否支持具体声明，研究覆盖判断事实能否回答用户问题，最终 Verifier 判断实际成稿，Completion Gate 绑定同一通过稿。

| 问题边界 | 记录与候选入口 |
| --- | --- |
| 修正出处时把部分列举改成完整清单 | [实际连续修订反例](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举)、[当前稿独立核验候选](to_verify/final-revision-comparison.md) |
| 具体步骤被归到另一个来源页面 | [来源归属问题](normative-scope-attribution.md)、[来源归属候选](to_verify/answer-source-attribution.md) |
| 相关事实没有回答用户所问对象 | [对象与适用范围](answer-object-mismatch.md)、[事实覆盖候选](to_verify/research-goal-coverage.md) |
| 同一请求得到冲突判断 | [核验一致性与实际请求审计](claim-verifier-consistency.md) |
| 缺证反馈后扩大主体、条件或义务强度 | [支持范围修订](to_verify/claim-supported-scope-repair.md)、[研究修订总问题](claim-revision-nonconvergence.md) |
| 局部观察被写成全文缺项 | [历史缺项问题](document-absence.md)、[停用后的保护边界](to_verify/document-absence-pause.md) |
| 原文行号与临时引用编号混用 | [引用坐标问题](citation-coordinate-confusion.md) |
| 引用原文没有可核对的来源信息 | [来源绑定问题及剩余验收](citation-source-attribution.md) |
| 后置失败遮蔽已完成模型成本 | [选证及时提交](research-selection-usage-commit.md)、[工具内部用量交接](tool-model-usage-handoff.md) |
| 选证截断使后续阶段未到达 | [正式失败](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)、[默认额度候选](to_verify/research-provider-output-default.md) |
| 拒稿后的取证、计划恢复和自主补证 | [反馈与修订](revision-feedback-loop.md)、[取证](evidence-acquisition.md) |

### 缺项问题的状态更正

独立缺项识别与读取覆盖门禁的历史有效边界见[职责分离](document-absence.md#83-文档缺项识别与普通支持验证的职责分离)、[真实读取消费](document-absence.md#85-覆盖门禁接入真实读取事实与生产工具)及[分类交接修复](document-absence.md#104-按来源顺序返回缺项分类)。这些局部证据保留，完整任务失败也保留；当前停用决定由 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)拥有，历史方案的“继续保留门禁”不再作为今天的实施指令。

[原文核查](document-absence.md#109-原文缺项核查与扩源反馈的边界验证)已更正“已保存来源存在被漏读答案”的旧解释。未取得证据时，模型可以扩源或说明本次取证限制；是否满足任务另由事实覆盖和最终交付判断。没有保存核验入参的历史运行只报告实际到达阶段，不推断缺项分支是否触发。

### 评测与成本的独立阻塞

正式结果、有效独立评分和已完成模型成本分别记录。无有效评分不代表答案通过；已确认的来源错误也不因评分结构失败而消失。局部通过、前置截断、服务超时和未交付按阶段归因，见[评测盘点](../evals/02-current-case-inventory.md)、[Provider 诊断](to_verify/model-provider-diagnostics.md)与[用量交接](tool-model-usage-handoff.md)。

## 核验点、反馈与能力用例映射

**核验点决定判断哪种语义关系，反馈字段解释同一个发现，正式轨迹用例覆盖对应能力。** 来源报告的 `unsupported_assertion`、`supported_scope`、`missing_premise` 分别说明实际断言、证据支持范围及缺口或冲突；它们不是三个任务。具体问题、资料、角色及答案来自正式输入，Prompt 只表达通用职责。所有新增用例保留完整阶段输入，不改写、裁剪、补证或注入理想反馈，执行 [QLT 真实轨迹规则](../devSpec/quality-security.md#12-通用核验点与真实轨迹用例)。

证据充分性检查决策前提是否齐备，规范性质一致性比较有明确依据的性质归属，两项能力分别计分。缺证反馈只能说明当前依据不足，不能证明规范性质比较正确。N1 原预声明将两者合并；现按实际能力解释，原始分数和封存记录保持原身份。反馈对实际断言的忠实解释是共同验收点，不因反馈提到某种性质就自动归为该性质比较失败。

这些类别由同一来源核验决策处理，不对应多个调用或独立路由。生产来源报告已有定位及三个解释字段，尚无类别字段。直接分类候选已移除额外维度、关系及通过项输出，原六项[封存成绩](to_verify/normative-context-acquisition.md#六项直接分类的最终结果)为完整资格 4/6，保持原身份。[A6 标签审定](to_verify/normative-context-acquisition.md#标签审定与实际断言忠实性的最小修正)确认原稿一般名称不能扩成具体字段身份，修正判据下只读复核旧响应为 5/6；A2 说明增加排他关系仍失败。本轮 Source v7 只收敛实际断言及必要缺证报告口径，沿原完整六项各一次验证，额外字段不恢复，候选未迁生产。类别正确率不覆盖遗漏，推理提及问题不替代实际通过。

下表是现有职责与真实样本的唯一映射导航，不声明所有能力已通过。`M` 表示已封存正式中文 HTTP 运行 `irun_d46adae369924211`；数字是该运行 `product-model-calls/24340/` 的物理 SDK 请求编号。原始输入及同轨迹修订可以回放，回放属于 Offline Eval；原报告按原版本保留，新单点结果独立登记。没有资格充分的正反样本时，明确记为覆盖缺口，后续经正式入口取得。

| 通用核验点与责任 | 对应能力及反馈 | 正式输入后的真实样本 | 当前边界 |
| --- | --- | --- | --- |
| 来源支持：证据充分性 | 判断实际承诺所需主体、对象身份、条件、范围或性质前提是否进入当前输入；保真一般命名不新增具体身份 | M `0049`、`0058` 的完整原输入及 N1、K1、A2／A6 真实回放及 v6 多项提示诊断 | 旧成绩保留，不计性质一致性通过；A6 按旧双缺口判据为 1/2，新审定只要求回传缺证及一般命名合法出口。明确对象身份的缺证负例仍待真实轨迹覆盖，本轮不编造 |
| 来源支持：主体与关系 | 核对实际主体及动作关系，不从另一项职责推出未给出的关系 | M `0018` 协作闭环缺证及同轨迹 `0039` 修订 | 原反馈与修订可回放；缺证只覆盖充分性，主体关系正误须按前提充分的实际输入另验，本轮不重采样 |
| 来源支持：条件与范围 | 保持条件、量词、局部与完整范围，反馈指明实际扩张 | 正式枚举失败见[实际流程修订](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举) | 对应完整模型入参仍须逐项核对资格；未计本轮覆盖 |
| 来源支持：具体出处 | 内容有据与被指定文档或章节支持分别判断 | M `0041` 章节归因缺证及 `0047` 真实修订；明确页面错配见[正式来源失败](normative-scope-attribution.md#2026-10-02-实际流程步骤的来源错配) | 缺证计充分性，明确出处错配另验；出处与规范性质分别计点，已有样本不代表新候选通过 |
| 来源支持：规范性质一致性 | 在性质依据充分且原稿断言明确时，比较规范性条款、非规范性指导等归属是否一致 | M `0064` 真实修订；`0047` 为含混及缺前提边界；详见[原单点诊断](to_verify/normative-context-acquisition.md#2026-10-09-单独核验规范性质的诊断预声明) | N1 缺前提，不计本点通过或已确认漏判；N2 至 N4 未调用，完整正式性质冲突样本仍缺失 |
| 来源支持：义务强度 | 区分必须、推荐、允许与可能，保留条件，不把“应”夸大为“必须” | M `0064` 的真实 MUST／SHOULD 条款 | 已有合法真实稿；清晰强度错配负例待正式轨迹登记，历史人工负例不计覆盖 |
| 来源支持：否定与认知限制 | 区分当前片段未写与全文不存在，缺证不能被反馈写成否定事实 | M `0027`／`0033` 局部否定范围反馈与 `0039` 修订；`0066`／`0074` 真实限制修订 | 同轨迹原输入及反馈保留，独立缺项流程仍停用 |
| Coverage：用户事实覆盖 | 对冻结原项判断事实是否回答所问关系，反馈说明用户必要缺口 | [正式覆盖消费](to_verify/research-goal-coverage.md#2026-10-02-引用身份修复后的覆盖消费) | 原项及完整真实输入单独验收，不混入来源性质判断 |
| Final：当前稿忠实性与交付 | 保持已核验事实、范围、出处及完整交付；历史修复反馈由修订者消费 | M [真实拒稿、修订及接受](../../.tmp/research-selection-state-target-20261008/final-division-checkpoint.json) | v6 原机制检查点成立，完整用户结果保持原失败 |
| 核验反馈：实际断言及依据忠实性 | 分类和说明只解释稿件实际断言及真实依据，不追加性质或强度前提，也不从一个维度证明另一个维度 | M `0049`／`0047`／`0058` 完整原稿及 N1、K1、L1／L3／L5 实际反馈；真实续修完整 c2 及当前直接分类完整六项 | 旧成绩及额外维度反例均保留。当前 A2 缺证类别正确但说明将实践建议排斥为非协议要求，另两项非空说明忠实，忠实性 2/3。不归为已确认稿件性质冲突，也不把已输出类别正确当作说明或无漏检通过 |

每次未识别、误拒或反馈失真先绑定上述核验点及实际阶段。没有对应点时，在其既有责任主体内补充通用判据、边界和同轨迹完整用例，禁止按任务名称或答案关键词加例外。输入缺证、歧义和服务故障按真实依据归因，不自动算语义漏放。唯一设计预声明调用、标签、预算及停止条件，实际结果由[评测盘点](../evals/02-current-case-inventory.md)拥有；矩阵不自动新增生产阶段或字段。

## 必须保留的经验

有效机制在后续验证中继续保留，独立下游失败不重开已解决问题。已固化机制只引用唯一完成文档，不在本页重述状态、结果或待办。

| 查阅目的 | 唯一记录 |
| --- | --- |
| 真实反馈逐轮修订与同稿绑定 | [多错误渐进修订](completed/multi-error-verification-revision.md) |
| 被拒稿的完整文字和引用交接 | [完整基稿](completed/complete-rejected-draft-handoff.md) |
| 引句、验收项和编辑目标的身份恢复 | [调用单元](completed/verifier-finding-binding.md)、[验收项引用](completed/final-criterion-transcription.md)、[片段寻址](completed/claim-fragment-addressing.md) |
| 已完成报告按实际输入消费 | [来源报告复用](completed/claim-source-review-reuse.md) |
| 引用继承与坐标反馈 | [引用继承](completed/claim-retained-references.md)、[坐标反馈](completed/research-admission-coordinate-feedback.md) |
| 动作与独立评分恢复 | [动作协议](completed/conversation-action-protocol-recovery.md)、[评分资格](completed/research-grader-qualification.md)、[评分额度](completed/research-grader-output-budget.md) |

## 已尝试的方法与未证实假设

历史尝试集中在具体问题内。提示、输入聚焦、职责分离或预算调整只在其实际输入与判据范围内成立，不作为所有语义误判的总解释。

| 尝试或待区分假设 | 原始问题与证据入口 |
| --- | --- |
| 显式禁令、反问、示例与推导判断 | [权限责任推断](permission-inference.md) |
| 摘要、全文标志与缺项分类 | [文档缺项](document-absence.md) |
| Context 裁剪、单句与完整稿、两侧聚焦 | [对象错位](answer-object-mismatch.md) |
| 先取证再写作、扩源及主动停止 | [取证](evidence-acquisition.md)、[选证候选](to_verify/claim-evidence-selection.md) |
| 片段保护与真实反馈消费 | [片段有界修订](to_verify/claim-fragment-revision.md)、[修订总问题](claim-revision-nonconvergence.md) |
| 正文提取、思考传递和输出截断 | [提取](source-extraction.md)、[思考](thinking-context-transport.md)、[截断](verifier-output-truncation.md) |

## 阅读顺序与完整记录

历史编号用于反查，日期对应当轮代码和证据身份。旧复合坐标、旧引用复制协议及已撤回候选不作为当前生产反例；停止理由保留在原问题中。

| 要查的问题 | 完整记录 |
| --- | --- |
| 近期研究、来源、汇总和最终核验的关系 | [研究修订总问题](claim-revision-nonconvergence.md)、[候选索引](to_verify/README.md) |
| 局部观察被写成全文缺项 | [文档缺项](document-absence.md)；历史编号 3、4、6、8、9、30、31、32、67、69、78、81 至 85、104、105、109 |
| 对象与依据范围错位 | [对象错位](answer-object-mismatch.md)；历史编号 57 至 66、75、86 至 101、114 |
| 执行职责被推成权限责任 | [权限推断](permission-inference.md)；原文保留对应历史编号 |
| 自主补证及拒稿后的恢复 | [取证](evidence-acquisition.md)、[反馈修订](revision-feedback-loop.md) |
| 整稿验收的来源支持职责 | [来源支持](verification-source-support.md)；历史编号 47 至 49、55、56 |
| 动作阶段输出与结构恢复 | [动作协议问题](action-final-protocol.md)、[完成记录](completed/conversation-action-protocol-recovery.md) |
| 正文提取、思考配置和核验额度 | [提取](source-extraction.md)、[思考](thinking-context-transport.md)、[截断](verifier-output-truncation.md) |
| 面试经验讲述 | [开发踩坑与优化经验](../interview/10-development-pitfalls.md)；证据继续由具体问题拥有 |

## 后续推进与接入规则

新尝试写入同一具体问题，总览只维护导航。未充分证明的机制由 `to_verify/` 保留，已解决机制按 [completed 规则](README.md#已解决问题的固化规则)收敛；Future 维护准入，正式评测维护原始用户结果。

先审查实际请求，在条件局部回放中消费同一轨迹的实际反馈和实际输出；人工相邻控制只校准判断边界，不能拼接成产品成功。核验符合预声明后再扩大至连续修订和正式 E2E。完整读取、工具可用、模型理由、合法动作与一次放行均不能替代用户结果。
