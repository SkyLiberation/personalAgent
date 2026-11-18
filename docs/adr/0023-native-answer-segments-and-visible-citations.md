# ADR 0023：正文分段与引用共同提交

有序正文分段保留。旧可见目录编号先后由 [ADR 0024](0024-plain-source-tools-and-inline-citations.md)和 [ADR 0030](0030-document-line-citation-identity.md)更新。当前答复入口见 [ADR 0055](0055-unified-conversation-answer.md)。

## 背景与决定

[ADR 0022](0022-conversation-owned-citations-and-support-repair.md)的逐字引用候选在正式路径反复把来源原文错填到草稿定位字段。改为 `FinalMessage.segments` 保存唯一正文，`message` 从有序分段拼接。生成器选择已公布的可见证据，绑定器从当次输入恢复原文。该分工消除了重复正文和模型计算定位的责任。[现行结果类型](../../src/personal_agent/application/conversation/models.py) · [引用编号](../topics/context-engineering.md#可见证据的随文引用编号)

当时的目录由现有输入重建，未形成另一个持久事实。采用 Claude Citations 和 Gemini grounding 的分段与引用分工。引用合法性由代码检查，事实支持由适用核验判断。[设计对照与历史结果](../optimization/answer-object-mismatch.md#95-原生正文分段与引用交接验证)

## 历史验证

离线五稿合法交接。正式五稿中两稿进入前置核验，三稿引用非法，局部支持检查未到达。原运行由操作者停止，未交付。保留无重复正文的提交决定，旧目录表示随坐标契约退役。
