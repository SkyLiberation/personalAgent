# 已解决问题与固化方案

本目录按具体问题保存已成立的方案、证据范围和失败尝试摘要。完成文档不保存中间流水，也不表示相关产品的全部门禁已经通过。规则由 [optimization 索引](../README.md#已解决问题的固化规则)唯一维护。

| 已解决的问题 | 固化记录 |
| --- | --- |
| DeepSeek 思考模式拒绝强制工具选择，内部动作义务仍须保持 | [Provider 编码与严格动作解码](deepseek-thinking-action-choice.md) |
| Coverage 的引用存在性在结构恢复后才检查，非法坐标触发入口 422；局部恢复 2/2 已接入 | [同一 typed 校验与有界引用恢复](coverage-reference-recovery.md) |
| 来源模型借用未绑定原文支撑引用，或误判已返回证据缺失；统一六类已接入 | [统一核验的证据边界与历史取舍](source-proof-boundary-isolation.md#统一核验的局部问题关闭) |
| 来源支持把未排除的相邻关系当必要疑点，或把全部返回资料代替本条引用 | [证据用途与必要澄清](source-evidence-purpose.md) |
| 来源核验混淆引用子集、返回全集与稿件限定范围 | [引用支持与实际返回范围](source-cited-returned-scope.md) |
| 来源反馈扩大性质或字段身份，类别正确却说明失真 | [来源核验的直接分类与反馈忠实性](source-feedback-classification.md) |
| 可读性优先级与 Code Agent 局部阅读边界未明确，模型响应解析与调用装配混装 | [可读性优先与功能模块化](code-readability-modularity.md) |
| 无研究稿时选证Schema允许无效answered身份 | [按实际状态呈现选证契约](research-selection-state-contract.md) |
| 目录拒绝抢先绕过反馈、非法 JSON 没有进入已有一次纠正 | [Conversation 动作协议恢复](conversation-action-protocol-recovery.md) |
| 未声明动作拒绝丢失已知具体名称，且补齐名称须保持原停止额度 | [未知动作名称反馈保真](unknown-action-name-feedback.md) |
| 被拒稿只有正文、缺少逐段引用关系 | [完整基稿交接](complete-rejected-draft-handoff.md) |
| 搜索返回结果时丢失实际查询参数，查询与来源证据混用 | [搜索执行参数的保真交接](query-execution-handoff.md) |
| 验收项重抄漏标点或同义改写导致最终回执被拒 | [最终验收项引用恢复](final-criterion-transcription.md) |
| 模型引句转录差异导致整份核验反馈丢失 | [核验意见绑定当前调用](verifier-finding-binding.md) |
| 同一稿件含多个错误，能否通过逐轮核验和修订处理 | [多错误的渐进核验与修订](multi-error-verification-revision.md) |
| 模型重抄旧正文导致修订目标定位失败 | [Runtime 正文片段寻址](claim-fragment-addressing.md) |
| 研究参数范围未进入实际生产 Schema | [当前可见参数范围](claim-argument-scope.md) |
| 修复耗尽后的外层重试漏掉失败响应用量 | [完整重试用量](model-retry-usage.md) |
| 研究编辑拒绝未返回实际未选证据坐标 | [研究引用准入的确定性坐标反馈](research-admission-coordinate-feedback.md) |
| 正文修订与新增引用无法同次提交 | [正文与新增引用的一次修订](claim-atomic-evidence-revision.md) |
| 正文修订要求重新选择全部已有引用 | [局部修订的引用继承](claim-retained-references.md) |
| 来源核验输入未变却随集合版本重复核验 | [按实际输入复用来源报告](claim-source-review-reuse.md) |
| 独立评分扩大必答项、误读范围或缺少实际引用页面与版本 | [评分目标映射、依据归属及参考资格](research-grader-qualification.md) |
| 研究独立评分器在开启思考时耗尽短输出额度 | [评分输出预算](research-grader-output-budget.md) |

本目录之外的 optimization 文档只保留完成文档的引用，不继续跟踪成功问题。

待优化问题及准入状态见 [Future 队列](../../future/design-optimization-backlog.md)，当前推进入口见[问题总览](../conversation-source-support.md)。
