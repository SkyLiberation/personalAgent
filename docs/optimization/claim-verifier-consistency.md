# 相同论断核验输入得到不同结果

`CLAIM-VERIFIER-CONSISTENCY-001` 属于 `CONVERSATION-VERIFICATION-FALSE-POSITIVE-001`，记录同一研究轨迹中的核验一致性问题。它与字段修改丢失、引用坐标错误及研究模型未补证分别判断；当前只有诊断事实，没有新增优化方案或生产修改。最新正式 E2E 再次出现相同输入的通过／拒绝冲突，且研究未到整组事实覆盖。2026-09-30 已逐组审查最新五组冲突的提交片段与拒绝理由；仍须先定义责任边界和连续验证，不能靠缓存一次通过制造收敛。

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
