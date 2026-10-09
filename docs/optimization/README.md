# 优化推进记录

**本目录与 Future 联动，按问题维护优化：进行中保留必要诊断，已解决则固化结论并移除中间流水。** 记录必须足以回答尝试过什么、在哪些条件下有效、为什么停止，以及下一轮必须保留什么。不能只留会话摘要或仓库外报告链接，也不按每次会话新建一份分散记录。

## 目录分工与入口

本目录拥有优化推进过程；[Future 队列](../future/design-optimization-backlog.md)唯一拥有问题准入状态，Future 专题拥有产品活动设计；尚未充分证明的机制候选正文由 [`to_verify/`](to_verify/README.md)按具体问题拥有，Future 只链接候选及其准入条件。正式用例结果与发布资格由[评测文档](../evals/02-current-case-inventory.md)拥有，当前生产行为由对应专题或摘要文档拥有。原始请求、响应、代码身份和校验和继续独立封存，不把大体积日志、密钥或私人数据复制进本目录。

每项优化开始前，按 [EVD 的 docs-first 与 e2e-first 流程](../devSpec/change-evidence.md#7-强制开发与设计流程)在对应活动设计中明确问题和可执行验收；进行中同步修订该正文，不以过程记录或事后总结替代先行设计。

测试存放位置遵守[评测归档规则](../../evals/AGENTS.md#5-比较身份与归档)：后续临时脚本和测试产物统一放在项目根目录 `.tmp/<专题>-<日期>/`，不再向 `C:/pae` 写入。本文档保存可复用经验及真实证据坐标；历史证据未迁移时保留原引用，不能批量替换路径制造失效链接。

| 问题编号与范围 | 推进记录 | 活动设计 |
| --- | --- | --- |
| `CONVERSATION-RESEARCH-STOP-001`：来源支持修正及其取证前置条件 | [问题总览与经验索引](conversation-source-support.md)、[正文搜索读取第 103 节](evidence-acquisition.md#103-正文行坐标统一与预编号引用联动) | [来源语义与修订设计](../future/conversation-verification-false-positive.md) |
| `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`：验证漏放与循环修订 | [对象错位](answer-object-mismatch.md)、[文档缺项](document-absence.md)、[反馈修订](revision-feedback-loop.md)、[研究论断无法收敛及子问题](claim-revision-nonconvergence.md)、[按问题关联的待验证方案](to_verify/README.md)、[阶段动作选择](claim-action-selection.md)、[相同输入核验不一致](claim-verifier-consistency.md) | [Verifier 设计](../future/conversation-verification-false-positive.md) |
| `CITATION-COORDINATE-CONFUSION-001`：原文行号与临时引用编号混用 | [失败事实与记录](citation-coordinate-confusion.md) | [统一文档坐标与后续观察条件](../future/citation-coordinate-identity.md) |
| `ANSWER-NORMATIVE-SCOPE-001`：规范主体、来源与义务强度对应 | [独立问题与反馈验收边界](normative-scope-attribution.md) | [最终稿具体来源归属候选](to_verify/answer-source-attribution.md)、[重复失败后的方案复审](to_verify/normative-context-acquisition.md)；准入由 [Future 队列](../future/design-optimization-backlog.md)拥有 |
| `ANSWER-ENUMERATION-SCOPE-001`：真实反馈修订扩大列举范围 | [实际修订反例](claim-revision-nonconvergence.md#2026-10-02-汇总将部分列举改为完整枚举) | [当前稿独立核验候选](to_verify/final-revision-comparison.md) |
| `MODEL-PROVIDER-TRANSPORT-001`：服务传输与 deadline 阻断核验 | [独立服务阻塞与恢复](model-provider-transport.md) | 按原失败完整请求恢复后继续原候选 |
| `CLAIM-SUPPORTED-SCOPE-REPAIR-001`：缺证反馈修订扩大否定范围 | [支持范围修订](to_verify/claim-supported-scope-repair.md) | [支持范围约束](to_verify/claim-supported-scope-repair.md)；引用交接见[完成记录](completed/claim-atomic-evidence-revision.md) |
| `RESEARCH-SELECTION-OUTPUT-TRUNCATION-001`：选证输出截断 | [正式入口失败](claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究) | [服务方默认输出额度候选](to_verify/research-provider-output-default.md) |
| `RESEARCH-SELECTION-STATE-CONTRACT-001`：空研究稿的选证输出允许无效answered身份 | [实际正式失败](../evals/02-current-case-inventory.md#2026-10-08-已校准参考续验的选证状态阻塞) | [按真实状态呈现选证契约](completed/research-selection-state-contract.md) |
| `RESEARCH-SELECTION-USAGE-COMMIT-001`：失败前已完成选证用量漏计 | [计量提交问题](research-selection-usage-commit.md) | [及时提交候选](to_verify/research-selection-usage-commit.md) |

同一队列项可以有不同机制域的设计；记录必须写清覆盖范围。本表不代表同编号的网页搜索/抓取分离、来源生成或评测工作已经全部完成，也不维护第二份准入状态。

## 记录如何组织

**按具体问题组织，同一问题的所有优化尝试放在一起。** 本目录包含目录规则、跨问题总览、进行中的具体问题记录，以及 `completed/` 中的已解决问题。不能再按时间、会话、模型、Prompt 方法或“生成／Verifier”阶段把不同问题追加到同一份正文。

| 阅读目的 | 入口 |
| --- | --- |
| 可读性优先与功能模块化如何控制开发上下文 | [规范与响应解析职责整理](completed/code-readability-modularity.md) |
| 近期候选如何开始验证 | [近期候选入口](to_verify/README.md#近期候选入口)；本轮预声明见[当前稿独立核验](claim-revision-nonconvergence.md#2026-10-08-当前稿独立核验的预声明) |
| 当前还缺什么、哪些修复已有收益 | [问题总览](conversation-source-support.md#当前核心问题与责任边界) |
| 同一问题试过什么、为何停止或接入 | [十个问题入口与历史编号](conversation-source-support.md#阅读顺序与完整记录) |
| 文档缺项的优化与当前边界 | [文档缺项](document-absence.md)，最新为[第 109 节原文核查与扩源边界](document-absence.md#109-原文缺项核查与扩源反馈的边界验证) |
| 导航混入正文与后续取证成本 | [正文边界第 110 节](source-extraction.md#110-唯一主区域选择的保真与正式消费验证)；后续条件审计见[取证第 111 节](evidence-acquisition.md#111-重复搜索结果与目标化读取的准入审计) |
| 计划完成后仍取证、未提交 Final | [第 108 节整体生命周期修正](revision-feedback-loop.md#108-plan-生命周期整体修正)；包含旧提示候选失败、统一设计、组合恢复与正式验收记录 |
| 动作协议拒绝如何有界恢复 | [Conversation 动作协议恢复](completed/conversation-action-protocol-recovery.md) |
| 研究引用未选时如何返回准确坐标 | [确定性坐标反馈](completed/research-admission-coordinate-feedback.md) |
| 局部修订如何继承已有引用及原文 | [引用继承完成记录](completed/claim-retained-references.md) |
| Final 结构校验失败应如何归因 | [第 112 节原始响应与结构修复输入审计](action-final-protocol.md#112-final-原始响应与结构修复输入审计)；保留原失败，区分格式交接与来源支持 |
| 拒稿后如何复用已有检索结果 | [第 115 节完整查询交接与 Context 正式接入](evidence-acquisition.md#115-完整查询交接与-context-重组的正式接入验证)；执行事实、局部行为与最终交付分别验收 |
| 当前能否识别示例扩大为普遍必须 | [第 114 节最小复验](answer-object-mismatch.md#114-当前局部-verifier-识别-iserror-普遍义务的最小复验)：先判断单项识别能力，不要求单轮找齐全部错误 |
| 查询条件为何不会再丢失或混入引用 | [搜索执行参数保真交接](completed/query-execution-handoff.md) |
| 多错误如何逐轮识别与修复 | [多错误的渐进核验与修订](completed/multi-error-verification-revision.md) |
| 研究 claim 收到反馈后为何反复编辑却不收敛 | [反馈修订无法收敛的整体问题](claim-revision-nonconvergence.md)；具体待验证方案见[候选索引](to_verify/README.md) |
| writer 失败前已经完成的选证成本为何未持久化 | [选证用量提交问题](research-selection-usage-commit.md)；与工具内部用量及失败重试计量分别归因 |
| 当前研究参数范围如何进入真实 Schema | [参数范围完成记录](completed/claim-argument-scope.md) |
| 重试失败响应用量为何丢失 | [重试计量完成记录](completed/model-retry-usage.md) |
| MiMo 429 的具体原因为何无法定位 | [Provider 失败诊断交接](to_verify/model-provider-diagnostics.md) |
| 独立评分器为何无输出、有效评分是否可信 | [输出预算固化记录](completed/research-grader-output-budget.md)、[评分目标映射与依据归属](completed/research-grader-qualification.md) |
| 已有事实是否回答原用户问题、未知能否满足目标 | [逐项用户事实覆盖及停止边界](to_verify/research-goal-coverage.md) |
| 最终验收项重抄为何让合法报告失效 | [验收项引用恢复完成记录](completed/final-criterion-transcription.md) |
| 模型重抄待编辑正文为何导致修订被拒 | [编辑目标抄写问题与 Runtime 片段寻址](completed/claim-fragment-addressing.md) |
| 被拒稿为何需要交回完整正文与逐段引用 | [完整基稿交接](completed/complete-rejected-draft-handoff.md) |
| Verifier 引句绑定为何丢失有效反馈 | [调用单元绑定](completed/verifier-finding-binding.md) |
| 逐行引用为何无法被核验器归属到官方来源 | [来源归属的独立诊断](citation-source-attribution.md) |
| 行号与引用号混用、同一位置重复编号 | [独立问题记录](citation-coordinate-confusion.md)；后续正常 E2E 的归档门槛见[条件设计](../future/citation-coordinate-identity.md#后续-e2e-观察与-completed-条件) |
| 开发经验如何讲述 | [面试复盘](../interview/10-development-pitfalls.md)，对应问题记录与总结章节双向引用 |
| 模型决定结束取证 | [取证第 116 节](evidence-acquisition.md#116-由模型决定结束取证的契约验证) |
| 覆盖分支触发与声明消费的下一轮预声明 | [取证第 119 节](evidence-acquisition.md#119-覆盖分支触发与声明消费的下一轮预声明) |
| 生成侧越界的责任边界 | [取证第 120 节](evidence-acquisition.md#120-生成侧越界的最早责任边界归因) |
| 下一候选与准入条件 | [Future 活动设计](../future/conversation-verification-false-positive.md#3-下一准入边界) |

历史编号只用于证据反查，不决定新记录落点。新尝试写入对应具体问题；联合实验保留完整原始身份，各问题正文只解释自己的结论，不把独立失败追加到已解决问题。

每份问题记录先说明问题范围、最新证据、有效收益和剩余边界，再列同一问题的连续尝试。历史章节中的“当前”“下一步”只适用于当轮，不能当作今天的活动方案。早期综合盘点原文作为历史保留，不再接收其他问题的新实验。

待验证的研究工具方案见[按问题关联的候选索引](to_verify/README.md)。章节迁移必须更新全部仓库内引用，核对决定性证据与结论不丢失；已解决问题按下节删除中间正文，不要求永久保留每轮流水。原始 `.tmp` 归档保持原样；面试材料只提炼经验，不复制实验流水或发布状态。未来新问题建立具体问题记录，先更新总览导航；同一问题不能因更换方法或新一轮会话另建文件。

## 待验证方案与失效方案的保留规则

**未充分证明的方案保留，直接证伪的方案收敛为总结；两者不能按整次测试是否通过混为一类。** 候选必须关联具体优化问题，不能按工具名、模型或会话建立无问题归属的方案仓库。

1. 未到达检查点、只取得局部收益、缺少连续依赖证据、服务或预算中断，以及尚未完成正式接入时，将仍成立的候选写入 `to_verify/<具体问题>.md`。原问题记录和索引必须链接它；候选回链失败事实，记录责任主体、机制、依赖、已证明与未验证部分、隔离代码、证据和下一判据。历史诊断不因迁移而冒充当前生产能力。
2. 同一问题只有一份候选正文；Future 只维护产品准入、剩余门禁与引用，不再复制设计步骤。已成立并满足限定判据的能力按 `completed/` 固化；后续独立失败不能否定它。
3. 只有反例直接否定预声明机制或证明候选引入回归，才可把对应方案判为失效。先保留中文总结，写明问题、方案、代码或模型身份、样本数、原始结果、决定性反例、已证实原因与假设、仍成立部分及撤回范围；不能只写“未通过”。
4. 对已直接证伪并停止维护的方案，允许删除其专属原始请求、响应、Trace、冗余评测脚本及归档，只保留上述总结；先检查全部引用和证据依赖，记录清理范围及原因，同步清理链接。不得只删除失败样本以抬高通过率，不得重写封印，不得把已删除证据仍标为可回放。共享支持证据、待验证或已成立机制的决定性证据、原始产品 E2E 与发布证据不在此清理范围内；`tests/` 仍只读保留。
5. 无法确定是否直接证伪、归档仍被其他有效结论消费或仍待定位时，不删除；写明不确定性并保留在对应问题下。删除实验记录不改变原失败结论与产品结果，后续重新提出同一假设须补齐新的准入依据。

本规则是停止维护失效方案时的清理入口；在跑样本仍完整记录和封存。具体问题映射与必要字段见[待验证索引](to_verify/README.md)。

## 已解决问题的固化规则

**证明某个方案解决了一个明确问题后，必须在同一轮把成果固化到 `completed/<问题>.md`。** 固化以问题为单位，不以模型、方法、会话或一次综合实验为单位；不得继续把已证明能力列为待验证。

1. 先明确原问题、解决判据和证据适用范围。局部能力、生产接入、完整用户结果分别说明；不得因整体任务另有失败而无限推迟局部成果固化，也不得把局部通过升级为产品完成。
2. 每个完成文档只保留：问题与结论、采用方案与责任主体、接入状态及生产消费者、决定性证据与边界、失败尝试汇总、重新打开条件。原始归档保存输入、输出、代码身份和校验和，正文只链接必要证据。
3. 失败尝试汇总仅保留“尝试方案、失败原因推理、失败结果总结”；推理须区分已证实原因与待验证假设。删除原文档中的中间稿、逐轮日志、过期计划、重复报告及重复结论，不通过复制到另一个文档继续保存流水。
4. 新发现的问题若确认不是本方案引入，独立命名、明确责任边界，并按 Future 准入规则登记为待优化问题；不得放在完成文档的“残留问题”中、扩大原验收范围或据此重开原问题。因果未明时记录不确定性，先定位再判断。
5. 同步迁移索引、Future、面试材料及全部引用，删除旧正文，不保留重定向空壳。成功问题在其他 optimization 文档中只保留指向 `completed/` 的引用，不再维护状态、结果摘要、后续计划、验证待办或追加实验；完成文档与面试经验相互引用，原始 E2E 结果仍由评测文档拥有。
6. 只有反例直接否定已固化的判据或证明该方案引入回归时，才重新打开同一问题；未覆盖的泛化边界和独立问题不等于原结论失效。后续验证必须保留此前已生效的优化。

“移除中间结果”默认只移除过程正文及冗余展示，支撑有效结论的封存证据继续保留。直接证伪且停止维护的方案按[失效方案清理规则](#待验证方案与失效方案的保留规则)处理；不得篡改失败结论。纯文档固化无需重新调用模型；生产变更的准入与发布门禁仍按 EVD 执行。

## 与 Future 的联动规则

**每轮推进同时维护过程事实和活动决策，已成立的经验不能随 Future 清理而消失。** 根规范及[证据准入](../devSpec/change-evidence.md)继续约束实验、实现与验收；本节只规定记录落点。

1. 开始推进前，读取队列、活动设计和同编号过程记录。复用已有文档，核对上一轮已成立的条件、失败候选、独立阻塞及未执行项。
2. 运行前在对应具体问题记录中声明本轮问题、入口或历史输入身份、保留条件、唯一改动、判据、样本预算与停止条件。具体调用载荷和源码在原始归档封存；尚未执行必须明确标注。
3. 执行后在同一轮补齐实际结果、证据分类、样本数、已知成本、证据坐标、失败位置、取舍和仍成立的经验。完整用户结果与局部检查点分开，未取得的用量标未知。
4. 同步修改 Future 中受影响的活动方案、剩余证据或停止边界；只有准入事实发生变化时才改队列状态。过程记录链接活动设计，活动设计和队列提供过程入口，不复制完整实验表。
5. 更正旧解释时，明确原解释、输入差异、纠正依据和仍成立的结论，并修正 Future 冲突正文。补充规则失败不能否定此前不同输入条件下已成立的读取能力。
6. 关闭或撤回优化项时，按 Future 规则删除活动项、迁移生产事实；本目录按[固化规则](#已解决问题的固化规则)保存方案与经验，更新引用，不留下指向已删文件的链接。

局部成功、候选准入、生产落地和产品验收必须分别写明。资料已抓取、正文已注入、模型表达理解、实际补读与最终论断正确也属于不同证据，不得相互替代。模型返回的可见理由只辅助定位，不能作为隐藏内部因果证明。

## 单轮记录内容

**一轮记录以可复核的决定为单位，不以聊天消息为单位。** 下面字段可按规模使用段落或表格，禁止事后把预期改写成实际结果。

| 字段 | 必须记录的内容 |
| --- | --- |
| 身份与目标 | 日期、问题编号、输入或归档身份、待区分的假设、所属责任边界 |
| 固定与改变 | 用户任务、来源、模型与 thinking、预算、读取摘要及位置、Plan、改动变量；不适用项说明原因 |
| 输入输出来源 | 区分原始轨迹、条件回放和人工相邻控制；记录每个局部输入的上游实际输出、版本、引用和校验和，以及下游实际消费坐标。连续验证按 [EVD](../devSpec/change-evidence.md#11-模型依赖链必须连续验证)执行 |
| 模型输入审计 | 记录生产构造链、最终实际请求、Schema 和服务方参数；预期标签由评测持有，不写入被评模型输入。输入范围不同的 Verifier 与评分器分别判断 |
| 预声明 | 用户结果与局部判据、成功和反事实控制、调用或成本预算、停止条件 |
| 实际结果 | 已执行和未执行样本、原始结果、人工或自动判断、用量与耗时、错误及脚手架修正 |
| 结论与取舍 | 被否定的主张、仍成立的经验、能否进入生产、下一条有依据的验证边界 |
| 证据与联动 | 原始证据坐标、相关检查命令、Future 更新点或无需更新的原因 |

关键条件和结论应在仓库内直接可读。外部归档不可用时标为待恢复，不删除已有经验，不据此扩大通过声明。历史归档保持原样；本目录是后续推进时维护的统一解释入口。

## 记录与文档检查

**更新过程记录不自动授权实现或新模型调用。** 纯文档整理核对已有证据、双向链接、问题编号、标题、表格和代码块；不为文档整理重跑付费模型或产品 E2E。规范入口变更另运行 `scripts/check_dev_spec.py`。结果强度和中文写作遵守[文档规范](../AGENTS.md)。

判断输入与集合版本的失效边界经验见[来源报告复用固化记录](completed/claim-source-review-reuse.md)。
