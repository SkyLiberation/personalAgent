# 已完成选证用量的及时提交

`RESEARCH-SELECTION-USAGE-COMMIT-001` 是[研究未收敛问题](../claim-revision-nonconvergence.md)的计量子问题。[失败记录](../research-selection-usage-commit.md)拥有原始事实，本页拥有机制，[Future 队列](../../future/design-optimization-backlog.md)拥有准入状态。2026-10-02 按用户要求先实现，真实失败回放和 E2E 延后统一执行。

## 已证明问题与责任

正式 writer 三次 429 前，一笔成功选证的 36,782 tokens 写入内存却未提交 Journal。另一正式样本两次已完成选证响应因截断和结构失败抛错，39,395 tokens 也未提交。差额精确对应封存 Provider usage，坐标和分项等式见[失败记录](../research-selection-usage-commit.md)。

Provider 响应拥有实际完成用量，模型 Adapter 拥有有限恢复与重试响应汇总，Conversation 拥有运行累计用量，现有 Journal 拥有其持久化。修复恢复既有事实交接，不新增计量存储或派生副本。

## 解决机制与防护

1. 选证成功后，Conversation 将现有聚合响应计入累计用量并立即 `_commit`，再校验选证和调用 writer。writer 失败时 Journal 已保存完成选证的成本。
2. `_model_failure` 将模型调用或结构恢复异常中的 `StructuredModelResponse` 保留到 `ConversationUnavailable.response`。选证失败边界读取实际已完成 usage，提交同一累计用量后继续传播原异常；不合法输出不进入写作或准入。
3. 直接 writer、普通动作或 Final 调用失败时，外层边界同样提交异常携带的聚合响应。每个响应按一次成功或异常路径计入，重试分项由现有 Adapter 聚合，提交累计状态不再次相加。未返回 usage 的拒绝保持原诊断事实，不制造完成响应。
4. `response` 为内部字段。HTTP 503 继续只输出原公开错误文字，日志仅序列化现有有界诊断，响应正文不进入错误详情。Journal 使用原合法写入口；选证仍本轮消费，恢复后的新调用拥有新的实际成本。

真实路径为正式 Conversation 选证 → 原模型 Port/Adapter → 累计用量 → 同一 Journal；失败沿原应用异常回到提交边界。删除成功后的立即提交会重新暴露 writer 失败前漏计，删除异常响应交接会重新暴露结构恢复漏计。

## 验证与退出

改动前身份及归档见[本轮预声明](../../../.tmp/final-revision-comparison-usage-20261002/plan.json)。按用户要求本轮模型调用、Offline Eval 和 E2E 均为 0，只执行静态检查。

本轮 Ruff、compileall、依赖 DAG 和差异格式检查通过，关联文档链接检查无错误，结果见[静态归档](../../../.tmp/final-revision-comparison-usage-20261002/static-checks.json)。实际用量提交和恢复去重待下述回放验收。

统一验证消费真实选证、两次截断和后置 429 轨迹，核对全部完成响应与 Journal 分项等式，检查错误保持、失败输出未准入及恢复后不重复计入。新正式 target 使用原中文入口和真实模型，用户结果与计量边界分开报告；工具内部用量按其[独立问题](../tool-model-usage-handoff.md)验证。

重复计入、完成 usage 丢失、异常响应暴露或失败输出进入准入均直接否定修复；封存结果并回到首次责任边界处理。用户结果按实际阶段归因，计量结论按真实响应与持久化等式验收。
