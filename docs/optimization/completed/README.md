# 已解决问题与固化方案

本目录按具体问题保存已成立的方案、证据范围和失败尝试摘要。完成文档不保存中间流水，也不表示相关产品的全部门禁已经通过。规则由 [optimization 索引](../README.md#已解决问题的固化规则)唯一维护。

| 已解决的问题 | 固化记录 |
| --- | --- |
| 目录拒绝抢先绕过反馈、非法 JSON 没有进入已有一次纠正 | [Conversation 动作协议恢复](conversation-action-protocol-recovery.md) |
| 被拒稿只有正文、缺少逐段引用关系 | [完整基稿交接](complete-rejected-draft-handoff.md) |
| 模型引句转录差异导致整份核验反馈丢失 | [核验意见绑定当前调用](verifier-finding-binding.md) |
| 同一稿件含多个错误，能否通过逐轮核验和修订处理 | [多错误的渐进核验与修订](multi-error-verification-revision.md) |
| 模型重抄旧正文导致修订目标定位失败 | [Runtime 正文片段寻址](claim-fragment-addressing.md) |
| 研究参数范围未进入实际生产 Schema | [当前可见参数范围](claim-argument-scope.md) |
| 修复耗尽后的外层重试漏掉失败响应用量 | [完整重试用量](model-retry-usage.md) |
| 研究编辑拒绝未返回实际未选证据坐标 | [研究引用准入的确定性坐标反馈](research-admission-coordinate-feedback.md) |
| 正文修订要求重新选择全部已有引用 | [局部修订的引用继承](claim-retained-references.md) |
| 来源核验输入未变却随集合版本重复核验 | [按实际输入复用来源报告](claim-source-review-reuse.md) |
| 研究独立评分器在开启思考时耗尽短输出额度 | [评分输出预算](research-grader-output-budget.md) |

本目录之外的 optimization 文档只保留完成文档的引用，不继续跟踪成功问题。

待优化问题及准入状态见 [Future 队列](../../future/design-optimization-backlog.md)，当前推进入口见[问题总览](../conversation-source-support.md)。
