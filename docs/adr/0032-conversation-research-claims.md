# ADR 0032：Conversation 研究与最终回答统一交付

## 2026-10-16 当前决定

研究模型同时提交 claims 与可选 `final_answer`，同一 `ResearchClaims.resource_ref` 拥有完整版本。统一核验同时检查来源、回答与研究的一致性、实际最终回答是否满足原目标；实际反馈返回同一研究写作者。没有最终回答时保存研究进展并反馈 `final_answer_missing`，不调用模型判断存在性。正文与引用由唯一准入原子绑定，claim 变更未同时提交回答时清空旧回答。

生产已迁入统一链，删除逐条通过拼接、独立 Coverage、synthesis、研究 Final 及 `ResearchReopening`。`accepted_research` 从当前 Journal 前缀重建版本、引用、实际返回资料与读取范围，只有当前完整版本存在适用空报告时才返回确切回答。Conversation 沿原 FinalMessage、计划完成和 Journal 路径交付该正文；普通回答继续原核验，不接受研究专用参数。

引用、执行事实、语义判断与 Completion 仍分别拥有职责；不新增存储、Agent、持久答案镜像、分类轴或复核调用。旧三阶段运行仅作为原始历史证据保留，不转换为新批准；本轮正式 E2E 从新任务和空资料进入。内部契约破坏式替换，无兼容开关。调用准入、研究选择、写作与核验额度统一提高至 131,072，保留原出站策略；成本优化在用户结果成功后进行。

依据为已接受的 a6 实际反馈修订 1/1，以及完整真实 G2 提额回放 1/1。首次正式 E2E 的供应商拒绝和恢复时交付字段缺失各为 0/1，均保留。已通过研究的交付显式传入 FinalMessage 既有的 `disposition="answer"`，不为通用结果类型加默认值；真实正文反事实及同一正式任务续验 **1/1**，确切正文交付、统一报告与独立评分均通过，见[正式结果](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证)。规格、必要反事实、预算、停止与回撤边界由[唯一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)拥有；其他既定用例与发布矩阵不由本例替代。后续新真实失败按最早责任定位，不以旧路径静默降级。

2026-10-16 恢复绑定修正：同一进程或新进程均沿当前完整输入判断研究报告适用性，不再因恢复请求而额外丢弃本来适用的报告。相同任务、Prompt、研究版本、绑定原文、返回资料及读取状态不变时可消费原报告；任一实际决定性输入改变仍拒绝复用。真实第 4 版的三项反馈与原启动过滤的对照已成立，正式恢复只从原始状态继续，不转换旧契约批准。验收和一次恢复边界见[统一 Spec](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)。

## 历史决定与原始证据

下文按原日期解释，出现的“当前”仅指各段原代码身份，旧三阶段不再是生产契约。

日期：2026-09-28。状态：研究链已进入生产调用链；2026-09-29 暂停拆分与复合识别；2026-09-30 按用户要求恢复 evidence-first，完整用户结果仍待验证。

2026-10-01：用户授权修复重试用量漏计并落地未收敛问题下其他设计。版本绑定的片段 ID、无损写作视图和当前引用/身份 Schema 范围已进入唯一研究路径，旧字符串匹配协议删除；本轮正式 target 及预声明见[接入归档](../../.tmp/research-convergence-integration-20261001/plan.json)。

2026-10-08：用户明确要求先解除前述独立阻塞、继续原优化，重新确定现行研究链的推进范围。[当前稿独立核验方案](../optimization/to_verify/final-revision-comparison.md)完成隔离校准及一次实际反馈连续链，原独立用户结果评分通过；生产已迁移同一三个模块，最终请求使用 v6 当前稿契约。一个原正式入口 target 在研究阶段耗尽 32 回合，最终核验未到达；[既有正文与新增依据原子提交](../optimization/completed/claim-atomic-evidence-revision.md)完成两份真实失败状态的条件验证，其中第一条独立范围拒稿经一次真实反馈修订通过；原样两个模块已接入，恢复同一正式验收，原最终职责保持。旧临时例外不自动延长；本次仅允许现行研究链按该范围继续验证，新的移除复核日期为 2026-10-09。届时完整用户结果仍缺证据时须作明确保留或撤回决定，不能默认长期实验接入。独立阻塞优先在自身责任边界解决，候选直接证明回归时撤回其自身差异；发布仍需完整矩阵。

