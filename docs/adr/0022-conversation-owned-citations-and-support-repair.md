# ADR 0022：成文引用试接入与逐字复制协议撤回

**状态：候选已撤回，未通过正式交接。** 下文保存曾测试的责任划分；当前生产行为仍由[验证专题](../topics/verification-and-completion.md)拥有。三次原正式任务均在引用协议处终止，未进入局部 Verifier，不将其误写为语义核验反例。

## 背景

整稿审查会把主题相关、示例出现误当成普遍结论得到支持。第 90–93 节已取得局部草稿及对应原文的识别收益；第 93 节额外模型事后补引用仍会漏交相邻条款。用户明确：生成器负责取证和引用，验证器只判断本次提交，缺证后生成器可以补充。漏引不能自动等同拦截机制失败，也不能由验证器再次搜索弥补。

## 决定与责任主体

本轮候选曾进入既有生产构造链；以下协议只存在于本轮封存的目标代码，已从最终工作树撤回。`FinalMessage.message` 仍是唯一正文，`evidence_citations` 由同一次 Conversation 成文提交。每项用逐字、唯一的 `draft_quote` 定位正文，用 `ConversationEvidenceReference(action_id, line)` 引用当前可见成功执行；`line` 只指该次 `read_action_output` 实际返回的行，空值表示整个已物化执行记录。

`materialize_cited_draft` 只恢复提交内容，拒绝不可见、失败、未返回行、错误原句或重叠范围。不自动挑邻片、扩展查询或生成依据，不读取未展示 Artifact。引用多条就传多条，未引用正文保留为空证据单元，是否需要依据由模型判断。引用与正文定位错误作为 `DecisionFeedback` 回到原循环。

既有 `verify_interaction_draft` 保留文档缺项覆盖拒绝，随后用独立窄职责提示检查每个非空白稿段和全部对应依据。无据或过度声明形成 `CitedSupportRejection`，经现有执行网关返回 Conversation，不形成通过回执，也不会继续运行普通审查覆盖该拒绝。模型只报告具体原句和支持缺口，不建议替代事实。

局部未发现问题后，原整稿语义审查仍验收冻结用户标准和固定来源支持项；其执行证据也限于当前引用，不再传入全部成功工具历史。该审查保留既有职责与规则，不由局部空发现替代原用户结果验收。所有判断通过后，原回执继续绑定最终发送正文。补充引用可以保持正文不变，但仍会重新执行验证，不复用旧拒绝作为完成证明。

## Complexity Justification 与迁移

新增类型分别承担成文引用、请求内证据单元及支持拒绝三个边界；`citations.py` 只负责确定性恢复，唯一生产调用者是 `ConversationService._verify_before_send`。工具消费者由原 Composition Root 装配，模型仍经既有 `StructuredModelClient` Port。没有新增补引用模型、Agent、工具、循环、持久化表、配置开关或兼容分支。

旧 `materialize_verification_evidence` 全历史投影入口删除，工具入参的 `evidence_refs/execution_evidence` 改为 `cited_units`，调用者和正式测试同步迁移。普通模型请求中的 `execution_evidence` 是由本次单元确定性构造的临时输入，不是另一份持久事实。缺引用产生空证据待验文本，不退回旧全历史路径。

Prompt 由原 Registry 唯一注册：`conversation.final:v7-writer-citations`、`interaction_verification.cited_support:v1-writer-citations`。整稿模板仅更新输入边界并升至 `v4-cited-evidence`，文档缺项分类保持原规则字节，因输入分布变化升至 `v2-writer-evidence`。输出上限与工具时限保持，实际支持调用数随稿段数变化，首次明确拒绝即返回；后续修订仍由已有循环决定。

## 外部依据

复用第 93 节已核对的两个独立 A 级实现：[ALCE](https://github.com/princeton-nlp/ALCE/blob/59472085253fca560f720051173511b275e6e301/eval.py#L276)按回答引用取对应原文做支持判断，[FActScore](https://github.com/shmsw25/FActScore/blob/f28272deffcf33efc1f1117d5479c10bb75221a9/factscore/factscorer.py#L187)将单项事实与相关原文交给判别模型。只采纳引用作用域与判别隔离，不采用平均分、关键词真假解析或固定分句数量；外部机制不能替代本工程正式验收。

## 证据、风险与退出条件

过程和原始坐标见[第 94 节](../optimization/answer-object-mismatch.md#94-conversation-成文引用与缺证恢复的工程接入)。本轮十次真实模型控制均符合目标边界；187 项 Contract 与回归通过，包括实际 ConversationService 在受控决策下补充引用、保留同稿并重新验证。该恢复测试属于 Runtime Conformance，不能冒称真实模型 E2E。

三次同一原研究任务全部失败，最后一次已扩大到 64 回合与 4M tokens，仍在 22 回合因同类无效引用停止。五稿匹配从 0/6 提升到 5/6，却未完成合法交接；原始结果由[评测盘点](../evals/02-current-case-inventory.md#成文引用与局部支持核验的迁移验证)拥有。

一次有界修正解决了错误反馈缺少失败稿、不同原因被合并计数的部分缺口，未解决完整正文与逐字引用副本不一致。按退出条件撤回本次候选代码和无消费者分支，生产及正式测试回到本轮起点，保留既有覆盖门禁、来源必检和修订循环。候选净增 184 行、最终生产净变化 0；代码身份与原始证据完整封存，没有恢复被否决的事后补引用器。

未采用模糊匹配、静默丢弃错误引用、放行无据正文、增加补引用模型或继续堆复制提示。后续只评估原生成文片段附带引用、正文只保存一次的表达；尚未实现，不能将局部模型收益写成正式用户结果已通过。
