# ADR 0033：论断单条撤回与独立文档缺项识别停用

2026-09-29 决定。独立缺项分类保持停用，单条论断撤回随 Conversation claim 路径在 2026-11-15 退出。[现行答复契约](0055-unified-conversation-answer.md)

## 背景与决定

当时的正式用例未交付，研究稿从 11 条增至 22 条，其中六条新增项与已有项完全相同。另有四个版本触发独立覆盖拒绝。同一组证据支持检查两条责任边界。[原正式结果](../evals/02-current-case-inventory.md#2026-09-29-拆分与复合识别停用对比)

原 `delete_claim` 让模型选择当前版本的一条论断，由 Conversation 校验 ID、版本及剩余项数，再原子提交并复验。原写入口和历史记录保持。采用按当前作用域对象身份更新的方式，参考 LangGraph 与 OpenAI Conversations 的删除契约。该历史动作已随旧研究状态退役。

移除独立缺项分类、读取覆盖拒绝、反馈模板及专用充分性声明。实际读取和引用继续以执行事实为准，适用的来源支持与整稿核验仍须拒绝无据全文否定。[原覆盖机制](0021-separate-document-absence-from-reading-coverage.md) · [原充分性声明](0027-model-owned-evidence-sufficiency.md) · [现行核验](../topics/verification-and-completion.md)

## 历史验证

同一正式 target 等候 7,200 秒后超时，0/1。请求已含删除动作，独立缺项分类零调用。模型未选择删除，Final 未到达，因此自然撤回、新版复验与整稿缺项保护均未验证。该轮同时更改两项机制，原结果保留原身份。[正式 target](../evals/02-current-case-inventory.md#2026-09-29-单条撤回与独立缺项识别暂停的正式-target)
