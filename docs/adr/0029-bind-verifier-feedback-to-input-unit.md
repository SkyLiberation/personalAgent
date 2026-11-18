# ADR 0029：用本次核验输入绑定反馈原段

## 背景与决定

正式运行出现四次引句绑定失败。模型删除 Markdown 反引号会让意见在参数校验处丢失。历史逐段来源核验一次只评一个草稿单元，故删除输出中的 `draft_quote`，由工具将本次原段与模型意见绑定。模型负责语义及证据选择，工具恢复原文，原循环消费拒稿，避免增加存储或带回完整证据副本。

Claude Citations 和 Gemini CLI 的既有引用实现支持定位与文本恢复分工。历史机械回放及真实局部核验取得反馈交接证据，原 E2E 人工中断且归档不全。后续 claim 相关核验随 [ADR 0055](0055-unified-conversation-answer.md)退出，绑定已有文字的设计原则由[文本引用规则](../devSpec/code-structure.md#21-已有文字通过引用传递)维护。[问题与结果](../optimization/completed/verifier-finding-binding.md)
