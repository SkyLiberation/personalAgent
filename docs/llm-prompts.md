# LLM Prompt 与决策边界

**Prompt Registry 只拥有可复用的版本化提示模板，不拥有业务事实、权限、执行结果或完成结论。** 文本事实源位于 `kernel/prompt_templates/`；调用方通过 `kernel.prompts.get_prompt()` 读取 `PromptSpec(name, version, output_contract, template)`。

## 当前 Registry

| Prompt | 生产消费者 | 输出边界 |
| --- | --- | --- |
| `answer_generation.system` | Conversation runtime LLM | 约束模型回答风格；最终回答仍由 Agent loop 与 Completion Gate 接受 |
| `evidence_rerank.system/user` | Evidence reranker | 只排序已有 evidence id，不创造证据或写入知识 |
| `react.system` | 受限 ReAct 执行 | 只能在本轮 allowlist 与预算内提出 ToolCall |
| `structured.system:v2` | JSON Object structured model adapter | 用中文分区要求返回一个符合调用方 Pydantic Schema 的完整 JSON 对象，不定义业务语义 |
| `structured.repair.system:v1` | structured model 的唯一一次 parse repair | 携带 typed validation feedback 与同一 Schema，要求完整重写并禁止改贴枚举制造通过 |
| `delete_candidate_resolve.user` | 删除候选解析 | 只能选择已有候选 id，不能执行删除 |
| `solidify_draft.user` | Conversation solidify | 只形成待准入草稿，不能直接写长期知识 |
| `graphiti.custom_extraction` | Graphiti adapter | 约束外部图谱抽取，不替代 Personal Knowledge admission |
| `interaction_verification.system:v4-cited-evidence` | Conversation Runtime Verifier | 中文判据与 JSON 数据边界；逐项产生 typed 判断，工具校验完整性并聚合 |
| `interaction_verification.source_support:v1` | 同一 Verifier 工具 | 固定加入的独立来源支持标准，不能由回答模型选择省略 |
| `interaction_verification.cited_support:v2-call-bound-unit` | 同一 Verifier 工具 | 逐段识别支持缺口；代码绑定待修订段落，模型不再复制原句；拒绝回原循环 |
| `conversation.action:v17-no-absence-gate` | Conversation Action 阶段 | 组装能力、预算、工作清单及任务中性的验收条件，不从条件推导任务类型 |
| `conversation.final:v20-no-absence-gate` | Conversation Final 阶段 | 生成 typed `FinalSubmission`，提交完整稿或基于最新基稿的修改；引用统一为文档行坐标，允许已完整返回的连续行范围，区分网页正文与工具结果；保留提交前自检，合成后继续完整核验 |
| `conversation.plan_context:v1` | Action / Final Context | 按 canonical 进度生成中文计数说明与 JSON 数据，进度不代表交付 |
| `conversation.working_plan.description:v1` / `conversation.prepare_final.description:v5-source-entry` | 原生控制动作定义 | 区分可修订进度与显式交付请求，不替代 Admission |
| `conversation.requirements:v1-task-neutral` | 上述两个阶段 | 将冻结条件作为 JSON 数据投影，不宣称待改正文或证据已经提供 |
| `web_search.description:v2-discovery-only` | `web_search` 工具定义与模型能力投影 | 只发现标题、URL 和摘要，不自动抓取正文，不规定查询或答案 |
| `conversation.read_artifact.description:v1-plain-lines` | 正文读取能力投影 | 按正文行与行数读取，明确超长行续读与覆盖边界 |
| `conversation.search_output.description:v2-plain-lines` | 正文搜索能力投影 | 字面或正则匹配，返回同一正文坐标；搜索完成不等于全文已读 |
| `web_read.description:v4-plain-source` | `web_read` 工具定义与模型能力投影 | 读取指定 URL 的提取正文；说明不可信边界、已有引用重读、字面匹配和失败语义 |

