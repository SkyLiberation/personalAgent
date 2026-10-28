# 工具内部模型用量未进入 Conversation 总账

`TOOL-MODEL-USAGE-HANDOFF-001` 拥有工具内模型调用进入 Conversation 总账的边界。2026-10-23 普通 Verifier 已按下述逐调用方式接入；真实语义拒绝、未知停止及整条已知用量等式成立，历史合法接受及契约失败的当前版本回放尚未执行。原历史轨迹保持，不把当前结果外推到其他工具或 Agent。准入状态见[Future 队列](../future/design-optimization-backlog.md)。

## 当前普通核验的机制与范围

仅在整个 workflow 返回后交回合计，无法在分段核验之间及时判断额度或未知消费。因此采用当前 Application owner 的显式调用绑定：Runtime 构造 Conversation 后，把其按受信 `ExecutionScope` 绑定的模型调用方法注入原核验工具。工具从既有网关配置取得 scope，模型可见参数不增加字段。各次核验调用原 typed 模型 Port，立即提交成功响应或失败前已完成响应；未知保持未知。独立分析许可下，每次请求同时检查 Journal 聚合额度、截止及未知消费。工具返回后，Conversation 从 Journal 取得最新 usage，避免旧局部变量覆盖；本轮不向未绑定该许可的普通对话外推相同的任务总额停止保证。

原网关 480 秒外层线程超时会使工作线程无法持有当前 run 的重入锁，且超时后可能继续付费；该工具改为同步调用，由原模型单请求超时与运行截止负责停止。原分段支持核验、整体核验、稿件／回执绑定均保持。该装配只修正普通核验入口，不增加通用 Hook、第二账本、工具用量字典或一套费用 Schema；当前模型响应已是 typed 用量事实，不再保留原“先新增工具合计回传契约”的候选。

依据是下列历史差额、LongDS 首轮真实用例及本轮集成审查。新 target 的 80 次物理请求（76 次逻辑调用）共 4,879,140 tokens，与 Journal 完全相等；10 次核验 workflow 的语义拒绝消费均已纳入。真实 `final-25`／原 criteria／完整引用的独立 Offline 分支在第一次真实核验响应交付后丢失，生产保留未知，第二次核验在模型 Port 前拒绝；该分支 1 次物理请求、旁路 12,014 tokens，未把旁路值回填生产。结果及源身份见[LongDS 结果](to_verify/verify_results/longds-analysis.md#12-独立能力-target-的结果与剩余边界)。这不是完整用户结果通过，原合法接受与契约失败的历史身份也未被重标。

## 历史失败依据与原边界

2026-10-01 完整终态中，Provider 已完成 66 次生产响应，共 1,194,979 tokens；Conversation 记录 62 次 typed 操作和 1,143,604 tokens。分项差额 51,375 tokens 精确等于三次最终核验工具的内部模型响应。直接模型调用的 63 份物理响应与 Journal 三项用量精确相等，内部恢复聚合为 62 次 typed 操作；本问题与[失败重试计量固化记录](completed/model-retry-usage.md)的分支不同。

[实际成本审计](../../.tmp/research-source-reuse-repair-20261001/cost-audit.json)保存完整请求、响应和逐分项等式。`application/conversation/service.py` 消费 `_verify_final` 的工具结果时只增加 `tool_calls`；`tools/interaction_verifier.py` 已取得结构化响应，却没有把模型用量交回总账。因此终态 `provider_usage_complete=true` 不代表全部生产模型成本完整。该路径在本轮未修改。

### 当时的责任与下一边界

当时定位为 Provider 拥有实际用量、Conversation 聚合执行事实一次，成功、语义拒绝和契约失败前的完成响应都须交接，未知不能补零；尚未实施。当前普通 Verifier 改用上节的逐调用绑定；其他消费者按其真实入口及证据另审，不从这份历史归因自动取得生产准入。

## 2026-10-11 新正式轨迹的两次最终核验

新run `irun_136c545f011740b3` 的生产原始已知用量1,508,643，Runtime记录1,445,777；差额 **62,866** 精确等于两次Final v6实际响应0086的30,650及0091的32,216。独立评分61,706另计，两次Source超时保持未知，不能补零。两次Final均为合法接受，最终答案已交付；该缺口不是服务在途或研究修订漏交，仍属既存工具内部用量交接。原始等式见[调用审计](../../.tmp/source-production-target-20261011/model-call-audit.json)及[终态用量](../../.tmp/source-production-target-20261011/formal-result-audit.json)。本次仅补充真实边界证据，未修改生产计量；已知生产总量仍低于原2,000,000上限，不以此扩张当前来源优化。

## 2026-10-02 最终契约失败调用仍有漏计

诊断补齐后的正式终态共完成 93 个生产响应，2,013,022 tokens；Journal 为 1,945,314。差额输入 57,431、输出 10,277、合计 67,708，精确等于五次最终核验工具的已完成模型响应；五次都因验收项转录失败，仍产生服务方用量。扣除这五次后，直接模型的输入、输出、total 与 Journal 逐项相等，全部请求已经完成，不归为在途调用或本轮选证未提交。证据见[分项等式](../../.tmp/mimo-provider-diagnostics-20261002/recovery-boundary-audit.json)及[完整结果](../../.tmp/mimo-provider-diagnostics-20261002/result.json)。本轮该交接路径未修改，已完成但契约失败的模型响应须纳入后续恢复及预算验证。

## 2026-10-02 引用身份修复后的合法回执用量

最终 ID 报告形成有效 passed 回执后，生产 Provider 合计 1,659,663 tokens，Journal 1,647,159；差额输入 10,138、输出 2,366、total 12,504 精确等于该一次工具模型响应。全部请求已完成，原用户评分的 9,413 tokens 独立计量。扣除工具响应后，直接模型与 Journal 三项相等，见[最终成本审计](../../.tmp/final-criterion-reference-20261002/target-audit.json)。身份绑定修复没有修改这条既存交接；合法和契约失败的工具响应均继续作为本问题的必要反事实。

## 2026-10-08 最终当前稿核验响应仍未交接

新正式轨迹完成 47 份生产响应，1,126,488 tokens；Journal 为 1,091,580。差额输入 32,856、输出 2,052、合计 **34,908**，精确等于一次最终 v6 工具模型响应。独立 grader 的 63,695 tokens 另计，全部 48 份响应完成，无未知服务用量。该问题未修复，不据终态完整标志宣称总账闭合，见[分项审计](../../.tmp/claim-atomic-reference-repair-20261008/product-audit.json)。

初始选证状态修复后的正式轨迹中，生产完成46份SDK响应，722,048 tokens；Journal为666,454。差额 **55,594** 精确等于两次最终核验工具的27,617与27,977；独立评分64,760另计，全部47份响应完成。两次合法报告分别拒绝和接受当前稿，均仍漏交工具内部用量，见[本次分项审计](../../.tmp/research-selection-state-target-20261008/product-audit.json)。实际恢复与当前稿核验成立，不改变本问题的归属和未修复状态。
