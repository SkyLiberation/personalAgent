# 正文编辑目标由 Runtime 标识与恢复

**已解决 `CLAIM-EDIT-TARGET-TRANSCRIPTION-001`：模型以版本绑定的片段 ID 指定目标，Runtime 从 canonical 正文恢复精确范围并合并。** 本问题是[研究修订未收敛](../claim-revision-nonconvergence.md)的独立定位边界。`ResearchClaims` 保持唯一持久正文；业务 claim 数量和来源核验单位沿用现行契约。

## 问题与采用方案

2026-09-30 正式入口第 5 版 c4 的两次 `old_fragment` 将正文直引号改成弯引号，原样匹配均为 0；完整原文已进入实际请求。最早责任边界是研究写作者的旧字符串目标协议。失败输入与字符审查见[封存审查](../../../.tmp/evidence-first-restored-20260930/target-coordinate-feedback/boundary-review.json)。

Conversation 从当前正文派生临时 typed 片段：从左向右按 `。！？；`、换行切分，连续分隔符归于前段，CRLF 原样保留。空白、引号、代码标记不改写，ASCII 点号不切分，所有片段顺序拼接逐字等于完整正文。ID 为 `cN.fM`；Python 半开偏移由 Runtime 计算，写作输入仅显示 ID 与原文，各 claim 的引用呈现一次。

模型提交完整 `base_ref`、`claim_id`、`start_fragment_id`、`end_fragment_id` 和 `replacement`，指定含首尾的连续范围。准入先核对资源、owner、revision，再核对同一 claim 内的合法顺序，取出原文范围执行 `text[:start] + replacement + text[end:]`。空 replacement 可以局部删除，合并后须保留非空 claim。正文修订保持已有引用，由 canonical citation binder 从实际输入检查有效性；新增引用的选证规则由 Conversation 契约拥有。

过期版本、异 owner、跨 claim、错误或反向地址、夹带旧字段均拒绝且零写入。范围外正文、引用和其他项保持原样。合法修改产生新版后，既有链路完整复验全部 claims 的来源支持与事实覆盖，再进入独立汇总、Final 与 Completion。

## 唯一生产路径

`POST /api/conversation/turn` 经生产 Composition Root 和真实模型进入 Conversation。`research.py` 的 `editable_claim_fragments` 同时服务写作视图与 `admit_claim_change`；`service.py` 在研究写作请求中用片段视图替换整条 text 展示。选证、来源 Verifier 和独立汇总继续消费 canonical 稿。`conversation.research.writer:v11-retained-references` 与 typed action 已迁移，原 `old_fragment` 和字符串匹配分支删除。

临时视图不写入 Journal，恢复从当前稿重建；新增持久业务字段、Port、模型或网络调用为 0，动作净增一个参数。当前引用与身份的 Schema 投影由[参数范围](claim-argument-scope.md)拥有。

## 决定性证据

| 证据 | 成立判据 |
| --- | --- |
| [真实失败边界回放](../../../.tmp/research-convergence-integration-20261001/fragment-replay.json) | 两条原动作保留 replacement 并给定合法 ID 后精确合并；七类拒绝控制零写入；删除地址消费者后同一 ID 动作拒绝。属于给定地址的条件局部证据。 |
| [实发写作输入审计](../../../.tmp/research-convergence-integration-20261001/target/writer-view-audit.json) | 当前视图、完整原文、顺序、身份与实发 Schema 对齐，没有第二份完整正文或模型字符偏移。 |
| [真实模型动作与新版消费](../../../.tmp/research-convergence-integration-20261001/target/admitted-fragment-audit.json) | 实际模型自主提交 ID，生产准入应用；范围外内容、引用、其他项保持，新版进入完整来源核验。 |

原用户结果及模型调用数由[评测登记](../../evals/02-current-case-inventory.md#2026-10-01-重试计量与研究设计接入)拥有，正式归档保持原始结果。

## 机制依据与失败尝试

2026-09-30 核对 [Anthropic citations 官方契约](https://platform.claude.com/docs/en/build-with-claude/citations)及 [CodeMirror ChangeSet 固定源码](https://github.com/codemirror/state/blob/9c801279cb83011e6f92af778f4443406e8f1200/src/change.ts#L188)。前者采用模型位置与执行侧原文恢复，后者消费确定性范围并拒绝越界。本工程以完整版本与主体绑定临时地址，偏移由 Runtime 产生。

| 尝试 | 已证实原因与结果 |
| --- | --- |
| 模型复制完整旧段 | 复制改变引号，原样匹配为 0，修订拒绝。 |
| 模型缩短复制目标 | 同样改变引号，仍未定位；目标长度减少没有解除复制依赖。 |

若同版本视图无法逐字重建正文、错误版本或主体被接受、有效 ID 定位到不同范围，或范围外内容被改写，则重新打开本问题。
