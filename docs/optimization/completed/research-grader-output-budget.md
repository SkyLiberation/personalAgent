# 研究独立评分器的思考与输出预算

**已修复 `RESEARCH-ANSWER-GRADER-OUTPUT-001` 的真实输入截断：正式 E2E 共用的评分请求将输出额度由 1200 提高到 32768，保留 thinking。** 该预算修复版本为 `research-answer-task-support-zh-v6-thinking-budget`，当时 Prompt、Schema 与 `passed` 合并条件保持；现行 v8 继续使用相同输出额度，评分机制由[目标映射与依据归属](research-grader-qualification.md)拥有。

## 问题与生产消费者

原正式研究入口已经返回答案，v5 评分器使用开启 thinking 的同一模型配置，但仍保留 1200 输出上限。三次外层尝试及各一次内部修复共六份响应全部 `length`、正文为空，没有可消费的评分。评分器由 `evals/e2e_quality/research_answer_outcome.py` 拥有，真实 Product E2E 的 `run_research_scenario` 在正式入口返回后调用它；评分只判断原用户请求、用户可见答案和场景参考资料。

输出预算一次替换，模型、transport、thinking、重试和超时保持。版本随请求归档，旧评分结果保持原身份。没有新增运行开关、模块、字段或生产结构。

## 决定性证据

2026-10-01 [真实原请求恢复](../../../.tmp/research-grader-budget-20261001/audit.json)确认完整 SDK 参数只有 `max_completion_tokens: 1200 → 32768` 不同。原用户、原答案、原参考集、Schema、通用 Prompt、Adapter 前缀及其他 kwargs 相同。一次实际 Provider 请求正常 `stop`，形成合法 typed 判决，无重试；原始 reasoning 保留。该样本证明给定真实输入的预算恢复，属于评分责任边界诊断，不计新的 Product E2E。

此次有效判决为未通过；判据审查及评分器资格由[固化记录](research-grader-qualification.md)拥有，正式原 E2E 仍为 `0/1`。成本与实际命令由[评测记录](../../evals/02-current-case-inventory.md#2026-10-01-独立评分器输出预算恢复)拥有。

## 失败尝试与重新打开条件

原机制在适用于开启思考的模型上继续使用短输出额度，重试和格式修复也重复同一上限，六次均无正文。现行请求为思考和合法评分正文预留同一有界额度，实际消耗按 Provider 响应记录。

若当前真实请求再次因本额度耗尽而无合法评分，或正式消费者没有使用当前预算，则重新打开该问题。样本规模和其他模型的可完成性按各自真实输入验收；质量分数另按评分资格处理。经验入口见[预算应覆盖实际思考模式](../../interview/10-development-pitfalls.md#12-评分预算应覆盖实际思考模式)。
