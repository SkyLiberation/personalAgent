# 研究写作者首次提交的 typed 输出故障

问题编号：`CLAIM-WRITER-TYPED-OUTPUT-001`。归属 [研究论断无法收敛](../claim-revision-nonconvergence.md)，仅处理首次研究提交在结构层失败并使正式入口返回 503 的边界；研究来源支持、事实覆盖和最终交付另行验收。

## 失败事实与责任边界

2026-09-28 原中文任务经正式 HTTP 入口、生产 Composition Root、真实模型和工具运行，结果 `0/1`，约 213 秒后返回 503。[原始模型响应](../../../.tmp/evidence-first-20260928/baseline/model-calls/27908/0008-response.json)提交 `create_claims` 且 `claims=[]`；一次[结构修复响应](../../../.tmp/evidence-first-20260928/baseline/model-calls/27908/0010-response.json)改成多条论断，却把 `references` 写成坐标字符串数组。既有 Schema 已要求 `claims` 非空、引用对象包含 `evidence_id`，两次均被 typed parser 拒绝。首轮模型的可见推理表示需要继续读资料，但不能仅凭推理断定提示是唯一原因。[基线 Trace](../../../.tmp/evidence-first-20260928/baseline/evidence/conversation-research-delivery-001/baseline/20260928T095242.832246Z-7448-4ba3bce0/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)和服务日志保留原始入口失败。

研究写作者拥有在现有资料下继续取证、创建非空论断或如实停止的模型决策；typed Schema 拥有结构拒绝，运行系统不补写论断或替换引用。旧 [Prompt](../../../src/personal_agent/kernel/prompt_templates/research.py) 的“没有集合时用 create_claims”没有明确区分“尚无集合”和“尚无足够依据”，引用说明也只给出坐标形式。

## 已接入的最小修正与连续证据

[预声明](../../../.tmp/claim-writer-contract-20260928/plan.json)仅替换注册写作者 Prompt 为 `v5-typed-claim-submission`：资料不足时选择 `return_to_actions` 并说明缺口，`create_claims` 至少一项，引用按 `{"evidence_id":"d2:37"}` 的对象结构提交。生产消费者仍由 Conversation 正式入口调用；Schema、准入、Verifier、预算和 E2E 用例均未修改。基线与 target 的 400 个代码文件身份只有这份 Prompt 不同，模型、JSON transport 与预算一致。[运行审计](../../../.tmp/claim-writer-contract-20260928/report.json)保留对照边界。

同一正式中文 E2E 的一次 target 为 `0/1`：[完整 Trace](../../../.tmp/claim-writer-contract-20260928/evidence/conversation-research-delivery-001/target/20260928T160958.989865Z-10284-fa6cb576/CONVERSATION-RESEARCH-DELIVERY-001.1.trace.json)记录入口 HTTP 200、四版被接受的 11 条论断、首版 67 个 typed 引用及实际来源核验；原先的首次提交 503 未复现。后续一次空 `add_claims` 被结构拒绝，现有单次修复产生合法 `ResearchSubmission`，流程继续。完整用户结果仍是预算 `limitation`：17 个模型回合、25 次工具调用、794,181 tokens、约 1043 秒，没有最终答案；来源支持与后续取证未收敛。target 未保存逐次原始模型载荷，阶段判断以服务日志和 canonical Trace 为限；两条随机前置轨迹不构成正式消融，也不证明故障概率已归零。

## 未验证边界与下一判据

当前仅证明这次正式运行越过原结构化入口故障，不能宣称研究任务完成或可发布。空 `add_claims` 的恢复已观察到一次，若再次造成未恢复的入口错误，应按其当时的实际模型输入定位同一写作者动作契约，不能把本次恢复外推为稳定性。下一次自然中文同入口验证须预先固定用户结果与局部 typed 提交判据；既要保留任何无效输出和修复轨迹，也要让来源核验、覆盖、汇总与 Completion 连续给出最终用户结果。若反例表明本 Prompt 引入回归或重复首稿结构故障，撤回该候选并重新审查写作者输入与结构修复责任边界；不能通过放宽 Schema 或脚本注入论断制造通过。
