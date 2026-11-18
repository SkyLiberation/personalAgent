# ADR 0031：完整基稿上的局部修订

2026-09-20 至 21 日决定。普通回答的局部合并于 2026-11-03 被 [ADR 0049](0049-answer-regeneration-in-original-loop.md)替代。完整稿交接继续服务现行回环。

## 背景与原决定

真实研究拒稿后，逐段引用关系未进入下一次请求，重新成文会遗漏上一稿依据；追加保留提示也未补齐。候选用原 Journal 保存完整 `SubmittedFinal`，模型只对最新基稿提交 `FinalRevision`，代码原子合并并拒绝过期版本、越权或无效引用。合成稿进入原核验，未改段落也随整稿检查。取舍是复用现有不可变引用和回执，避免模糊替换或独立草稿存储。[历史设计](../optimization/revision-feedback-loop.md#121-修订引用保留约束与完整稿合成边界)

## 历史验证与退出

四次 Offline 模型检查共 175,278 tokens，完整基稿交接和局部合并检查成立。原正式 E2E 在九稿进入核验后因服务方 429 失败，未取得用户结果，也未记录各稿修订种类。完整交接单独保留，普通回答改由同一原生循环完整重提。[完整交接固化](../optimization/completed/complete-rejected-draft-handoff.md) · [原评测结果](../evals/02-current-case-inventory.md#完整基稿与局部修订的验证)
