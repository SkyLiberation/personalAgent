# 最终验收项通过引用恢复原文

## 问题与结论

**`FINAL-CRITERION-TRANSCRIPTION-001` 的身份绑定问题已解决：模型返回当前验收项 ID，Runtime 恢复原文并形成回执。** 普通与研究最终核验采用同一契约；正式路径已消费一次真实模型报告到 Completion。原用户 E2E 的语义评分仍失败，完整结果由[评测登记](../../evals/02-current-case-inventory.md#2026-10-02-验收项引用恢复的正式验证)拥有。

旧契约要求模型重抄验收项全文，再以字符串集合证明身份。2026-10-01 两份正常 stop 报告分别漏句号、改写“不得混为一谈”，第三份才形成回执，见[历史边界](../../../.tmp/research-source-reuse-repair-20261001/final-boundary-audit.json)。2026-10-02 同入口五份合法 JSON 报告均漏忠实性标准的句号，第五份还将“解释工具由谁选择和调用”改写；五次全部被拒，32 回合返回 limitation。前四份原始状态全部 satisfied，第五份含一项 insufficient_evidence；这些状态均不是有效通过事实，见[原始输入审计](../../../.tmp/mimo-provider-diagnostics-20261002/input-audit.json)。

## 方案、责任与生产消费者

Goal 与系统支持标准拥有原文。Runtime 合并去重本次标准，按原顺序派生只读 `VerificationCriterion`，其中 `criterion_id` 仅在当前请求有效；模型仍读取完整原文，输出 ID、原三态与反馈。动态 Schema 枚举当前 ID 并限定结果数量；工具检查每项恰好一次，从同次权威输入恢复正文，形成 `BoundVerificationCriterionResult` 和 typed 回执。未知、缺失及重复 ID 在输出校验或工具绑定边界拒绝，产生零有效回执。

原用户标准 digest、完整稿 digest、研究版本、状态聚合与失败反馈交接保持。实际消费者为 `observed_receipts` 和 Conversation 的同稿、同研究版本 Completion 检查。当前接口由[核验专题](../../topics/verification-and-completion.md)拥有；所有模型搬运已有具体文字的通用设计规则由 [COD 文本引用规则](../../devSpec/code-structure.md#21-已有文字通过引用传递)拥有，根入口、CTX 和 Prompt 模块链接该规则。

生产改动为四个文件，新增 71、删除 23、净增 48 行。新增两个不可变契约类型，分别表达权威原文投影与 Runtime 绑定结果；每次调用派生两个临时 Schema。删除模型结果的 `criterion` 全文字段、全文集合匹配和两份 Prompt 的重抄指令；普通最终 v5、研究最终 v3 沿现行装配调用，无新模块、Port、持久化、开关或模型阶段。

## 决定性证据与适用范围

按[封存计划](../../../.tmp/final-criterion-reference-20261002/plan.json)固定模型、thinking、JSON Object、480 秒超时、原研究/来源/覆盖/评分和暂停机制。五份历史报告各回放一次，三个真实模型局部样本各一次，原中文 HTTP E2E 一个样本一次；没有补齐正式中间结果或追加付费样本。

| 证据 | 实际结果 |
| --- | --- |
| 同五份真实报告的绑定反事实 | 旧绑定 0/5，ID 绑定 5/5；只置换原项位置身份，正文、资料、状态与反馈保持。前四份聚合 passed，第五份仍 failed；付费调用 0，见[回放](../../../.tmp/final-criterion-reference-20261002/offline-candidate.json) |
| 遗漏、重复、未知 ID 控制 | 三类全部拒绝，零有效回执；缺项/未知由当前 Schema 拒绝，重复由工具完整集合检查拒绝 |
| 三个固定历史输入的真实模型 Offline Eval | 绑定 3/3，实际输出直接进入生产工具；普通稿连续经过原来源支持。4 份物理响应、30,804 tokens、133.625 秒，见[实发审计](../../../.tmp/final-criterion-reference-20261002/live-input-audit.json) |
| 原正式入口的自主模型轨迹 | 一次最终报告只输出 r1–r10；十项原文精确恢复，同稿及原标准 digest 保持，canonical 回执消费者接受，第 19 版研究引用到达 Completion，返回同一 answer。检查点 1/1，见[引用审计](../../../.tmp/final-criterion-reference-20261002/reference-audit.json) |

本轮真实历史第五稿的新判决变为全部满足，原来不足意见及固定反事实的拒绝均保留；两次独立采样的语义差异没有被改写为身份机制收益。原正式 E2E 返回答案后由独立评分拒绝，问题及输入差异见[语义审查](../../../.tmp/final-criterion-reference-20261002/semantic-review.json)。原始代码、请求、响应和检查由[本轮报告](../../../.tmp/final-criterion-reference-20261002/REPORT.md)封存。

## 失败尝试汇总

旧全文复制契约将模型的同义改写与漏标点转化为整份核验失效，真实报告及同输入回放已证明责任边界。此前五次正式重提均未解除该要求；本轮以身份引用替换复制职责，没有增加同义提示或归一化正文。准备时发现旧普通样本使用已撤回的 Observation 形状，在零付费调用时改用现有 bounded-unknown 历史输入，原稿、标准和实际摘录保持，见[准备调整](../../../.tmp/final-criterion-reference-20261002/preparation-adjustment.json)。

## 重新打开条件

当前合法报告恢复出另一验收项正文，未知/重复/缺失 ID 形成有效回执，或回执绑定到错误稿件、标准及研究版本时重新打开本问题。开发经验见[让模型判断、代码关联原文](../../interview/10-development-pitfalls.md#7-让模型识别问题让代码关联原文)。
