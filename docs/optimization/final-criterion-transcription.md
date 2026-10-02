# 最终核验验收项逐字转录失败

`FINAL-CRITERION-TRANSCRIPTION-001` 属于[Verifier 产品问题](../future/conversation-verification-false-positive.md)。2026-10-01 正式研究集合通过后，最终 Verifier 已收到完整 11 项 criterion，却在首份报告漏抄忠实性条目的句号，在第二份报告把“不得混为一谈”抄成“不得混为谈”。两份合法 JSON、正常 `stop` 均被 `tools/interaction_verifier.py` 的字符串集合一致性检查拒绝，语义反馈没有进入正常修稿交接；第三份才形成有效通过报告。证据见[实际最终边界](../../.tmp/research-source-reuse-repair-20261001/final-boundary-audit.json)。

## 责任与设计方向

Goal 拥有验收项内容；Runtime 拥有项身份、当前调用绑定和唯一覆盖；模型判断满足程度及语义反馈。下一候选让模型返回当前调用的 criterion ID，Schema 枚举当前合法身份，Runtime 检查每项恰好一次，并从实际输入恢复 criterion 正文。模型无需重抄正文证明身份。绑定失败保留明确的输出契约错误，不归为用户提供的非法参数；语义拒绝保持修订反馈。

下一准入使用两份原始输出的确定性反事实，覆盖漏项、重复、未知身份和有效不满足意见，随后验证同入口真实模型的完整用户结果。该设计尚未实现；本轮没有新增模型样本或改变最终核验契约。准入由[Future 队列](../future/design-optimization-backlog.md)拥有。

## 2026-10-02 正式轨迹重复转录失败

同一自然任务的第 19 版八条 claim 来源通过，进入最终汇总后，五份正常 stop 报告均未形成合法回执。前四份各返回十二项 satisfied，但都漏掉忠实性验收项末尾的中文句号；第五份仍漏句号，还将“解释工具由谁选择和调用”改为“解释工具由谁选择和由谁调用”。Runtime 按完整字符串集合匹配，五次都返回 `semantic verifier must return exactly one result for every criterion`，最终达到 32 回合返回 limitation。原始报告的 satisfied 不等于有效核验通过。第五份原始报告还有一项 insufficient_evidence，只作为该无效报告的诊断，不用前四份覆盖它。

十二项原始输入、逐次缺失/新增文本及原始响应由[实发输入审计](../../.tmp/mimo-provider-diagnostics-20261002/input-audit.json)拥有；完整用户结果由[本轮评测](../evals/02-current-case-inventory.md#2026-10-02-mimo-诊断补齐后的正式验证)拥有。本轮只补 Provider 诊断，最终契约保持；上述 criterion ID 设计继续待实施，下一准入保留本次五份失败报告。
