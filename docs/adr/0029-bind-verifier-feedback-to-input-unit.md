# ADR 0029：核验意见绑定调用中的草稿单元

## 背景

**模型对问题的识别不应依赖再次逐字抄写草稿。** 正式 E2E 已出现四次引句绑定失败；历史原始报告证明，删除反引号会使整份报告退化为通用参数错误，合法意见也无法送达。实际模型输入包含原稿及抄写指令，失败事实不支持再追加同义 Prompt。

## 决定与责任主体

既有工具一次只核验一个 `CitedDraftUnit`，因此删除模型输出的 `draft_quote` 和精确子串分支。模型继续输出 `evidence_ids` 与 `exceeded_scope`，说明本段哪个论断超出证据。工具把该次输入的 `unit.draft` 写入 `CitedSupportRejection.checked_draft`，与原完整拒稿正文及意见一起交给原 Conversation 修订循环。

草稿事实由本次提交拥有，核验工具拥有调用关联；来源事实仍由执行记录与引用物化拥有，模型只决定支持关系。新稿重新绑定，局部证据编号不能跨核验单元解释。合法引用不能证明语义正确；空发现继续原整稿核验，不直接交付。

完整证据不再次装入拒稿反馈。历史输入中存在超过 37,000 字符的单元，重复回传可能触发现有 20,000 字符 Observation 卸载。当前反馈仅增加精确段落，原文与来源继续由已有可见证据提供；不新增持久化、预算例外或隐藏恢复路径。

## 外部依据与复杂度

两个 A 级来源已于 2026-09-18 核对：[Claude Citations](https://platform.claude.com/docs/en/build-with-claude/citations#how-citations-work)按文档位置直接提取原文；[Gemini CLI 搜索工具](https://github.com/google-gemini/gemini-cli/blob/3c311beac2e78336816dd4a123db39743f9fbf85/packages/core/src/tools/web-search.ts#L94-L163)在固定提交 `3c311beac2e78336816dd4a123db39743f9fbf85` 中消费引用索引并由代码生成标记。采用的是引用定位与文本恢复分工，不照搬其模型、搜索或专有接口，也不以外部机制证明本工程收益。

Complexity Justification：3 个生产文件、零新类、零新调用、零新存储。移除模型抄写字段与匹配分支，增加一个代码绑定字段，Prompt 升为 `v2-call-bound-unit`。实际消费者为既有反馈 Observation 和 Conversation 输入物化。不增加草稿分句、模型计算偏移、重试器或兼容双轨；历史源码只留在独立归档。

## 证据、风险与退出条件

本轮适用证据为历史失败回放、固定中文真实模型 Offline Eval，以及原正式研究 E2E。运行前判据与预算见[预声明](../../.tmp/verifier-unit-binding-20260918/plan.json)，输入体积修正见[补充审计](../../.tmp/verifier-unit-binding-20260918/plan-amendment.json)。执行结果由[问题记录](../optimization/completed/verifier-finding-binding.md)拥有，完整用户结果由[评测登记](../evals/02-current-case-inventory.md)拥有；局部反馈交接取得正式观察，但原 E2E 人工中断且完整运行归档不全，不声明产品完成或发布资格。

段落较长时，模型的问题说明仍可能含混或误判，不能把结构成功算作语义通过。非法证据 ID 保持拒绝，本轮不扩展通用协议恢复。若当前段落绑定、意见交接或有据／无据控制出现候选因果回归，撤回相应候选；后续独立产品失败与本局部检查点分别记录。
