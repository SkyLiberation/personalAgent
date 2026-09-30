# ADR 0033：允许撤回单条研究论断并暂停独立文档缺项识别

## 背景与决定

2026-09-29 的同一中文正式 E2E 未交付答案。停用拆分与复合识别后的研究第 6 版从 11 条增至 22 条，其中 6 条新增论断的正文和引用与旧项完全相同；当前模型只能修改或追加，无法撤回一条。该运行还对 8 个研究版本完成 11 次文档缺项识别模型响应，第 2 至 5 版各形成一次覆盖拒绝。原始用户结果仍为 `0/1`，不能仅凭这些局部事实断言任一机制是未收敛的唯一原因。[正式结果](../evals/02-current-case-inventory.md#2026-09-29-拆分与复合识别停用对比)与[逐项审计](../../.tmp/claim-no-compound-20260929/duplicate-addition-audit.json)保留原始边界。

按用户要求，当前目标代码给研究写作者增加 `delete_claim`，并从研究检查序列与普通 Final Verifier 同时移除独立文档缺项分类。来源支持、研究事实覆盖、独立汇总和最终语义核验继续按现行责任执行。此次组合改变两个机制，因此后续同入口运行只报告用户结果与调用事实，不将成本或质量差异归因于某一个机制。

## 责任主体与唯一契约

研究模型根据用户目标、当前完整集合、已读证据及最新反馈选择是否撤回、撤回哪一条。`ResearchSubmission` 只接受当前 `base_ref` 与一个 `claim_id`；`Conversation.admit_claim_change` 是唯一写入口，确定性校验目标存在、版本未过期、删除后至少保留一条，然后生成下一版 `ResearchClaims`。其他 claim 的身份、正文、引用及顺序保持，历史版本和已发生的核验意见不改写；新版本必须重做来源支持与事实覆盖。不能通过删除逃避用户仍需的事实，遗漏由研究覆盖和最终用户结果判断。

普通 Final 与研究均不再调用 `interaction_verification.document_absence`，`DocumentAbsenceReport`、`SourceCoverageRejection`、专用反馈 Prompt 和仅用于绕过该拦截的 `evidence_sufficiency` 字段同步移除，不留生产开关或兼容入口。执行系统仍投影实际读取状态供普通整体语义核验使用，但读取不完整本身不再触发独立分类拒绝；外部事实仍须由实际提交的来源支持，不能把“未见”无据扩大为“全文没有”。

## 机制依据与复杂度说明（Complexity Justification）

新增的是一个已有研究动作协议内的 typed 操作，没有新工具服务器、Port、持久化事实或第二写入口。[LangGraph 官方 `RemoveMessage` 与 `add_messages` 实现（提交 `07b33185`）](https://github.com/langchain-ai/langgraph/blob/07b33185eab893be2ed031eedae52f09314bf77c/libs/langgraph/langgraph/graph/message.py)按对象 ID 从当前状态移除，未知 ID 报错；[OpenAI Conversations API 的单项删除契约（2026-09-29 查阅）](https://developers.openai.com/api/reference/ruby/resources/conversations/subresources/items/methods/delete)要求会话 ID 与 item ID。两者是独立 A 级机制坐标，只支持“指定当前作用域内的对象身份并由状态 owner 执行删除”的边界，均不决定本工程哪条论断应撤回。本工程沿用现有 `ResourceRef`、稳定 `claim_id`、Journal 与自动复验；不移植消息 reducer、远端删除 API 或物理删除历史。

相对原生产链，同步删除独立缺项模型调用、对应报告和反馈分支，以及无人消费的取证充分性字段。独立缺项机制曾在历史正式任务实现“未读完拒绝、补读后重验”的局部检查点，[ADR 0021](0021-separate-document-absence-from-reading-coverage.md)和 [ADR 0027](0027-model-owned-evidence-sufficiency.md)保留那段事实；本次停用不把历史证据改写为无效。风险是未读完来源的全文缺项表述不再有专门的读取覆盖拦截，须观察逐项支持与最终核验是否仍拒绝无据保证。

## 验证、风险与退出条件

[预声明](../../.tmp/claim-delete-no-absence-20260929/plan.json)选择原中文 `test_conversation_research_review_001`，固定用户输入、身份、初始事实、正式 HTTP 入口、真实模型与服务提供方、预算、评测器及超时。成功只计完整有据答复通过用户结果评测；`limitation`、超时或缺报告均计失败。局部检查点单独核对实发 Schema 含 `delete_claim`、独立缺项调用为零；若模型自然选择删除，核对当前版本目标消失、其余项保真及新版复验。模型未选择时记录未到达，不注入动作制造 E2E 通过。旧运行与新运行是独立随机轨迹，不作为单变量消融。

[实际 target](../evals/02-current-case-inventory.md#2026-09-29-单条撤回与独立缺项识别暂停的正式-target)为 `0/1`：入口等待 7,200 秒超时，未交付。实发 Schema 包含 `delete_claim`，独立缺项分类响应为 0；模型未提交删除，第 19 版最后 8 条 claim，无法验证自然撤回及新版复验。第 18 版七条逐项来源支持全部通过，事实覆盖发现架构页官方 URL 缺口；模型回到工具阶段补证，第 19 版重验仍未完成。缺项分类停用后的无据全文否定保护因 Final 未到达而未验证。此结果只确立生产接入与已到达检查点，不能宣称候选解决未收敛或可发布。

本轮只跑一个原子 E2E，成本上限为正式配置 2,000,000 tokens 加在途超额与 7,200 秒入口等待；超过该范围不追加样本。若删除动作引入丢失用户必需事实、跨版本误删或绕过复验，撤回删除动作；若停用缺项分类导致无据全文否定交付，重新评估缺项责任边界。若原阻塞仍复现，保留失败并重新设计，不追加同义 Prompt 或预算补丁。此组合在完整用户结果和必要反事实成立前保持待验证，不得声明收敛问题已解决或可发布；目标复核日期为 2026-10-05。
