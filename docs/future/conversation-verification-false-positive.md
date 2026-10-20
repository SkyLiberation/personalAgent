# Conversation Draft 语义验证隔离设计

本页是[设计优化队列](design-optimization-backlog.md)中 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001` 的活动边界，只保存尚未闭环的决策、剩余门禁和退出条件。机制候选由[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)及对应问题记录拥有，最新正式结果由[评测文档](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)拥有。

## 1. 尚未解决的问题

**统一链的既定 v3 正式续验已完成用户交付并通过独立评分，本例关闭。** 其余已声明 S／F 统一阶段回放和正式缺失回答生命周期按原范围记录，不因未覆盖的泛化疑虑否定已通过用例。

本次真实报告还把“提交前自行核对”扩大为正文必须展示核对清单，归既有目标满足类别的 RV-01／RV-03 用例，单独待校准。后续只按该实际输入审查反馈边界，不新增类别或叠加复核；其他真实来源归属、列举范围及修订问题沿对应既定用例验收，原成绩和失败不改写。

## 2. 责任与保留条件

原始用户目标确定所需内容；模型选择信息需求、证据、正文和修订；执行系统拥有实际来源正文、坐标、URL 和失败事实。代码拥有版本、唯一编辑目标、可见引用与选中子集不变量。现行代码由同一研究模型生成 claims 与最终回答，唯一核验器检查来源支持、回答与 claims 的一致性及原目标覆盖；Completion 绑定同一完整版本和确切通过正文。正式结果与当前行为分别由评测文档和 ADR 拥有。

保留现行唯一研究路径、确定性来源投影和版本绑定；当前行为由 [ADR 0032](../adr/0032-conversation-research-claims.md)及[验证专题](../topics/verification-and-completion.md)拥有。`split_claim`、复合识别和独立文档缺项识别继续按 [ADR 0033](../adr/0033-claim-deletion-and-document-absence-pause.md)停用。删除动作的自然使用及语义覆盖仍按[单条撤回候选](../optimization/to_verify/claim-deletion.md)验收，不用本轮未触发结果代替。

[确定性坐标反馈](../optimization/completed/research-admission-coordinate-feedback.md)的局部缺陷已修复，不再列为待办；它不承担证据适合性或精确文本复制。既有[动作协议恢复](../optimization/completed/conversation-action-protocol-recovery.md)、[完整基稿交接](../optimization/completed/complete-rejected-draft-handoff.md)及[查询事实保真](../optimization/completed/query-execution-handoff.md)继续保留。保存误路由的独立边界由[准入审计](conversation-research-save-misroute.md)拥有。

## 3. 下一准入边界

### 研究、最终回答与单一核验

研究模型同时负责 claims 与最终回答，统一生产链已迁入。C1、G2 和原目标正式续验均已按既定条件通过，不追加稳定性采样；普通回答保持原路径。剩余类别回放、正式 N 生命周期及上述真实反馈误读按[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)记录，不用本例替代其证据，不恢复已删除的 Coverage、独立汇总或研究 Final。

### 最终修订与计量验收

[当前稿独立核验](../optimization/to_verify/final-revision-comparison.md)的 v6 已随统一方案替换，其真实拒稿与修订成果保持原身份，不再维护独立 Final 活动候选。[计量候选](../optimization/to_verify/research-selection-usage-commit.md)继续按完成响应、Journal 等式与恢复去重独立验收。

### 有范围的未知与正常交付

“规范明确没有此要求”是需要证据的外部断言；“依据本次所读片段无法确认”是有范围的认知限制。后者应允许与有据事实一起形成正常答案，由模型依据用户目标、线索与成本决定继续查找或停止。不能暗加每个问题必须有肯定答案的条件，也不能用切换 disposition 绕过原事实及用户结果契约。

当前仅对 `answer` 执行独立语义评分，`limitation` 仍计未交付。若需改变公开结果契约，须先单独声明正反例、原始失败及评分边界；本轮没有该变更。

### 来源支持与片段修订

[一次有界范围校准](../optimization/claim-verifier-consistency.md#2026-09-30-断言范围校准)已经执行，下一次来源变更须重新区分真实缺证、语境范围误读和生成稿范围扩张，不能继续叠加同义判据。相同输入通过与拒绝不自动裁定哪次正确；不得选择较早通过覆盖最新适用拒绝。按实际输入消费最新已完成判断与判决本身的准确性分别验收。

2026-10-18 的[定向删除验证](../ablation/claim-verifier.md#23-context-定向删除验证)及[输入归属／去重对照](../ablation/claim-verifier.md#25-输入归属与去重对照)均未修复新增海岸漏检，按预声明停止。[输入归属审计](../ablation/claim-verifier.md#24-持续漏检的输入归属审计)提供混用等线索，相同稿件的聚焦命中仍保留。2026-10-19 的[两步诊断](../ablation/claim-verifier.md#27-原文阅读隔离诊断)在可见组消费已指出具体疑点的笔记后命中，隔离组阅读不合格，未证明独立阅读或隔离收益，不准入多阶段生产。

[Issue 与根因复审](../ablation/claim-verifier.md#28-issue-检索与根因复审)核对了“已发现却按轻微细节忽略”和来源混用两条历史轨迹。其后的[来源支持判据候选验证](../ablation/claim-verifier.md#29-来源支持判据候选验证)仅改来源支持定义段，N3 仍漏检，按预声明失败早停，N1-final／H5 未执行。新规则已收到，但本次同轨未形成“海岸”具体限定的支持判断，不能归因为已发现后按轻微忽略。该候选不准入生产。

后续[最小 Context 与错误类型核对](../ablation/claim-verifier.md#210-最小-context-与错误类型核对)已按有界诊断结束：A 仅裁材料仍漏检，B 单稿来源任务识别了海岸限定缺证，目标反馈的 `citation_not_supported`、`a3` 定位及绑定原文均准确。该结果说明本次单稿来源任务可执行、现有类型足够；B 同时改变材料和任务，不能单独归因于 Prompt、删除 claim 或长度，也不是完整阶段修复。

[最简输入逐组加回](../ablation/claim-verifier.md#211-最简输入逐组加回)中，B0 命中、G1 首次漏检，但精确重复 G1 重新命中，随后精确重复 B0 仍命中。两次配对没有一致复现组级退化，按预声明以 `boundary_not_reproduced` 结束，G2 至 G5 及半组未执行。因此不能把漏检归到 G1 的原会话、冻结要求或身份材料，也未排除该组影响漏检概率；本轮未触及 claim 加回组，不能据此判断 claim 无影响。后续[中性追问](../ablation/claim-verifier.md#212-同输入异判的中性追问)已完成两条轨迹各一次，补充了可核查的材料与报告说明；首次对象现在承认海岸限定未单独覆盖，仍未解释原同输入异判的原因。“目标未参与”是事后自述，不作背景无影响的证据。按用户要求补做的[定向类别追问](../ablation/claim-verifier.md#213-直接追问未分类原因)仍未取得原漏检原因，模型明确表示无法从材料确认；不把当前追问提示混作旧请求。当前仍无新生产候选，不准入新阶段或类型；后续责任边界由[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#当前优化取舍)拥有。有限重复不计稳定率，同义 Prompt、claim 拆分、新字段或新增阶段不自动启动，既有局部通过与原任务关闭保持。

局部修订的已有引用交接由[引用继承完成记录](../optimization/completed/claim-retained-references.md)拥有。来源语义的进一步校准先按[完整实发输入审查](../optimization/claim-verifier-consistency.md#2026-10-01-修订修复后的判决边界审查)区分主体歧义、模态扩大、有效推导与上下文义务强度，固定清晰相邻对照后再进入连续验证。保留 thinking、原模型参数及原始推理。来源报告复用由[固化记录](../optimization/completed/claim-source-review-reuse.md)拥有；[支持范围修订](../optimization/to_verify/claim-supported-scope-repair.md)已真实消费反馈，但仍有范围扩大及正文新增事实未绑定新引用的失败，下一设计聚焦同一修订提交的引用绑定。最终验收项身份由[引用恢复完成记录](../optimization/completed/final-criterion-transcription.md)拥有；保留原评分标准和 thinking。

实际同 SDK 输入还出现有效报告与输出额度耗尽的结构差异。下一验证分别计语义判决、报告可完成性及全部已完成响应的成本；原始空正文没有判决，不计为来源拒绝或通过。

正文目标方案由[Runtime 片段寻址完成记录](../optimization/completed/claim-fragment-addressing.md)拥有；`CLAIM-EDIT-TARGET-TRANSCRIPTION-001` 的事实、契约及决定性证据只维护在该记录中。[片段有界修订](../optimization/to_verify/claim-fragment-revision.md)独立验收编辑范围与内容语义，来源一致性及完整用户结果继续作为本上位问题的准入边界。

正式验证仍须从中文自然任务、空资料和生产入口连续消费真实选证、生成、核验、修订与交付，不注入理想稿或挑选通过版本。未到达阶段单列，调用、tokens、耗时与用户结果分开计分，不从独立随机轨迹宣称成本收益。

[跨任务分类与反馈结构审查](../ablation/feedback-output-schema.md)保留当前八类四字段：它们能表达并被实际消费，尚未证明分类数量最优或检查完整。当前准入按[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#分类方法与反馈结构复审)区分漏项、类别、反馈质量与修订；外部结构重试不作为语义恢复依据。2026-10-20 的[字段顺序诊断](../ablation/feedback-output-schema.md#7-字段顺序敏感性诊断)中两臂均未报海岸，已按计划停止。B1 借用未绑定 d3:129 是[旧归属问题](../ablation/claim-verifier.md#24-持续漏检的输入归属审计)复现，不另立问题或重置累计尝试。后续[片段加入诊断](../ablation/feedback-output-schema.md#8-未绑定原文片段的加入诊断)中声景缺证由 P1 报告变为 U1 未报，U1 又将数据字典有训练划分错判为测试数据不独立的明确反证，因范围违规停止，未完成反向配对；海岸两臂均命中，不支持将该片段认定为海岸根因。当前两项诊断均已结束，没有新生产候选；下一方案须有具体限定覆盖、材料归属和同一关系反证的依据，不自动追加类型、过程字段、输入裁剪或阶段，先前通过范围保持。

## 4. 停止与退出

用户于 2026-10-20 要求的[固定输入重复计划](../optimization/to_verify/research-goal-coverage.md#同输入判决波动的扩展采样)已完成：B0／G1 各十次，准确可用海岸反馈均3/10；B0另三次输出定位失败。它只测同一材料的判决频率，Schema沿用全稿枚举也是既定诊断条件，不代表生产整稿准确率。两组频率相同不能证明背景无影响，最简也漏则说明背景不是漏报必要条件。该测量已结束，不恢复旧输入改法，不追加已通过用例门槛；本轮没有新生产候选，后续方案分别取得具体关系漏报和输出定位失败的依据。后续[逐轨审计](../ablation/claim-verifier.md#218-海岸漏报的逐轨判断审计)将 G1 七次漏报区分为六次整体接受名称／地点和一次发现缺证后放过；两条路径都须保护，不能只增加错误类型或归因于旧细节豁免语句。用户要求的[临时 reason 诊断](../ablation/claim-verifier.md#219-临时-reason-输出诊断)已完成十次，准确可用反馈4/10；四次原生漏报理由省略海岸、用国家名概括有据，不能证明完整限定已检查或较历史3/10改善。该临时实验已停止，不属生产候选；下一方案须保护被核对文字的完整含义，不依靠简化复述或理由自述证明覆盖。用户随后要求的[整体中文语言对照](../ablation/claim-verifier.md#220-整体中文翻译的语言对照)已完成各十次交错采样，海岸四项完整反馈混合4/10、中文7/10。按渐进核验契约回查，至少一处真实且定位正确的问题为混合6/10、中文10/10；中文两次未报海岸仍有其他真实反馈，不是整轮失败。引用完整性与单点覆盖另计；混合组的空报告及非法定位仍是实际反馈问题，不能全部归为英文理解失败。实验已结束，原 REA 停止与原始成绩身份保持，不据此扩大生产阶段。

此前[中文单类二元诊断](../ablation/claim-verifier.md#221-中文单类二元输出诊断)错误禁止 true 分支基础反馈，纯布尔方案已撤回。后续[恢复反馈与验收复核](../ablation/claim-verifier.md#222-中文单类核验恢复基础反馈与验收复核)已完成：本轮10/10至少给出一处真实且定位正确的错误反馈，海岸四项完整8/10。F02／F05 报告其他真实缺证，按已有渐进核验契约不是整轮失败。语言历史同口径为混合6/10、中文10/10，旧4/10与7/10只代表海岸四项，不再概括为整体成功率。引用完整性、其他反馈未决与最终错误放行另计；已有逐轮修订能力保持，不要求单轮穷举。实验及基础反馈恢复验证结束，原请求和冻结v1保持，生产本就有四字段，本轮没有研究模型实际修订或新生产候选。

保持原模型、思考模式、预算及独立用户评分，不扩大昂贵矩阵或重复无增益 E2E。相同边界一次有界修正后仍失败时，停止对应方向局部补丁，按 EVD 重审责任、输入与最小边界，并及时检索同类优秀实践；恢复确定性反馈契约依据工程失败和反事实，不用外部资料替代。

后续候选仅在具备责任边界依据和预声明后进入实现。已撤回的整体 Context、固定搜索流程或孤立同义提示不恢复为并行路径；已成立局部机制也不因独立下游失败被撤销。当前决定由 [ADR 0032](../adr/0032-conversation-research-claims.md#2026-10-16-当前决定)拥有；既定用例达到条件即关闭，新真实失败再按对应问题重新打开。其他未执行边界与完整发布矩阵不得写成通过。

评分输出预算机制见[固化记录](../optimization/completed/research-grader-output-budget.md)，评分资格契约见[固化记录](../optimization/completed/research-grader-qualification.md)，运行步骤见[评测执行](../evals/04-running-and-release.md#研究评分器输出额度)。工具内部模型用量交接由[独立问题](../optimization/tool-model-usage-handoff.md)拥有，成本不得只报直接调用总账。