`structured.system:v2` 与 `structured.repair.system:v1` 是 MiMo JSON Object Adapter 的 transport instruction；Prompt 名称和版本进入模型 request metadata，Pydantic output type 仍是唯一 Schema owner。Conversation Verifier 已替换旧英文正文和标题拼接输入，接入中文来源支持判据与 JSON 序列化；主模板版本和固定支持标准版本均进入请求。此次是行为变更，不能声称字节保持；已知语义缺口及验证范围见 [ADR 0020](adr/0020-require-conversation-source-support-verification.md)。MiMo transport 的准入依据见 [ADR 0007](adr/0007-structured-output-transport-capability.md)。

当前工作树的 Conversation 主模板及 request version 由同一 Registry 条目拥有，调用方只组装动态输入。
2026-09-21 按用户明确要求保留已试验的证据自检版本，替换原笼统检查句，不新增模型调用或改变核验门禁。两份历史输入的局部修订只有 1/2 通过，保留代码不代表该版本已达到修复或发布门槛；证据和后续反馈输入审计见[修订记录](optimization/revision-feedback-loop.md#125-保留自检与最新反馈的输入审计)。
第 108 节整体调整 Plan 生命周期，Action 中文分区表达创建、可修订进度、执行、拒稿恢复与显式 Final；Final 通过同一 Plan Context 获取进度，正文引用协议保持。动态计划说明和控制动作描述迁入 Registry，详见 [Plan 修正记录](optimization/revision-feedback-loop.md#108-plan-生命周期整体修正)。历史自然语言覆盖反馈见[缺项记录](optimization/document-absence.md#105-用自然语言解释未完整读取与修订边界)；当前生产链已停用该独立分类与反馈分支。
当前搜索与读取共享原文行号，Action 与 Final 的逐行引用使用文档号与原文位置；Final 保留原生正文段。局部支持模板与修订环继续保留，读取机制见 [ADR 0024](adr/0024-plain-source-tools-and-inline-citations.md)，引用替换及 Offline 验证边界见 [ADR 0030](adr/0030-document-line-citation-identity.md)。旧读取描述仅随暂留实现保留，不进入模型能力投影。既有验收边界修复见
[当前评测用例盘点](evals/02-current-case-inventory.md#验收条件不再推导改稿任务的边界修复)，产品验收尚未完成。
尚未实质修改的 grounding judge 与领域 extraction 提示仍在各自 owner 内组装；后续触达时必须按
[代码组织与实现约束](devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)迁入 Registry，不能继续新增内嵌正文。

## 变更门禁

- 修改 Prompt 必须同步检查其 schema、validator 与唯一生产消费者；零消费者 Prompt 直接移除。
- 模型输出必须经过 typed parse 与所属 Application/Domain 的 deterministic admission。
- Prompt 测试只证明模板契约；产品效果必须由自然输入的 E2E 或语义 Eval 证明。
- 版本变化按现行规范执行注册与类型静态检查、真实失败输入的 Offline Eval 及受影响的 E2E；不维护或运行 `tests/`。

## Conversation 研究相位

`conversation.research.writer` 为 `v7-delete-claim`，`conversation.research.coverage` 为 `v3-fact-scope`，`conversation.research.final_verification` 为 `v2-stage-feedback`，`conversation.research.synthesis/faithfulness` 为 v1。研究写作者、整组事实覆盖、最终 Verifier、独立汇总和最终忠实性标准分别消费这些模板。事实覆盖只判断 claims 的事实充分性，不判断来源 URL 是否存在或是否写入答案；运行系统将已引用来源 URL 确定性投影给独立汇总。写作者在资料不足时选择继续取证，创建论断时提交非空集合与对象引用；已有集合时可通过 `delete_claim` 撤回单条论断，准入仍要求剩余集合非空并自动重验。当前生产链不注册复合论断识别、文档缺项分类或覆盖反馈 Prompt，也不向研究写作者提供 `split_claim`。来源支持继续复用原注册模板；实际职责与验证范围见 [ADR 0032](adr/0032-conversation-research-claims.md)及 [ADR 0033](adr/0033-claim-deletion-and-document-absence-pause.md)，正式结果由[评测登记](evals/02-current-case-inventory.md)记录。
