# ADR 0032：Conversation 研究论断与独立汇总接入

日期：2026-09-28。状态：研究链已进入生产调用链；2026-09-29 按用户要求暂停拆分动作及复合论断识别，完整用户结果尚未通过。

## 失败事实、授权与范围

正式入口的同一中文研究任务在上一轮返回预算 `limitation`，没有用户答案；本轮修改前源码哈希与[该次封存身份](../../.tmp/optimization-integration-20260928/protocol-target/identity.json)完全一致。隔离 claim 实验还暴露整项重写、编辑后未复验、结构与来源判断混装及研究稿被要求承担最终排版的问题，分别由[未收敛问题](../optimization/claim-revision-nonconvergence.md)及其子问题拥有。历史局部改善不能证明整链已通过。

用户本轮明确要求“完整接入，不要进行offline测试”，覆盖此前“先补齐准入验证再接入”的执行顺序。本次直接装配生产纵向切片，以同一自然任务的正式 HTTP E2E 验收；不运行 Offline Eval 或 `tests/`。这不是补齐了原准入证据的声明：单变量消融、连续成功及未自然到达的恢复分支仍按实际结果记为缺失。记录本例外的风险、范围和退出条件，不扩大为其他任务的默认规则。

## 唯一事实责任与路径

`AgentRuntime` 现有模型和工具 Port 装配 `ConversationService`。用户消息从正式 Conversation HTTP 入口进入，真实取证仍通过现有 Admission 和工具网关。需要核验且非计划审阅的任务在实际可引用来源正文出现后，由 Conversation 进入研究提交；模型也可用 `prepare_final` 主动请求该阶段；没有该研究产物的普通交流保持原 Final 契约。这是不同产物的责任边界，不是同一研究任务可选的新旧双轨。

`ResearchClaims` 是 Interaction Journal 中唯一的不可变 claim 版本。`research.py` 是身份分配及合法编辑的唯一责任主体，创建后只允许绑定最新 `ResourceRef` 的片段替换、引用替换、补充缺失事实或重新核验。原文片段必须精确且唯一；引用仍由 canonical citation binder 解析，准入失败不写版本。模型拥有正文、取证和修订选择；代码原样保持非目标字段及其他 claims，不代写事实。

合法创建、编辑或单条撤回立即进入当前完整版本的逐项来源支持和整组事实覆盖核验。事实覆盖只接收会话与当前 claims，判断可否供汇总的事实充分性；来源 URL 存在性和最终呈现不属于该模型判据，不要求 URL 重复写入网页正文或 claim。来源支持反馈仍绑定当前版本与 claim；当前链路不调用复合论断或独立文档缺项识别，也不在 `ResearchReview` 中保存结构或覆盖拒绝。每个模型请求通过已注入的 `StructuredModelClient`，使用注册 Prompt 并计入现有 token 预算；预算不足不跳过剩余必检。`ResearchReview` 保存模型判断与确切版本，研究可汇总性由最后到达的完整事实覆盖通过推导，不额外持久化通过状态。单条撤回的具体准入见 [ADR 0033](0033-claim-deletion-and-document-absence-pause.md)。

研究通过后，独立汇总请求只物化完整原始会话、当前已核验 claims、从引用确定性恢复的来源 URL、冻结用户标准及汇总阶段反馈。它不读取研究决策历史或来源全文。完整 `FinalSubmission` 再通过运行时调用的 `verify_interaction_draft`：此时 Verifier 判断最终稿对已核验事实的忠实性及用户交付契约，不重新竞争 claim 与原始来源的支持判断。Receipt 绑定 `research_ref`；Completion 同时检查最终正文和当前研究版本。研究通过本身不触发交付。最终核验的 `research_feedback` 仅在事实缺口时生成 `ResearchReopening`，使该确切版本返回研究写作者；纯汇总表达问题仍返回独立汇总。来源身份保留 canonical 文档行坐标，不能使用支持核验内部的 `eNNN` 局部编号；最终引用须属于当前研究已核验的来源位置。

## 复杂度说明（Complexity Justification）与机制依据

沿用各问题已经核对的两个独立 A 级机制坐标：[精确局部编辑](../optimization/to_verify/claim-fragment-revision.md)、[判断单位先于支持核验](../optimization/to_verify/claim-multi-proposition.md)、[编辑后复验](../optimization/to_verify/claim-revision-progress.md)、[研究与最终交付对象分离](../optimization/to_verify/claim-verifier-stage-scope.md)。这些资料只支持机制边界，不能替代正式用户结果。

相对本轮开始时封存的代码，生产改动涉及 12 个文件，新增和删除行数以[生产改动清单](../../.tmp/claim-production-integration-20260928/production-change-inventory.json)为准，其中 3 个新模块、22 个新类均属于 claim、核验事实或模型提交的 typed 契约。新增模块分别拥有共享契约、Conversation claim 准入与检查序列、注册 Prompt；拆分避免最终 Verifier 反向依赖 Conversation。全部由现有生产根装配的 Conversation 和工具消费者调用。

不引入新的 Agent 注册、外部工作流、独立数据库、镜像状态或运行开关；研究在现有 Conversation 循环和 Journal 中运行。新增共享 typed claims/报告契约、局部编辑及检查序列模块、研究 Prompt 模块；其消费者分别为 Journal、Conversation 和最终 Verifier。研究路径移除直接生成 Final 后重新核验来源的旧职责，普通非研究核验仍消费其自身完整草稿。

## 验证、风险与退出

执行计划与检查点保存在[预声明](../../.tmp/claim-production-integration-20260928/plan.json)。只运行既有 `test_conversation_research_review_001` 一个相关 E2E：真实模型自主取证、创建和修订，不注入 claims、反馈或最终稿。用户结果沿用原中文请求及语义验收，局部检查点单独记录；`limitation`、503、超时仍计失败。首次验证保持原模型、16 回合、24 工具和 192,000 token 预算；随后用户明确授权的配置变更见下节。

自动逐项复验可能增加成本；历史结构判据已有同输入不一致风险，现已停用。独立汇总与最终核验只有在该连续链自然到达后才能获得本次执行证据。准入缺口不能靠静态检查或 Trace 存在补齐。第一次失败定位到最早责任主体后，最多做一次有界修正并先回跑同例；重复阻塞须重新判断责任边界，不增加局部补丁；用户授权提额用于主链路验证，不作为原预算通过或机制收益。

本轮例外仅允许按用户要求接入并接受正式验证，不允许宣称优化成立或发布完成。移除日期为 2026-10-05：届时若仍无完整用户结果证据，应重新取得明确范围决定，或撤回未获支持的生产部分及专属 Prompt，禁止长期保留隐式实验链。原始失败和仍成立的局部机制证据继续保留。本次实际结果追加到问题入口；通过前候选仍在 `to_verify/`，不移入 `completed/`。

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
