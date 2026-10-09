# 相同论断核验输入得到不同结果

`CLAIM-VERIFIER-CONSISTENCY-001` 属于 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`，记录同一研究轨迹中的核验一致性问题。它与字段修改丢失、引用坐标错误及研究模型未补证分别判断。2026-09-30 先逐组审查历史五组冲突，再完成断言范围的有界校准并接入恢复后的真实链路；该次局部判断达标，后续正式轨迹仍有相同输入的通过／拒绝冲突。不得选择较早通过覆盖最新适用拒绝。报告消费的责任边界见[复用固化记录](completed/claim-source-review-reuse.md)，判决和修订语义分别由本页及[支持范围反馈候选](to_verify/claim-supported-scope-repair.md)拥有。一致性仍按真实判决证据判断。

## 已确认的事实

2026-09-23 的[宽限制完整循环](revision-feedback-loop.md#145-宽限制下的完整研究修订循环)中，第 12 版 c1 的来源支持请求 `call-044` 返回空 `findings`，随后继续核验 c2。研究模型只修改了 c2 正文，c1 正文和引用保持。再次提交第 14 版后，`call-050` 对 c1 返回一条拒绝。

再次提交同一第 14 版后，`call-053` 又返回空 `findings`。这三次实际请求的完整 JSON 对象相等，包括操作、Prompt 版本、所有消息、模型、Schema 与服务方参数，不只是正文相同。三次实际响应模型均为 `mimo-v2.5`；实发参数没有 `temperature` 字段，不能把上游声明值当成服务方实际收到的值。请求内容的规范化 SHA256 为 `b1f4da9c43fad24ece7b22442c72efedbd265636ea85d2cd143cb7af4951b34b`。

中间一次拒绝针对 c1 的“现有查阅的官方文档和规范，没有明确说明……具体中介步骤”，理由是证据没有覆盖全文，不能确认缺项。另两次对同样表述和证据没有提出问题。实际审计见[请求及响应对照](../../.tmp/claim-full-loop-20260923/verifier-consistency-audit.json)。

该轮最后一次提交的 `call-058` 请求也与前三次完全相同，再次返回空 `findings`。四次合计为通过、拒绝、通过、通过；最终完整集合仍因 c2 被拒，没有完整研究通过。新增对照见[最终审计](../../.tmp/claim-full-loop-20260923/final-audit.json)。

2026-09-24 的同一研究轨迹继续提供另一处可复核反例：第 11 次核验 c1 的实发来源支持请求 `call-083` 与第 16 次 `call-116` 的 `kwargs` 完全相等，含模型、消息、Schema 和服务方参数。前者返回空 `findings` 并继续核验下一项，后者对原样 c1 返回“`type: "mcp"` 参数名缺证”的拒绝。c1 正文、引用、绑定证据及核验成功标准均未被研究模型修改；第 28 版因此先拒 c1，不足以评价该版 c4、c5 的来源支持。[连续轨迹审计](../../.tmp/claim-trajectory-audit-20260924/summary.json)及[第 11 次请求](../../.tmp/claim-parameter-feedback-v20-continuation-20260924/call-083-request.json)、[第 16 次请求](../../.tmp/claim-v25-verification-continuation-20260924/call-116-request.json)保留逐字比较。此观察再次证明核验结果不一致，不单凭本例裁定哪次语义判断正确。

[同一轨迹扩限](revision-feedback-loop.md#150-扩大预算后仍未取得完整研究集合通过)又出现 c6 的相同输入反例：第 17 次核验的 `call-121` 与第 18 次的 `call-135` 实发来源支持 `kwargs` 完全相等，c6 正文和引用也相同。前者返回空 `findings` 并继续核验 c7，后者以“已查资料没有明确说明中介步骤”的缺项表述无法由所交片段证明为由拒绝 c6。因此第 18 次转向 c6 不能归因于 c7 的引用编辑；同样不能单凭这两次响应判定 c6 的缺项表述究竟应通过还是拒绝。[扩限审计](../../.tmp/claim-budget-extended-audit-20260924/summary.json)保存请求和响应比较。

2026-09-26 的 [MiMo v2.6 Flash 集成续接](../../.tmp/claim-integrated-budget-continuation-20260926/result.json)再次出现同类现象：[第 150 次请求](../../.tmp/claim-integrated-budget-continuation-20260926/call-150-request.json)和[第 165 次请求](../../.tmp/claim-integrated-budget-continuation-20260926/call-165-request.json)的来源支持 `kwargs` 完整相等，引用单元及来源读取状态也相等。第 150 次[响应](../../.tmp/claim-integrated-budget-continuation-20260926/call-150-response.json)为 `findings: []`，继续检查后续论断；第 165 次[响应](../../.tmp/claim-integrated-budget-continuation-20260926/call-165-response.json)拒绝相同 c4 中“安全条款”的归类。第 15 至 16 次整组核验之间研究模型只修 c12，没有修改 c4。这一观察仍只证明判断不一致，不裁定该措辞实际是否有据。

2026-09-29 的[原中文正式 target](../evals/02-current-case-inventory.md#2026-09-29-单条撤回与独立缺项识别暂停的正式-target)在独立缺项分类停用后，完成 84 次逐项来源支持模型响应。[只读请求审计](../../.tmp/claim-delete-no-absence-20260929/recheck-audit.json)按供应商响应 ID 去重，再比较观察器保存的完整请求对象（方法、操作、版本、消息、Schema、`extra_body`）：仅有 29 个不同请求，55 次是已出现请求的精确重复。9 组请求重复，其中 2 组的可解析响应既有空 `findings`，又有非空 `findings`；另有 8 个响应不能按该脚本解析为判决，不参与混合判决计数。模型绑定与配置在同一目标运行中固定。[MiMo 官方参数说明](https://mimo.mi.com/docs/en-US/api/guidance/model-hyperparameters)明确 thinking 模式会把实际 `temperature` 和 `top_p` 固定为 `1.0` 与 `0.95`，因此调用方写 `temperature=0` 不能证明服务方会按零温度采样；这与输出差异相容，但不证明它是唯一原因。相同请求的不同结果再次出现，仍不能单凭输出差异判定哪次正确、或把 55 次重复调用全部视为可安全删除；核验范围和事实依据须单独审计。

2026-09-30 的[同一中文正式入口 target](../evals/02-current-case-inventory.md#2026-09-29-研究来源-url-交接与事实覆盖职责复验)又在前置研究阶段耗尽 32 个决策回合。按服务提供方响应 ID 去重的[只读完整请求审计](../../.tmp/research-coverage-fact-scope-20260929/repetition-audit.json)得到 90 次来源支持响应、28 个不同请求，另 62 次精确重复；11 组请求重复，其中 5 组的可解析输出同时出现空和非空 `findings`，4 个响应不可解析为判决。最大一组相同请求出现 16 次。研究从首版到第 21 版始终为 10 条 claim，每次只改动 1 条；已保存核验最多到 c8，没有事实覆盖。该结果证明逐项修订有实质编辑，但相同输入重判使先前检查无法稳定保留；不能单凭这些输出裁定哪次语义正确，也不能把两条独立随机轨迹的重复数差异归因于 URL 阶段改动。

代码每次编辑后从 c1 重验整个集合，并在第一条非空 `findings` 处停止。本次已保存的逐项核验计数为 c1 21 次、c2 19 次，递减至 c8 1 次，c9、c10 均为 0。这解释了为何单条修改虽有推进，整组覆盖仍始终无法开始。下表只裁定**本次提交片段与拒绝理由**之间的关系，不推断来源全文，也不把先前空 `findings` 当作语义通过证明。

| 相同请求组 | 通过／拒绝 | 逐项审查 |
| --- | --- | --- |
| c1 原版：[请求](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0018-request.json)、[拒绝](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0030-response.json) | 2／1 | 拒绝有据。片段写 `Applications SHOULD`，没有把 `Applications` 等同于“MCP 客户端宿主”；claim 添加了这个主体括注。 |
| c1 修订版：[请求](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0034-request.json)、[拒绝](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0212-response.json) | 12／1；另有 3 次原始响应不可解析 | 拒绝理由要求证明该词在规范其他位置也未得到界定，超出草稿的“此句”限定。已提交的句子本身可供核对，但草稿将这一限定语插在三项界面要求之间，句法有歧义；不能据此认定整条 claim 已可靠通过。 |
| c4 初版：[请求](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0090-request.json)、[拒绝](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0174-response.json) | 6／1 | 拒绝有据。所交 OpenAI 片段只给出声明 output schema 以便客户端校验的建议，不能证明整份资料都没有说明收到结果后是否实际校验。 |
| c4 修订版：[请求](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0184-request.json)、[拒绝](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0238-response.json) | 3／1 | 两项拒绝均有提交片段依据：草稿称“该处原文仅建议”声明 schema，但片段还包含 FastMCP 类型化返回模型及示例；草稿又把 MCP 正文归入 `Output Schema` 与 `Data Types` 章节，而提交片段没有章节标题。后者不判断原文实际章节，只判断本次没有提交标题依据。 |
| c7：[请求](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0190-request.json)、[拒绝](../../.tmp/research-coverage-fact-scope-20260929/model-calls/28272/0208-response.json) | 1／1 | 拒绝有据。片段把 OAuth 流程限定于通过 plugin 连接“你的自定义远程 MCP 服务器”，草稿却写成一般的 plugin 连接。 |

五组中每组的观察器请求对象逐字段相同，响应模型均为 `mimo-v2.6-flash`；观察器对象不包含全部服务方实发参数，不能据此声称 HTTP 载荷逐字相同。90 次去重后的原始响应中，4 次不可按原始内容解析为判决：3 次因输出长度截止且正文为空，1 次在 JSON 后附加了 `function`。它们不计入上表的通过／拒绝，生产结构恢复后的结果也不能回填成原始判决。

## 2026-09-28 结构核验中的同输入反例

结构判据内容边界候选的连续 Offline 样本也出现同类反例。未修改 c19 的第 12、16、20 次实发结构请求完整相等，包括操作、版本、消息、Schema、模型和参数；规范化 SHA256 为 `83992b2a5dcd4f65c0143de8ff728941f52b170993af0cfae01c4b89f4d7c83e`。同一 `mimo-v2.6-flash`、关闭思考时依次给出 `compound=false`、`false`、`true`，最后一次要求把协议属性、行业定位和用途分开。请求没有包含其他 claim、当前版本号或上一轮反馈，因而不能将差异归于这些 Context 变化。

[逐字段对照](../../.tmp/optimization-integration-20260928/claim-continuous/structure-consistency.json)只证明结果不一致，不单凭多数判断裁定哪次正确。原始整链与成本由[复合论断候选](to_verify/claim-multi-proposition.md#内容边界候选的连续结果与接入判定)拥有。必须先处理这一限定语义边界及稳定性，不能缓存一次放行后宣布结构已经通过；本轮没有对一致性加入生产修复。

## 归因边界与影响

这证明当前相同输入的核验结果不一致，不证明其中哪一次语义判断正确，也不能单凭此确定供应商内部随机机制。需要另外判断当前语料范围说明是否被误当成全文缺项结论；该问题的既有机制与事实见[文档缺项记录](document-absence.md)。

对研究循环而言，未修改且曾通过局部支持检查的论断仍可能再次被拒，使反馈对象重新变化。单条编辑仍保持其余 claim，不能把同请求输出差异归为字段修改丢失，也不能因此否定引用编辑的字段保护。一次正式轨迹曾完整研究通过并进入汇总，但最新轨迹未到事实覆盖；前者不证明当前核验稳定。

当前可以继续用原 Verifier 的拒绝反馈诊断研究修订，但它也可能对同一无据表述偶然放行，或把句内观察误读成全文缺项。一次整组 `passed` 只是该次模型判断，不证明重复稳定或用户结果合格。五组审查已排除“未修改 claim 收到不同正文证据”作为直接解释；已确认的改稿问题集中在主体限定、否定范围、排他词和条件省略，另有 c1 修订版的判据误读与句法歧义。下一步须先区分生成稿范围控制、来源片段边界与 Verifier 判据各自的责任，再预声明最小 Offline Eval 和同入口连续 E2E；不能缓存先前通过结果、跳过未修改项核验或改写反馈制造收敛。本轮保留原 Verifier，不追加修复。

## 2026-09-30 断言范围校准

用户要求恢复 evidence-first 并继续优化。本次将局部来源支持模板替换为 `v3-asserted-scope`：先确定草稿实际断言的主体、条件、强度及否定范围，再核对本次证据；同段各项事实分别检查，所引句内观察不扩大为全文否定，来源身份不补出正文缺失的定义或章节。没有修改报告 Schema、聚合门槛、逐项复验或拒稿交接。生产判据使用通用设备反例，具体 MCP 资料仍只属于输入。

按[预声明](../../.tmp/evidence-first-restored-20260930/plan.json)运行真实模型固定输入 Offline Eval：8 个样本、2 次重复、旧新两版本，共 32 次调用、68,395 tokens；模型为 `mimo-v2.6-flash`、JSON Object、思考开启、480 秒超时。样本包含两份实际失败请求，以及消除原句歧义的局部／全文相邻对照、条件主体对照和跨域多事实缺证。两版本固定相同证据和标签，只替换局部模板；未将模糊原句整体预标为正确。

旧版类别与标签一致 `14/16`，两次漏放历史 c4 的文档否定；候选 `16/16`，所有返回证据 ID 均合法。已逐项阅读实际 findings：候选指出缺证主体、全文否定、条件扩大及额外保证，局部观察和保留条件的正例均为空。类别匹配不意味着每一条解释完美；例如候选对条件扩大还附加了 CIMD 推荐范围说明，该理由不能独立证明所有 OAuth 实现行为。候选用量 38,272 tokens，旧版 30,123 tokens，此小样本未显示成本下降。

[实际样本和结果](../../.tmp/evidence-first-restored-20260930/offline/results.json)只证明这 16 次候选判断，没有证明对全部正文或重复调用长期稳定。下一步用原正式 E2E 连续消费真实选证和研究稿；完整用户结果、未到达阶段及有界修正分别归档。若相同范围边界再次失败，停止追加同义判据并重新审查实际输入和责任主体。

恢复后的首轮正式 target 用户结果为 `0/1`、32 回合预算限制，但已两次到达事实覆盖。[全请求审计](../../.tmp/evidence-first-restored-20260930/target-database-owner/audit-all-provider.json)有 66 次来源支持响应、22 个不同请求，另外 44 次为精确重复，3 组可解析输出同时出现通过与拒绝。c5 的同一完整输入先通过，后检出把 MCP 风险说明与 function calling 的 strict 说明称为“同一文档”的来源归属错误；实际两段 URL 不同，该拒绝有依据，先前判决漏放。其余冲突仍须按实际范围分别审查。候选的 16/16 固定样本不能外推成当前产品一致性或收敛通过；本轮不追加核验同义句、缓存或跳过检查。

最新坐标反馈正式 target 仍 `0/1`，未到事实覆盖。[审计](../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/audit.json)为 14 次来源支持响应、10 个不同 messages、4 次重复；2 个长度截止的空输出不计语义判决。c2 第一次通过、后一次出现两条 findings，[完整对象比较及人工审查](../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/boundary-review.json)确认捕获的 method、operation、version、Schema、messages 和 extra_body 全部相等，不声称覆盖全部 HTTP 实发参数。

第一条拒绝针对把原文的 tool call 引用要求及示例 `call_id` 写成具体强制机制，有本次证据依据，先前通过漏放。第二条将已描述五步应用流程中的“应用执行、模型发起”分工推导解读为模型在任何情形都不执行外部操作，要求排除其他机制和场景，存在上下文范围误读；这不意味着前一问题或整项应放行。v5 c1-c3 通过后，c4 对 `call_id` 及“只规定了”的两条拒绝有据，编辑随后因引号不匹配被拒。相同输入的冲突与模型实际编辑错误仍分别归因；一次有界范围校准没有解决长期稳定性，本轮封存该方向，不再追加同义判据或靠保留既往通过跳过核验。

## 2026-10-01 真实接入复验

[本轮正式 target](../evals/02-current-case-inventory.md#2026-10-01-重试计量与研究设计接入)在原模型、thinking、预算、来源模板 `v3-asserted-scope` 与用户结果契约下完成。[全部请求和响应审计](../../.tmp/research-convergence-integration-20261001/target/source-consistency-audit.json)有 46 次来源响应、19 个不同观察器请求、27 次精确重复，3 组可解析判决同时出现通过与拒绝。1 份响应在 JSON 后附加内容，保留原始输出且不计原始语义判决；生产可恢复结果不回填原始判决。

| 原样 claim 的请求组 | 实际结果 | 后一次拒绝对象 |
| --- | --- | --- |
| c1，第 4、5 版 | 通过、拒绝 | 将列出工具请求的代词主体确定转述为模型，而另一所引片段将动作归于 API。 |
| c2，第 6、7 版 | 通过、拒绝 | 将成本／延迟的可能性写为确定结果，并增加因果理由。 |
| c3，第 8、9、10 版 | 通过、通过、拒绝 | 对说明和 `should` 使用“要求”的转述强度。 |

每组比较的 method、operation、version、messages、Schema 和 extra_body 完整相等；模型均为 `mimo-v2.6-flash`。本表陈述实际拒绝内容，转述的句法与义务强度仍须结合对应完整输入裁定，不以多数判决代替事实。[Provider 参数审计](../../.tmp/research-convergence-integration-20261001/target/provider-parameter-audit.json)确认实发 thinking 开启、temperature 未传；[MiMo 官方 API](https://mimo.mi.com/docs/en-US/api/chat/openai-api)规定 thinking 开启会使用 temperature `1.0`、top_p `0.95`。这与判决方差相容，不单独证明根因。

本次完整用户结果仍失败，最后两次动作因保留引用未选齐而被确定性拒绝，未进入整组事实覆盖。片段 ID 的实际准入与范围保持已经成立，和来源一致性分别归因。本轮没有追加来源 Prompt、缓存已通过结论或跳过未改项；下一候选需基于这些完整实际请求重新声明语义边界与连续验证条件。

## 2026-10-01 修订修复后的判决边界审查

用户要求先修复引用继承，再分析 Verifier 不稳定。本轮完成确定性责任回放后，只读审查上述三组历史冲突，不修改来源模板或模型参数，不新增模型采样。thinking 保持开启，7 份原始响应的 `reasoning_content` 均保留。[实发输入身份审计](../../.tmp/research-retained-reference-repair-20261001/verifier-input-identity-audit.json)进一步确认每组传入 SDK 的完整 `kwargs` 相等，包含模型、所有消息、`response_format`、输出预算和 `extra_body`。

### 实际输入与构造链

`verification_steps` 先用唯一 binder 从当前 claim 的引用恢复 `draft` 与 `execution_evidence`，逐 claim 构造来源请求；`research_request` 放入来源模板 `v3-asserted-scope` 和实际核验单元。JSON Object 适配器再加通用 JSON／Schema 指令。三组实际 SDK 请求均为三条消息：通用结构指令、来源判据、当前正文与已绑定证据；没有注入上一版判断或其他 claim。实际输出为 `OverreachReport.findings`，第一条非空报告终止本版，合法修改后仍从首项重验。

因此，这三组冲突发生在相同语义输入上的不同判决，不能归于本次请求之间正文、引用、Schema 或 thinking 配置变化。来源身份与正文均已交付；服务提供方隐藏内部过程没有可核对的证据。返回推理只用来定位解释差异，不能充当隐藏因果证明。

### 三组解释差异

[逐组语义审计](../../.tmp/research-retained-reference-repair-20261001/verifier-semantic-audit.json)保留实际输入、证据、判决及诊断片段坐标。原 c1、c2、c3 分别为 604、634、799 字符，绑定 6、6、12 个证据单元；当前是逐 claim 检查，每项内部仍含多项事实。

| 组与结果 | 已确认的解释差异 | 责任判断 |
| --- | --- | --- |
| c1：通过、拒绝 | 一份证据用 `it`，另一份明确写 API 获取列表。通过按就近回指解释为模型；拒绝按另一段 API 主体判定模型归属缺证。 | 原文存在主体歧义，生成稿却作确定归属。需区分模型选择、API 获取列表和实际请求执行者，不能仅用多数判决决定整项正确。 |
| c2：通过、拒绝 | 通过直接认为成本句有据；拒绝将 `can` 对应的“会”判成必然，并将相邻两句的因果推导判成未直接明写。 | 模态与因果须分别审查。“可能”改为“必然”是明确扩大；泛指“会”仍需读语境。判据已允许有效推导，未逐字明写不能独立证明因果无据。 |
| c3：通过、通过、拒绝 | 通过按句中“应”读取 `should`；拒绝将介绍词“另要求”解释为“规定必须”，覆盖后续“应”。 | 草稿没有“必须”。仅凭介绍词不足以证明义务升级，应核对整句实际强度；其他事实继续独立检查。 |

三组共同暴露的是主体消歧、模态及上下文强度的判断阈值不同。2026-09-30 的有界校准约束了断言范围，但固定样本的 16/16 没有覆盖这些中文转述边界。报告仅输出发现的问题，空报告也没有逐事实判断记录，因而不能从其形状证明每个事实都被可靠检查。c2 的合并拒绝理由还把模态扩大和有效推导混在一起，研究模型难以判断该保留哪一部分。

本轮引用继承 target 的第 5 版还提供一份[新的实际拒稿审查](../../.tmp/research-retained-reference-repair-20261001/live-verifier-boundary-audit.json)。原始请求因 8,192 输出额度耗尽而正文为空，保留 30,152 字符推理；该响应不计语义判决。现有有界结构恢复随后返回两项 findings，输入的格式指令已变化，不能把两次调用计作同输入冲突。

第一项针对从 Agents SDK 的过滤能力概括一般应用能力，须单独检查实现范围。第二项把“是否允许并行调用可通过 `parallel_tool_calls` 配置”读成双向行为保证；实际前文明确写 `false` 防止多个调用，末句没有声称 `true` 必然并行。此处有上下文范围及有效推导的判据疑点，应和明确声称“设为 true 就保证多个调用”的负例分开。单项疑点不覆盖第一项范围问题，也不回填整条 claim 通过。

第 6 版 c1 在内部恢复后取得有效空 `findings`，c2 随后被拒。模型只修订 c2 生成第 7 版，c1 正文与引用保持。[原始结构对照](../../.tmp/research-retained-reference-repair-20261001/current-source-format-consistency.json)确认第 6、7 版 c1 的初始 SDK 参数完全相等，两次都长度截止；同样完全相等的恢复请求则先以 9,408 字符推理返回 15 字符有效正文，后以 29,178 字符推理耗尽输出而正文为空。输入丢失不是这组差异的解释；这属于原始结构可完成性的变化，不计为通过／拒绝冲突。修改后的整组重验让未改 c1 再次成为耗时边界，完整用户结果另行计分。

第 7 版最终形成有效拒稿，同一组完整 SDK 参数还出现空与非空 `findings`：[同一对照的第三组](../../.tmp/research-retained-reference-repair-20261001/current-source-format-consistency.json)为第 6 版通过、第 7 版拒绝。新拒绝针对“原文未指定配置主体”，指出原句 `You can prevent this by setting parallel_tool_calls to false` 已给出设置方线索。该否定有可核对的来源风险；它和配置者究竟属于哪个架构角色仍分别判断。

这里还观察到反馈转述的扩大：第 5 版意见是“原文未把主体指定为应用”，下一实际 replacement 却写成“原文未指定配置主体”。限定于某个架构角色的缺证被反向写成任何主体均未指定。此差异属于生成修订，后续相同输入一次漏过、一次指出则属于 Verifier 一致性；两者都不能归为机械编辑丢字段。

本轮还出现另一组完整 SDK 参数相等的有效判决：[首次请求](../../.tmp/research-retained-reference-repair-20261001/target/model-calls/26116/0087-request.json)返回空 findings，[后次请求](../../.tmp/research-retained-reference-repair-20261001/target/model-calls/26116/0113-request.json)拒绝相同稿。草稿先总述“tools 规范对应用与客户端的相应要求”，再用冒号列出人工参与、应用 UI 与客户端安全建议；拒绝将冒号前的主体延伸至第一项人工参与原则。证据 `e008` 是无主语的通用 SHOULD 句，后接 `Applications SHOULD:`，后续条目另有明确应用和客户端主体。这里的差异是概括句及列举范围的解释，须分别核对原文明确归属与有效实现推导，不以“原句未明写该主体”自动否定所有推导，也不以后面有应用条目补出前句的直接义务归属。

全部 SDK 来源请求另作[原始报告审计](../../.tmp/research-retained-reference-repair-20261001/target/sdk-source-report-audit.json)：比较完整 kwargs，内部格式修复与重试单独保留；可解析空／非空报告参与语义冲突计数，长度截止和空正文只参与报告可完成性计数。正式运行结束后封存 42 份来源完成响应，其中 16 份长度截止、15 份空正文，2 组出现有效通过／拒绝，5 组出现有效报告／不可解析输出的差异。所有来源 SDK 请求 thinking 开启，不能将这些现象归于本轮关闭 thinking。

最后一版从首项重验时，再次出现长度截止及在途恢复，未形成有效来源判决便到达入口等待上限。此处是报告可完成性的阻塞，和前文的语义冲突分别归因。完整用户结果、未到达阶段及最后已提交用量边界由[本轮正式评测](../evals/02-current-case-inventory.md#2026-10-01-修订引用继承与-verifier-审查)拥有；不把局部修订合法或前次空 findings 当作整组通过。

### 下一条验证边界

先保留三份完整真实输入作为诊断样本，分别建立主体归属、可能／必然、有效推导与上下文义务强度的清晰相邻对照；歧义原句单列，不预标整项通过。未来候选须说明同一输入怎样形成可复核的断言范围与证据判断，再预声明局部反事实和正式连续轨迹。研究 claim 的编辑粒度与每项内部事实的核对范围分别判断。

本轮分析新增模型调用为 0，生产来源判据、报告类型和整组复验行为没有修改。引用继承修复的正式运行与用户结果由[评测登记](../evals/02-current-case-inventory.md)拥有；本节只拥有 Verifier 的实际解释差异与下一责任边界。


## 2026-10-01 结构化反馈后的判决边界

本次来源请求 19 次，全部形成合法 typed 报告，无精确重复 SDK 请求；没有重复采样，故不能据此宣称相同输入判决稳定。[来源实发审计](../../.tmp/research-source-reuse-repair-20261001/source-audit.json)包含本次全部判断，未形成结论的历史结构失败仍单列。

c2 第 5 版明确限定“本条引用的原文范围”，报告仍将其读为整份资料没有结果约束；该局部范围误读与其他实际缺口分别归因。c1/c2/c7 的反馈已进入 writer，但部分改写扩大范围或新增事实未绑定引用，连续消费由[支持范围候选](to_verify/claim-supported-scope-repair.md#已观察结果与下一边界)拥有。最终验收项重抄的确定性失败由[独立问题](completed/final-criterion-transcription.md)拥有，不作为来源语义冲突。后续先固定清晰相邻样本重审判据，不再增加同义 Prompt 补丁。
