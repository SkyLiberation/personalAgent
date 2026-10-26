# ADR 0041：回答结果模块替换与独立核验装配

状态：接受，已实现；实际阶段、两轮流程与两轮独立评分通过。日期：2026-10-23。

## 问题与决定

LongDS 首轮已经完成 7 次 Python，但普通核验 10 次拒绝，最终触及主决策上限。该例未进入 claim 写作。用户明确要求先不接入核验和 claim，确保分析流程运行，并要求后续能够消融 claim。

按[研究 Spec §9.9](../optimization/to_verify/knowledge-decision-delivery.md#99-可替换回答模块与无核验流程验证)，将直接回答与 claim 回答实现为同一 Application 提交契约的两种模块，核验由独立配置装配。默认保留当前 `claims + required`；本次独立 LongDS 流程采用 `direct + none`。配置在 Runtime 装配，在 Journal 的 run 及对话边界绑定；模型不选择装配，恢复不能换配置。

## 责任、复杂度与替代方案

模块拥有写作协议和提交接纳；Conversation 继续拥有唯一模型循环、调用预算、执行及 Final 提交。claim 实现复用当前 typed 引用、版本、选证和核验，无核验模块不伪造通过事实。Artifact 和 Journal 没有第二写入口。

不采用临时 monkey patch、生产 `skip_claim/skip_verifier` 条件散布或复制一套 Agent。局部模块接口隔离用户已明确提出的变化；从 service 移走 claim 提交／接纳，增加一个配置契约和一个模块文件，不引入通用插件容器。

## 例外、防护与退出

根规范要求 Product E2E 经过适用 Verification/Completion，且候选不得作为生产开关。本次用户指令授权可替换模块及临时无语义核验装配；只将其作为明确的诊断部署，记录 `unverified_flow_capture` 与 `release_eligible=false`。身份、权限、引用、执行事实及成本门禁继续生效，原完整 target 不改成绩；未核验结果不得产生通过回执。

临时 `none` 配置的诊断例外至 **2026-11-06** 复审／移除。诊断结束或修复核验并恢复完整 target 后，停止无核验采集；可替换 writer 是持续架构决定，后续 claim 消融须固定同一 verifier 条件，不以本轮双变量变化归因。

## 验证

固定实际阶段回放和一次正式入口两轮流程，预算、停止线与断言由原 Spec 拥有。实际阶段的正文、引用拒绝与修复输入、绑定拒绝及 claim 模块调用保持已核对，新增模型／执行为 0；两轮流程与两轮独立官方评分均通过。实际完成记录恢复同一正文，改变 writer 或核验配置的原 run 恢复及同对话新 run 均拒绝，新增模型／执行为 0。完整 36 轮、L3、自然 Context 压力及 claim 独立收益不在本次通过声明内。
