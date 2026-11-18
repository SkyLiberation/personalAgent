# ADR 0046：用封存证据恢复单次未派发作业

历史单次运维例外，于 2026-10-27 到期。原恢复检查已通过，后续正式运行结果由[评测盘点](../evals/02-current-case-inventory.md)维护。

## 事故与决定

LongDS Netflix Task 2 第 21 轮 Command `44f0494d6141d9b65848f4eaca8b77e7483bf18625c2225f9f46866463383ceb` 在落盘 `job.json` 时发生 WinError 5；同名 Docker 容器查询返回 404，原回执为 `unknown/backend_unknown`。同版本代码证明落盘先于 Docker 调用，结合空容器 ID 与原错误，可确认这笔作业未派发。原 run 在未决门禁处停止，准备请求没有发送，模型未获得基于该错误修复的机会。

在副本 `.tmp/lr2/` 内使用仅匹配本次 Command、scope、digest、许可和原证据的一次性适配器。它只执行对账，经原服务与 Journal 追加未派发的 typed 失败，零 `execute`，保留原 unknown 回执。后续使用新 run 接续原用户请求，先前费用和执行事实保持原身份。[事故归档与恢复规格](../optimization/to_verify/python-data-analysis-tool.md#41-容器创建意图写入失败的分类与恢复)

## 验证与退出

单次恢复核对原封存、绑定、未决集合、重复请求的相同失败回执和跨主体拒绝。事故脚本只保留作证据。改写原 JSON、批量视 unknown 为失败或重跑整个任务都会丢失事实或扩大副作用，故采用原写入口的一次性适配。通用恢复和 Windows 落盘仍按各自证据验证。