## 失败事实、授权与范围

2026-10-15 Coverage 引用恢复：单次 Source 的正式七条均通过，自动复核零次；覆盖模型结构修复后输出未返回坐标，HTTP 422 阻断交付，原 0/1 保持。引用存在性现已进入同一 typed 校验与 Model Port 有界修复，临时绑定类型保持 canonical Schema，合法输出恢复 canonical 类型，普通默认一次、Coverage 最多两次。局部真实阶段 2/2 后原样迁入五模块，Source v31、六类五字段和直接反馈保持；新正式用户结果单独验收，见[独立引用恢复](../optimization/completed/coverage-reference-recovery.md)。

2026-10-14 移除自动复核：用户接受 C7 的范围澄清要求，真实修订与新稿 Source 已通过。单次 Source v31 已原样迁入两个模块，六类五字段、selector v7 和 writer v23 保持；删除非空反馈的再次判断、注册模板及组合版本。九项完整回放与 C7 实际闭环构成新校准资格，旧 9/10 不改写；原后续消费、完整研究与正式入口仍按既定计划验收。现行契约见[核验专题](../topics/verification-and-completion.md)，依据与删除项见[固化记录](../optimization/completed/source-proof-boundary-isolation.md#2026-10-14-移除自动反馈复核)。

2026-10-14 统一契约接入：Source v28／条件反馈复核 v4 和 writer v23 已原样迁入三个既定模块，来源 Schema 统一六类五字段，旧缺证名称删除；初判为空直接继续，非空只复核实际报告一次，最终报告与组合版本绑定。十项局部、两项真实修订及完整研究链均达到既定条件；生产十一项真实请求和消费等值，其他源码及环境保持。旧终态记录独立归档、实际数据库恢复，当前无需来源类别数据改写或兼容别名。原中文正式 E2E 已实际交付，Source／Coverage／Final 通过；评分参考缺少实际引用范围而 inconclusive，原 pytest 0/1 保留。独立参考修正后继续正式验收，发布矩阵未验证。当前契约由[核验专题](../topics/verification-and-completion.md)拥有，生产接入由[固化记录](../optimization/completed/source-proof-boundary-isolation.md#生产接入与真实消费)拥有，剩余正式验收见[活动设计](../optimization/to_verify/normative-context-acquisition.md#下一次正式验收)。

2026-10-13 候选决定修订：撤回双阶段核验与两类 Schema 草案，保持单次统一 Source。六类候选新增 evidence_presence_conflict，以 citation_not_supported 替换原缺证名称，同步 Schema、Source、条件反馈复核及 writer；无新字段、兼容别名或独立范围调用。v28／反馈复核 v4 明确未绑定原文不得支持当前核验点，校准后完整十项 10/10，局部问题关闭；七项复用、U1／A3／C7-after 续验，旧标签与 7/8 不改写。P1、C7 两个新类别反馈实际修订消费 2/2，通过完整目标 Source；其他当前 claims、Coverage、生产接入和正式用户结果仍待验收。生产保持 v19、writer v21 与原五类。局部结论由[固化记录](../optimization/completed/source-proof-boundary-isolation.md#统一核验的局部问题关闭)拥有，剩余流程由[唯一设计](../optimization/completed/source-proof-boundary-isolation.md#生产接入与真实消费)拥有。

2026-10-11：按用户持续推进的授权，仅迁入来源反馈分类、实际返回范围和证据用途修正的三个既定模块。原生selector／writer消费实际反馈后的完整研究链1/1；生产262份源码与密封候选逐字相同，旧三个解释字段已删除。当前Source v19、writer v21，其他决策、执行、最终核验及Completion契约保持。原Docker故障保留为历史阻塞，用户恢复后正式target已完成，原评分下用户结果0/1；新真实P1重开对应引用支持问题，旧局部成绩保持。局部和研究消费通过不延长旧实验例外，也不证明用户结果或发布通过。范围、预算和退出由[唯一接入设计](../optimization/completed/source-proof-boundary-isolation.md#生产接入与真实消费)拥有，旧正式失败及历史记录保留。

正式入口的同一中文研究任务在上一轮返回预算 `limitation`，没有用户答案；本轮修改前源码哈希与[该次封存身份](../../.tmp/optimization-integration-20260928/protocol-target/identity.json)完全一致。隔离 claim 实验还暴露整项重写、编辑后未复验、结构与来源判断混装及研究稿被要求承担最终排版的问题，分别由[未收敛问题](../optimization/claim-revision-nonconvergence.md)及其子问题拥有。历史局部改善不能证明整链已通过。

用户本轮明确要求“完整接入，不要进行offline测试”，覆盖此前“先补齐准入验证再接入”的执行顺序。本次直接装配生产纵向切片，以同一自然任务的正式 HTTP E2E 验收；不运行 Offline Eval 或 `tests/`。这不是补齐了原准入证据的声明：单变量消融、连续成功及未自然到达的恢复分支仍按实际结果记为缺失。记录本例外的风险、范围和退出条件，不扩大为其他任务的默认规则。

## 唯一事实责任与路径

2026-10-13 历史反馈核对决定（现已移除）：来源报告绑定前，仅对实际非空反馈执行一次形成后核对，复用五字段报告与现有模型 Port；原始响应是尚未接受的模型结果，不覆盖执行事实，代码不删改语义发现。原七项完整 7/7 已验证，方案及边界由[反馈忠实性固化记录](../optimization/completed/source-feedback-classification.md#已形成反馈的忠实性修正)拥有；生产尚未迁入。

2026-09-30 用户明确要求“恢复 evidence-first 并继续优化”。现行研究提交前，Conversation 用同一模型 Port 调用 `conversation.research.evidence_selection:v7-state-bound-needs`，输入原始会话、冻结验收原项的只读编号、实际执行资料、当前 claims 与最新适用研究反馈。历史研究取证自述由普通动作消费，进入研究时移出当前修订视图，执行事实及适用核验报告保持。模型输出 typed 信息需求、对象引用及 `write/acquire/limit`；代码只绑定可见坐标。Runtime按canonical当前稿是否存在选择同一父契约的当次Schema：空稿只允许`ready/needs_evidence/delivery_check`及空claim_ids，已有稿保持完整answered契约并绑定当前claim。状态和引用校验继承原责任，不改写模型语义。选择本轮消费，不写入新的持久业务事实；恢复时可由原执行记录重建。`write` 后由 `writer:v23-citation-support-contract` 消费所选正文，创建和增补的引用及引用替换的新增坐标须属于本轮选择；正文片段修订保留目标 claim 已绑定引用，模型可同次通过 typed `additional_references` 明确追加新依据，新增坐标须本轮选中且真实可见；Runtime 去重合并，版本、片段及引用全部校验后生成一个新版；写作者检查修订后相邻句的来源指代并修订受影响范围。纯认知限制不强制添加引用，外部事实缺证仍由来源核验判断。`acquire/limit` 沿现有取证或限制响应分支执行。全部调用计入原预算，选择不代表语义通过。选证成功响应在调用 writer 前提交累计用量；选证或直接模型调用失败时，应用异常保留已有 typed 聚合响应并在外层提交实际完成用量，再传播原错误。HTTP 与日志继续使用原有界错误投影。修复和待验证边界由[计量候选](../optimization/to_verify/research-selection-usage-commit.md)拥有。删除、来源 URL 交接及停用机制保持当前契约。准入与验证限制由[选证候选](../optimization/to_verify/claim-evidence-selection.md#2026-09-30-按用户要求恢复并连续验证)拥有；下文各日期试验保留为历史证据。

`AgentRuntime` 现有模型和工具 Port 装配 `ConversationService`。用户消息从正式 Conversation HTTP 入口进入，真实取证仍通过现有 Admission 和工具网关。需要核验且非计划审阅的任务在实际可引用来源正文出现后，由 Conversation 进入研究提交；模型也可用 `prepare_final` 主动请求该阶段；没有该研究产物的普通交流保持原 Final 契约。这是不同产物的责任边界，不是同一研究任务可选的新旧双轨。

`ResearchClaimContent` 唯一定义研究正文及引用契约，创建、增补和 canonical `ResearchClaim` 均消费它。它复用既有严格配置和引用字段，只将 text 的 Schema 描述限定为供研究来源核验与独立汇总使用的论断；最终 `ConversationAnswerSegment` 仍拥有交付正文。`writer:v11-retained-references` 已于 2026-10-01 迁移片段地址输入与输出；此前 v9 只修正研究正文职责描述。实发 Schema 冲突、固定输入比较及停止条件见[阶段契约预声明](../../.tmp/evidence-first-restored-20260930/stage-schema-plan.json)，不把类型描述修复宣称为语义收敛。

`ResearchClaims` 是 Interaction Journal 中唯一的不可变 claim 版本。`research.py` 是身份分配及合法编辑的唯一责任主体，创建后只允许绑定最新 `ResourceRef` 的片段替换、引用替换、补充缺失事实或重新核验。片段 ID 由当前正文无损派生，动作提交首尾 ID 及 replacement；完整资源、owner、revision 与 claim 核对后，Runtime 取出连续原文范围合并，范围外字符保持原样；引用仍由 canonical citation binder 解析，准入失败不写版本。模型拥有正文、取证和修订选择；代码原样保持非目标字段及其他 claims，不代写事实。

选中子集违规由准入代码对实际绑定坐标计算集合差，错误反馈列出确切未选坐标供下一轮修复；它不替模型选择证据，也不接纳被拒动作。局部修复和生产交接的限定证据由[确定性坐标反馈](../optimization/completed/research-admission-coordinate-feedback.md)拥有，完整用户结果由[评测登记](../evals/02-current-case-inventory.md#2026-09-30-evidence-first-恢复与有界修正)拥有。

合法创建、编辑或单条撤回立即进入当前集合的来源支持与整组事实覆盖核验。修改项核验完整正文；同次 `respond` 的模型绑定内，正文、引用、binder恢复的原文与来源身份、完整实际返回视图及来源判据版本相同的项，消费 Journal 中最新适用报告；最新适用拒绝同样保留。新的调用边界及显式 `recheck_claims` 重新核验。逐项报告保持原绑定，不生成通过镜像或复制报告。事实覆盖接收会话、同一冻结原项、当前 claims、全部实际已返回的去重可引用读窗及执行派生读取状态，以 `ResearchCoverageReport.requirements` 逐项记录原 `criterion_id`、必要事实关系、当前 claim、相关原文坐标、状态及反馈。`covered` 表示已有事实充分，`missing` 表示已读必要事实未写入，`needs_evidence` 表示必要关系仍缺原文，`delivery_check` 将呈现或提交要求交给最终核验。Runtime 校验原项全集恰好一次、当前 claim 及已返回坐标，从全部状态推导研究充分性；`delivery_check` 的最终结果继续验收。覆盖请求不依赖当前 claim 自选的引用范围，大页抓取元数据及 retrieval 入口保持，未返回正文由原动作入口读取。明确的来源未知与当前尚未取得段落分别判断，writer 按缺项反馈补证或修订；来源 URL 存在性和最终呈现不属于该模型判据，不要求 URL 重复写入网页正文或 claim。研究来源支持由`conversation.research.support:v31-proof-last`单次输出`ResearchSupportReport`，自动反馈复核已删除，输入完整draft、本条引用、有序片段及实际返回视图；外部事实引用支持与实际返回范围分别判断，不能互相代替。每项发现只含category、error_description、片段首尾ID及evidence_ids，多个独立问题分别输出；分类和说明解释同一具体关系。Runtime校验提交身份和有序范围，从原绑定恢复相关eNNN或dN原文交给selector与writer；旧三个解释字段已删除。来源支持反馈仍绑定被验版本与 claim；当前链路不调用复合论断或独立文档缺项识别，`ResearchReview` 不保存独立结构或文档缺项分类报告；用户事实覆盖的逐项模型判断按实际结果保存。每个模型请求通过已注入的 `StructuredModelClient`，使用注册 Prompt 并计入现有 token 预算；预算不足不跳过剩余必检。`ResearchReview` 保存模型判断与确切版本，研究可汇总性由最后到达的完整事实覆盖通过推导，不额外持久化通过状态。单条撤回的具体准入见 [ADR 0033](0033-claim-deletion-and-document-absence-pause.md)。

研究通过后，独立汇总请求物化完整原始会话、当前已核验 claims、从引用确定性恢复的来源 URL、冻结用户标准及汇总阶段真实反馈。它不读取研究决策历史或来源全文；`synthesis:v3-revision-scope` 消费 Journal 中的 `latest_final` 与 `final_feedback`，修订并保留有据事实的主体、条件、数量、列举范围与义务强度。完整 `FinalSubmission` 再交给运行时调用的 `verify_interaction_draft`：Runtime 沿 canonical citation binder 恢复最终每段实际引用的原文与来源 URL，形成同顺序、同正文的 `cited_units`，参数校验一一对应。`final_verification:v6-current-draft` 只接收当前完整稿、当前研究、冻结标准、当前段落及实际引用，独立判断忠实性、具体来源归属和用户交付；旧稿与真实反馈由汇总者消费。当前声明按整段上下文解析来源指代，完整清单按实际数量、要素及正文与总结的一致性检查。研究来源核验继续拥有 claim 事实支持，多来源本身合法。Receipt 绑定当前确切正文、原验收项和 `research_ref`；Completion 检查当前通过稿及研究版本。研究通过本身不触发交付。最终核验的 `research_feedback` 仅在事实缺口时产生 `ResearchReopening`，使确切版本返回研究写作者；表达问题仍返回独立汇总。来源身份使用 canonical 文档行坐标，最终引用须属于当前研究已核验的位置。接入证据和未覆盖边界见[本轮记录](../optimization/claim-revision-nonconvergence.md#独立阻塞恢复与原方案续验)。

## 复杂度说明（Complexity Justification）与机制依据

沿用各问题已经核对的两个独立 A 级机制坐标：[精确局部编辑](../optimization/to_verify/claim-fragment-revision.md)、[判断单位先于支持核验](../optimization/to_verify/claim-multi-proposition.md)、[编辑后复验](../optimization/to_verify/claim-revision-progress.md)、[研究与最终交付对象分离](../optimization/to_verify/claim-verifier-stage-scope.md)。这些资料只支持机制边界，不能替代正式用户结果。

相对本轮开始时封存的代码，生产改动涉及 12 个文件，新增和删除行数以[生产改动清单](../../.tmp/claim-production-integration-20260928/production-change-inventory.json)为准，其中 3 个新模块、22 个新类均属于 claim、核验事实或模型提交的 typed 契约。新增模块分别拥有共享契约、Conversation claim 准入与检查序列、注册 Prompt；拆分避免最终 Verifier 反向依赖 Conversation。全部由现有生产根装配的 Conversation 和工具消费者调用。

不引入新的 Agent 注册、外部工作流、独立数据库、镜像状态或运行开关；研究在现有 Conversation 循环和 Journal 中运行。新增共享 typed claims/报告契约、局部编辑及检查序列模块、研究 Prompt 模块；其消费者分别为 Journal、Conversation 和最终 Verifier。研究路径移除直接生成 Final 后重新核验来源的旧职责，普通非研究核验仍消费其自身完整草稿。

## 验证、风险与退出

执行计划与检查点保存在[预声明](../../.tmp/claim-production-integration-20260928/plan.json)。只运行既有 `test_conversation_research_review_001` 一个相关 E2E：真实模型自主取证、创建和修订，不注入 claims、反馈或最终稿。用户结果沿用原中文请求及语义验收，局部检查点单独记录；`limitation`、503、超时仍计失败。首次验证保持原模型、16 回合、24 工具和 192,000 token 预算；随后用户明确授权的配置变更见下节。

自动逐项复验可能增加成本；历史结构判据已有同输入不一致风险，现已停用。独立汇总与最终核验只有在该连续链自然到达后才能获得本次执行证据。准入缺口不能靠静态检查或 Trace 存在补齐。第一次失败定位到最早责任主体后，最多做一次有界修正并先回跑同例；重复阻塞须重新判断责任边界，不增加局部补丁；用户授权提额用于主链路验证，不作为原预算通过或机制收益。

2026-09-28 的例外仅允许按用户要求接入并接受正式验证，不允许宣称优化成立或发布完成，原移除日期为 2026-10-05。新的明确范围决定见本文开头的 2026-10-08 授权，不以旧日期自动延长。原始失败和仍成立的局部机制证据继续保留；实际结果由问题入口拥有，候选固化按本次判据与完整用户结果的各自边界处理。

## 用户授权提高生产预算后的连续验证

原配置两次正式 target 均在 claims 创建前耗尽预算：首样本 195,716 tokens，回跑 194,757 tokens / 24 次工具；原始结果仍均为失败。用户随后明确选择“提高生产预算上限，先验证完整 claim 链路”。本地 `.env` 与生产示例改为 768,000 tokens、48 次工具、32 个决策回合；模型、任务和评分契约不变。HTTP 等待上限为 3600 秒，模型请求仍为 480 秒。新样本保存于同一归档根的 `target-expanded/`。这是容量调整后的真实链路验收，不是同预算收益或单变量消融；不能抹去原配置失败。

## 非法工具参数的错误交接

提额后的首个正式样本在约 139 秒因工具参数不是 JSON 返回入口 503；一次原有重生成仍失败，未到达 claims。该批调用没有执行，属于有实际响应的动作协议拒绝，不是服务不可用。`StructuredOutputFailure` 由 Adapter 携带实际聚合用量和零可执行动作的响应；Conversation 对该错误返回原 typed action feedback，并按既有预算和重复错误规则让模型重新决策。Usage decorator 同样保留拒绝响应的成本。未增加适配器重试次数、未剥除 XML 前缀、未执行部分调用，也不把结构化语义输出或网络故障改为成功。原用例先回跑，检查所有非法批次的 call_id 均没有执行 Observation。

## 研究候选入口条件修正

协议交接修正后的同入口样本没有入口异常，但 11 回合、29 次工具、806,775 tokens 后仍未调用 `prepare_final`，研究初稿未出现。实发 Action v14 与准备动作 v3 把进入研究核验描述成已有完整事实集合后的交付请求；这可能把研究核验职责前置给取证阶段，输入缺陷尚不等于因果已经成立。Action v15 与准备动作 v4 改为允许已有初步依据时提交当前有据候选，再由研究核验反馈事实缺口；不要求先读完全部来源或自证覆盖。完整事实覆盖、逐项来源支持和最终用户标准仍为交付门禁。仅调整这一入口职责，保持同一原任务和提额后预算，以 `target-candidate-entry/` 真实样本验证自然到达阶段与用户结果，不把随机轨迹当正式消融。

## 来源可见后的研究阶段衔接

入口提示的单次修正仍未完成接入：`target-candidate-entry/` 在 1001.36 秒、779,708 tokens、15 回合和 38 次工具后预算限制，仍无 claims。停止追加入口提示，将阶段可达性归还运行时：需要核验且非计划审阅的任务，在 canonical citation projection 已有 `source_text` 正文后进入研究提交；搜索摘要或只有未读资源引用不触发。模型仍可创建候选、返回取证或停止，不被注入任何语义结果；只有完成研究核验后才允许独立汇总。动作和研究 Prompt 同步该实际衔接方式，删除“必须再次主动 prepare_final 才返回研究”的说明。

验证仍为同一个正式 E2E，配置保持 768,000 tokens / 48 工具 / 32 回合；以真实来源和紧随其后的实发研究请求验证接入，不声称已获得产品通过。若该边界绕过计划审阅、导致错误交付或阻断继续取证，则撤回此边界并保留反例。

## 撤回反复结构放行的前置门禁

`target-source-entry` 已由正式 Conversation 自主创建 claims，多次真实拆分均保持其他项并自动复验。但完全相同的实发 Provider kwargs 出现相反的结构判断：一项连续六次 false 后又因出处 URL 判 true，另一项也从 false 变为 true，见[原始请求坐标](../../.tmp/claim-production-integration-20260928/target-source-entry/same-input-structure-disagreements.json)。来源支持尚未运行。运行约 22 分钟后主动终止该诊断样本并保存 [operator-stop](../../.tmp/claim-production-integration-20260928/target-source-entry/operator-stop.json)；这属于人工中止、未交付，不能计为完整 target 通过，也不能把人为断开造成的入口错误归为产品服务故障。

被反例否定的是“全部 claims 每次结构分类均放行才能开始事实核验”的可靠性，而非拆分操作、其他字段保持或自动复验的已成立行为。替换这一前置门禁：来源 Verifier 仍逐项检查当前完整正文的全部断言；只有真实 findings 才追加原独立结构诊断，并将同版来源拒绝与诊断同时送给研究写作者。结构反馈不能单独拒绝已获来源支持的内容，不能覆盖来源意见，也不允许在没有 findings 时出现。写作者仍自主选择取证、片段修订、引用修订或拆分。完整来源支持、事实覆盖、独立汇总忠实性及用户结果都必须通过；没有缓存旧版通过或忽略未改正文。

再次核对固定源码 [Ragas Faithfulness@298b682](https://github.com/vibrantlabsai/ragas/blob/298b68274234c060deacab3cf5fb52aa3a20e885/src/ragas/metrics/_faithfulness.py) 与 [FActScore@f28272d](https://github.com/shmsw25/FActScore/blob/f28272deffcf33efc1f1117d5479c10bb75221a9/factscore/factscorer.py)，两者用分解单元服务于事实支持判断，没有本工程的反复结构分类放行循环。这是职责取舍的外部参考；把结构用于拒稿诊断是本工程依据真实反例作出的设计判断，不宣称两者实现了该运行时流程，也不替代本工程验证。

`target-support-feedback/` 从相同原始中文会话和空资料重新开始，保持模型、768,000/48/32 预算、正式入口与原用户评分；不恢复中止样本，不运行 Offline。如果吞掉来源拒稿、在缺证时提前汇总或产生用户结果回归，撤回这一边界。独立汇总及最终交付未自然到达前仍不具有通过证据。

## 本轮停止状态

用户明确要求“遇到阻塞后直接停止，不需要继续执行”，`target-support-feedback` 已据此终止，不再修复或回跑。本样本实际到达首版 10 条 claims、c1 来源拒稿、精确片段修订与第 2 版自动复验；c1、c2 通过后，c3 因提交引用未支持 `require_approval` 的 `always` 取值被拒。完整研究覆盖、独立汇总、最终核验及用户结果未通过。停止记录见[本轮报告](../../.tmp/claim-production-integration-20260928/REPORT.md)。

## 2026-09-29 同时暂停拆分动作与复合识别

用户要求先完成当前正式运行，再同时停用模型可提交的 `split_claim` 和复合论断识别 Verifier，并用相同中文 E2E 对比。Conversation 研究准入删除拆分分支，`ResearchSubmission` 不再暴露该动作；来源支持拒绝后不再额外请求 `ClaimStructureReport`，`ResearchReview` 删除 `structure` 字段，注册 Prompt 和写作者说明同步迁移。该轮比较时来源支持、文档缺项、事实覆盖、独立汇总和最终核验的责任不变；后来文档缺项识别暂停、单条删除动作加入，现行契约见 [ADR 0033](0033-claim-deletion-and-document-absence-pause.md)。

[正式对比](../../.tmp/claim-no-compound-20260929/comparison.json)确认两次用例的用户输入、入口、初始事实、评测器、模型、transport、预算和超时一致，生产代码差异限于四个研究相关文件。停用前样本在入口等待上限超时；停用后样本返回预算 `limitation`，两者用户结果均为 `0/1`。停用后实发复合识别调用为零，但研究稿仍通过 `add_claims` 重复增补，未完成来源支持、事实覆盖或独立交付。因此此决定只证明机制已从正式路径暂停，不能声称解决了未收敛问题。两条独立随机轨迹且同时移除两个机制，不用于估计任一机制的单独收益。

本次停用的退出条件是取得同一正式入口的完整用户结果和必要反事实，并重新判断复合结构是否需要独立责任；不得因调用数下降恢复未经证明的机制。新观察到的重复增补由[未收敛问题入口](../optimization/claim-revision-nonconvergence.md)单独登记，先审查模型实际输入、反馈与准入边界，再决定有界修正；不在本次比较后连续追加局部补丁。
