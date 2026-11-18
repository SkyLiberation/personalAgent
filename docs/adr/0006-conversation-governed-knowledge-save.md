# ADR 0006：Conversation 内受治理的知识保存

2026-07-28 决定。当前保存入口由 Conversation 负责确认和恢复，Personal Knowledge 负责写入知识。[工具与授权专题](../topics/tools.md#gateway幂等与审计)

## 背景与决定

B01 中，模型能请求用户确认，但系统没有待确认状态，用户回复后无法继续。相同材料经显式固化入口可写入知识。修复需要接通确认协议。

模型选择用户消息中的知识原文。Conversation 校验来源角色和逐字匹配，冻结主体、来源及内容，生成待确认 Command。Journal 保存确认状态及 Receipt。确认后调用 `KnowledgeService.solidify_conversation`；拒绝或错误作用域无写入，成功后的重复确认复用原结果。现行入口使用 Turn 身份绑定确认。[Web 路由](../../src/personal_agent/adapters/web/routes/conversation.py) · [保存用例](../../src/personal_agent/application/conversation/knowledge_save.py)

采用业务专用 Command 和确认入口，复用既有知识写入。原空转 Procedure 已移除。E14 的结果判据包含确认前零写入、确认后可查到准确知识原文、控制语义不入知识及重复确认不重写。

## 历史验证与例外

B01、语义基线及早期 E14 target 的归档分别为 `20260728T083321.588087Z-48120-2ce6f484`、`20260729T031804.415533Z-15972-214cb81c`、`20260729T033339.065714Z-22692-16415241`。当时的实验例外截止于 2026-08-28；该日发布矩阵中，E14 因缺少待确认结果而失败，发生在专用追踪封存前。本 ADR 记录历史准入与当前代码事实，发布结果以评测记录为准。[历史评测盘点](../evals/02-current-case-inventory.md)
