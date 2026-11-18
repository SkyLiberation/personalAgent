# ADR 0032：Conversation 研究论断与最终回答的历史决定

2026-11-15 由 [ADR 0055](0055-unified-conversation-answer.md)替换。Conversation 专用的选证、论断写作、修订和结果核验已退役。

## 历史决定

原研究循环将选证、版本化论断与来源核验接到同一个 Conversation Journal。模型根据已读资料和反馈修订；准入原子校验同版正文与引用。曾使用逐项来源支持、事实覆盖与独立汇总。2026-10-16 改为同一版本同时提交论断和可选 `final_answer`，统一核验当前版本与完整回答，移除独立 Coverage、synthesis 和研究专用 Final。只在决定性输入均相同的情况下复用适用报告，复用仍绑定原稿。原阶段协议、预算和回放由[研究规格](../optimization/to_verify/research-goal-coverage.md#2026-10-15-sourcecoverage-与-final-合并设计)保留。

该机制复用原 Artifact、Journal 和交付入口。选证、论断语义与稿件归模型，引用与版本准入归 Runtime，语义判断归 Verifier。使用成功读到外部正文作为阶段入口后来使部分普通文件交付走入研究支线，是退役的实际依据之一。[退役依据](0055-unified-conversation-answer.md)

## 撤回反复结构放行的前置门禁

同一实发请求出现相反的复合结构判断，旧门禁要求所有论断先被放行，阻塞实际来源核验。诊断主动停止，未交付。后继仅对实际来源拒绝追加结构诊断，随后在 2026-09-29 同时停用拆分和复合识别。两条正式运行的原用户结果均为 0/1。另一次重复追加揭示单条论断撤回的独立需求。[未收敛问题](../optimization/claim-revision-nonconvergence.md) · [后续决定](0033-claim-deletion-and-document-absence-pause.md)

## 验证、风险与退出

原 10 月正式流程在服务方拒绝和恢复交付字段缺失后各保留 0/1，修复后同一正式任务续验 1/1，确切正文、统一报告及独立评分通过。来源引用恢复、无损修订和反馈范围的局部结果分别保留。该次正式结果属于旧研究协议。[正式结果](../evals/02-current-case-inventory.md#2026-10-16-统一研究与最终回答的正式验证) · [来源支持取舍](../optimization/completed/source-proof-boundary-isolation.md) · [原子论断修订](../optimization/completed/claim-atomic-evidence-revision.md)

旧会话与轨迹按原版本解释。统一答复使用新运行身份；独立检索实验、周期研究与知识库论断仍沿各自契约。
