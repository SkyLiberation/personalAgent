# 机制消融

本目录保存隔离消融的规格、结果和适用边界；当前产品契约仍由[核验专题](../topics/verification-and-completion.md)等权威正文拥有。实验使用正式入口轨迹及新增真实采样的完整阶段输入，回放结果按 Offline Eval 解释；公开题库、人工诊断和产品结果分别记录。

| 实验 | 目标与状态 |
| --- | --- |
| [额外 claim 对核验器的作用](claim-verifier.md) | 11个主配对、4个聚焦配对与1次中立核对已执行；[评估指标](claim-verifier.md#21-具体评估指标)区分收益与负担，[机制诊断](claim-verifier.md#22-机制诊断与因果边界)定位重复输入、额外对齐及判据取舍 |
| [指标快照](claim-verifier-metrics.json) | `claim-verifier-metrics:v1` 对既有归档的只读重算；保留局部关系分母及未测原因 |
| [完整 AI 初审](claim-complete-review-20261020.md)、[逐行数据](claim-complete-review-20261020.json) | 覆盖 11 份输入、22 份报告、23 条反馈；事后答案问题分母下完整组 10/25、移除组 8/25，含版本重复。非盲、未独立人工复核；旧成绩保持，该次初审零新增被测模型调用，不测实际修复与用户结果 |
| [N2 恢复预检](claim-n2-continuation-preflight-20261020.md)、[结果数据](claim-n2-continuation-preflight-20261020.json) | 首稿完整输入、实际 writer 准入和原选证请求可还原；140 个来源文件及 262 个源码身份核对通过。预检当时零新增模型调用，续跑器及 A4／A5 尚未执行；后续真实续跑另列 |
| [N2 条件续跑](claim-n2-continuation-20261021.md)、[结果数据](claim-n2-continuation-20261021.json) | 两臂各续跑一次并交付；完整组消除初始问题 3/4、移除组 2/4，但完整组新增一项支持缺口，两组终稿均仍缺证。23 次物理调用、1,236,604 tokens，完整组新增 tokens 高 74.9%；非盲 AI 初审、未独立人工复核，未证明净收益，A5 未执行 |
| [claim 价值复核](claim-verifier.md#223-claim-收益价值复核)、[派生数据](claim-value-analysis-20261021.json) | 零新增模型调用：增量发现集中 N2，费用差额约 61% 来自后续路径；定位到局部修订后未处理反馈退出模型输入。研究资源纠错与用户收益分开，现有移除组未检验整个 claim 工作表示的必要性 |
| [历史反馈交接续验](claim-verifier.md#224-历史反馈交接的真实续验)、[结果数据](claim-feedback-handoff-20261021.json) | 历史实际进入选证与 writer，区域排序在新核验前修复；转载归属仍漏修。基线内容过滤中断，独立候选第 8 版因下一核验预留不足停止，均未交付。34 次派发、已知 1,769,824 tokens，另 1 次未知；不构成完整配对或净收益证据，无生产改动 |
| [固定基线计划](claim-verifier-baseline.plan.json) | 冻结 `v1`、源校验和、主配对和任务映射；[正式离线重算命令](../evals/04-running-and-release.md#claim-指标持续评估)输出独立归档 |
| [Context 定向删除结果](claim-verifier.md#23-context-定向删除验证)、[结果数据](claim-context-deletion-results.json) | 两组目标识别均 0/1，2 次模型调用、110,298 tokens；候选停止，N2 两次调用按预声明未执行。[输入归属审计](claim-verifier.md#24-持续漏检的输入归属审计)另发现稿件与证据混用，未新增模型调用或生产改动 |
| [输入归属与去重对照](claim-verifier.md#25-输入归属与去重对照)、[结果数据](claim-input-provenance-results.json) | 标清字段归属与仅去重均未识别海岸，各 0/1；2 次调用、126,595 tokens，N2 两次按计划未执行，不接入生产 |
| [外部同类问题检索](claim-verifier.md#26-外部同类问题检索) | 2026-10-19 核对 CoVe、Decomposition Dilemmas、FaithBench、FaithJudge 四篇原始论文；区分相近失败、方法差异与未验证因果，零新增模型调用 |
| [原文阅读隔离诊断](claim-verifier.md#27-原文阅读隔离诊断)、[结果数据](claim-source-reading-isolation-results.json) | 可见组先读后核验识别海岸 1/1、合法关系误报 0/3；隔离组阅读不合格，停止后续比较。3 次调用、93,270 tokens，未证明隔离独立收益，不接入生产 |
| [Issue 检索与根因复审](claim-verifier.md#28-issue-检索与根因复审) | 重查同轨“已发现却忽略”和来源混用，核对 TruLens、DeepEval、Ragas 五项公开 issue；形成来源支持判据候选，后续验证另列 |
| [来源支持判据候选验证](claim-verifier.md#29-来源支持判据候选验证)、[结果数据](claim-source-support-boundary-results.json) | 仅改来源支持定义段，N3 海岸识别 0/1、合法关系误报 0/3；1 次调用、64,979 tokens、142.34 秒。按预声明失败早停，N1-final／H5 未执行；需重审具体限定如何进入判断，不准入生产 |
| [最小 Context 与错误类型核对](claim-verifier.md#210-最小-context-与错误类型核对)、[结果数据](claim-minimal-context-results.json) | 海岸目标在 A 仅裁材料组为 0/1，在 B 单稿来源任务组为 1/1，目标反馈沿用现有类型。2 次调用、27,854 tokens、91.903 秒。B 同时改变材料和任务，只作隔离观察，不证明完整阶段修复或单一变量收益，不准入新生产阶段或类型 |
| [最简输入逐组加回](claim-verifier.md#211-最简输入逐组加回)、[结果数据](claim-context-addback-results.json) | B0 命中，G1 首次漏检，但 G1 精确重复重新命中，随后 B0 重复仍命中；配对未一致复现组级退化，按预声明终止。4 次逻辑／物理调用、40,206 tokens、231.230 秒；G2 至 G5 及半组未执行，不据此估计稳定率或判定原目标、claim 的独立影响 |
| [同输入异判的中性追问](claim-verifier.md#212-同输入异判的中性追问)、[结果数据](claim-context-neutral-results.json) | 两条历史轨迹各问一次，均能说明海岸支持缺口；首次对象承认旧报告未单独覆盖，后次解释与旧报告一致。未得到原背景影响或同输入差异的可验证因果。2次调用、20,022 tokens、48.276秒，事后解释不计核验修复或成功率 |
| [直接追问未分类原因](claim-verifier.md#213-直接追问未分类原因)、[结果数据](claim-context-direct-question-results.json) | 用户明确要求点出海岸及citation_not_supported，原G1只问一次；模型表示无法确认当时未报告原因，未取得新根因证据。1次调用、10,130 tokens、25.406秒，事后定向解释不计原判断因果或生产修复 |
| [分类错误处理与反馈输出结构审查](feedback-output-schema.md) | 跨文本分类、路由、信息抽取等任务检索，固定核对两套独立工程实现与本地生产消费链。八类四字段可表达海岸问题，无法单靠结构证明检查完整；区分漏项、错类、反馈质量和修订，零新增项目模型调用及生产改动 |
| [字段顺序敏感性诊断](feedback-output-schema.md#7-字段顺序敏感性诊断)、[结果数据](feedback-field-order-results.json) | 完整真实输入保持，只将 category 呈现移到末位；A1／B1 海岸均未报，各 0/1，合法控制均误拒 0/3；B1 空报告，原生键序不可观察，按预声明停止，B2／A2 未执行。两次调用、126,755 tokens、152.642 秒，无生产改动 |
| [未绑定原文片段的加入诊断](feedback-output-schema.md#8-未绑定原文片段的加入诊断)、[结果数据](citation-boundary-probe-results.json) | 同一原 a3 与 49 条绑定，仅改变额外真实片段可见性。P1 报告声景缺证，U1 未报且出现无效明确反证反馈；海岸两臂均命中，合法关系均误拒 0/2。按范围违规停止，反向未执行；2 次调用、21,551 tokens、131.156 秒。属于旧归属问题的再次复现，无生产改动 |
| [固定输入的二十次重复](claim-verifier.md#217-固定输入的二十次重复)、[结果数据](verifier-repeatability-results.json) | B0／G1 各十次，准确可用海岸反馈均3/10；B0另四次漏报、三次定位失败，G1另七次漏报。旧四次加回不并入；本轮20物理、196,956 tokens、961.957秒，零重试。保留首批停止与只执行剩余16次的控制器修正，不代表生产整稿准确率或claim收益，无生产改动 |
| [海岸逐轨审计](claim-verifier.md#218-海岸漏报的逐轨判断审计) | G1 十份有效报告：六次整体接受名称／地点、一次发现缺证仍放过、三次独立核对后命中。只读核对 297 个归档文件，零新增模型调用；不把所有漏报归于同一取舍 |
| [临时 reason 输出](claim-verifier.md#219-临时-reason-输出诊断)、[结果数据](coast-reason-probe-results.json) | 十次准确可用海岸反馈4/10，另三次有效漏报、一次引用缺失、两次定位无效；四次原生漏报的理由都省略海岸，再宣称名称有据。106,067 tokens、643.355秒，零重试，临时实验结束；不证明较历史3/10改善，不改生产 |
| [整体中文语言对照](claim-verifier.md#220-整体中文翻译的语言对照)、[结果数据](coast-language-probe-results.json) | 海岸四项完整反馈混合4/10、中文7/10；按逐轮契约复核，至少一处真实且定位正确的问题为混合6/10、中文10/10。中文未报海岸的两次也有其他真实反馈，不算整轮失败；引用完整性另计。二十物理、214,229 tokens、1,254.222秒，实验结束，无生产改动 |
| [中文单类二元输出](claim-verifier.md#221-中文单类二元输出诊断)、[结果数据](coast-binary-probe-results.json) | true 分支误删基础反馈，方案已撤回；十次纯布尔只保留二元记录，不能计海岸反馈通过。同轨四次明确海岸缺证、六次仍整体接受地点或省略限定。91,144 tokens、298.155秒，实验结束，无生产改动 |
| [单类恢复基础反馈与验收复核](claim-verifier.md#222-中文单类核验恢复基础反馈与验收复核)、[本轮结果](coast-feedback-probe-results.json)、[口径复核](verifier-feedback-acceptance-review.json) | 本轮10/10至少报告一处真实且定位正确的问题，海岸8/10仅作单点覆盖。回查语言组同口径混合6/10、中文10/10；未报海岸而报其他真实问题不算整轮失败，引用完整性另计。本轮十物理、100,967 tokens、417.033秒，复核零新增调用，无生产改动 |
| [研究任务来源与采样](research-tasks.md) | 四个公开题库、保留321道问题、17个具体场景；本次三个采样任务及中文改编 |
| [可复查汇总数据](claim-verifier-data.json) | 模型报告、逐点裁判、用量与身份校验；90次物理调用，已知4,006,802 tokens，另2次用量未知 |
