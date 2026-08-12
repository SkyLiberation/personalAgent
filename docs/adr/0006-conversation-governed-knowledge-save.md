# ADR 0006: Conversation 内受治理的知识保存

- 状态：Accepted for experimental implementation；not merge-ready
- 日期：2026-07-28
- baseline 证据：`data/e2e_traces/20260728T083321.588087Z-48120-2ce6f484`
- semantic baseline 证据：`data/e2e_traces/20260729T031804.415533Z-15972-214cb81c`
- 当前 target 证据：`data/e2e_traces/20260729T033339.065714Z-22692-16415241`
- 临时例外到期/实现移除日期：2026-08-28

## Goal / Current Incorrect Behavior / Expected User-visible Result

用户从 Conversation 自然表达“保存这条结论，保存前让我确认”时，Agent 应返回可恢复的
待确认操作；确认后保存并返回 Receipt，拒绝、越权和 replay 不产生额外知识。

当前 Conversation 虽能用文本要求用户确认，却没有 typed pending state、确认入口、恢复、
执行或 Receipt。用户回复确认后，系统没有冻结内容可继续执行。

## Business Expansion or Proven Constraint / Out of Scope

这是已有 Conversation 与已有知识固化能力之间缺失的产品闭环，不是为对齐外部框架增加
通用 Workflow。范围仅覆盖用户明确要求保存的既有 user message。

Out of Scope：保存 assistant 推断、任意知识草稿改写、关键词识别确认、通用 Procedure
执行器、双 digest、跨 Provider 授权编译，以及把 `capture_text` 暴露给 Conversation。

## Simplest Baseline E2E / Executed Result / Root Cause

执行：

```powershell
$env:PERSONAL_AGENT_REQUIRE_LIVE_E2E='true'
uv run pytest -q evals/e2e_quality/test_product_capability_outcomes.py::test_baseline_b01_conversation_cannot_govern_explicit_save --e2e-scope=diagnostic -s
```

结果：`1 passed in 120.78s`。Conversation 返回 `clarification_required`，模型明确要求确认，
但 Claim 零增长、`tool_calls=0`，响应和 trace 均没有 pending confirmation；同一输入调用
`KnowledgeService.solidify_conversation` 后新增 2 个 Claim。根因是 Conversation 缺少确认后
继续执行的确定性产品协议，不是模型理解失败或知识写能力缺失。

## Target E2E and Counterfactuals

E14 从 `/api/conversation/turn` 输入用户自然表达，自动断言：

- prepare 返回 `confirmation_required` 和 immutable command，确认前 Claim 零增长；
- Command 只冻结模型从 user message 中选择的精确知识 span，不包含保存或确认控制语义；
- 重启后同一 command 仍为 `awaiting_confirmation`；
- 错误 scope 零副作用；reject 零副作用由 Runtime conformance test 覆盖；
- confirm 经唯一知识固化入口写入精确结论，并返回绑定同一 digest 的 Receipt；
- 新增 Claim 不得包含“请求保存”或“保存前确认”等控制语义；
- replay 返回同一 Receipt 且不再次写入。

测试不向 Prompt 指定 Tool、Workflow、Model、内部执行顺序或保存实现。

## Decision Ownership / Fact Owner and Write Path

- 模型：判断用户是否明确请求保存，并选择既有 user message 中承载知识的精确原文 span；
- Conversation Admission：机械证明 message index 有效且 span 逐字存在于对应 user message；
- Conversation Service：冻结精确 span 与 source index，创建 Command；decision 按 run ref、principal、scope 和状态校验，服务端读取内部 digest；
- Interaction Journal：拥有 Command、确认状态和 Receipt；
- `KnowledgeService.solidify_conversation`：知识事实唯一 canonical 写入口；
- Receipt：知识写入的 execution fact；E14 还必须从公开 Claim 读取入口证明精确结论存在且控制
  语义不存在，Receipt 或记录新增不能单独完成本用例。

Proposal 携带模型从 user message 逐字复制的 `text_span`，不携带改写正文。Admission 不补
业务语义，只校验 source index、角色和逐字包含关系。使用一个 `CommandDigest` 绑定 span、
source index、command、确认、journal 与 Receipt。

## Required Production Capabilities and Missing-capability Delivery

已有：Conversation typed model decision、正式 HTTP 入口、FileInteractionJournal、身份/scope、
Personal Knowledge 固化及 Claim 持久化。

需扩展：在既有 `ToolCallProposal` 中注册粗粒度 save capability、typed exact-span selection、
immutable Command/Receipt/operation、公开 decision contract、journal 恢复与 replay。

不存在且不引入：通用 Procedure execution、第二知识写入口、事件总线、Projection、双 digest。

## Affected Modules and Dependency Direction

- `application/conversation`：proposal、command、receipt、状态迁移和用例；
- `orchestration/runtime`：注入现有 Personal Knowledge canonical writer；
- `adapters/web/routes/conversation`：协议转换、身份解析和错误映射；
- `application/knowledge`：保持现有 owner，不接收模型生成的替代正文；
- E14：正式 HTTP 生产路径与 trace/report 证据。

依赖仍为 Web Adapter -> AgentService/Conversation -> Personal Knowledge Application；Domain 和 Personal Knowledge
事实模型不依赖 Conversation 或 Web。

## Complexity Added, Removed and Rejected Alternatives

新增一个业务特定 capability/arguments、一个 immutable Command、一个 Receipt、一个三态
operation 和一个 decision endpoint。语义选择复用既有 `ToolCallProposal`，其余对象分别承担
跨请求冻结、执行事实和公开确认契约，均有 E14 生产消费者。

同步删除未接入生产执行却声称覆盖该能力的 `conversation_solidify` Procedure definition、
`ConversationSolidifyInput` 空壳及冲突 workflow 文档。拒绝恢复旧通用 Procedure，因为它会引入
Planner/Projection/Grant 双 digest 等未被 baseline 要求的机制；也拒绝关键词路由和开放
`capture_text`，因为二者分别篡夺模型语义决策和绕过确认。

## Removed Legacy Path / Risks

删除空转 Procedure 后，Conversation governed save 是该用户目标的唯一主链；原有显式
`/api/knowledge/solidify-conversation` 仍是已发布的 Personal Knowledge API，但与新链路复用同一个
Application 写方法，不构成第二 canonical owner。

当前 E14 覆盖精确 span、控制语义反事实、确认前重启与成功后 replay。若故障注入证明“Personal Knowledge 已提交、Journal Receipt
尚未提交”的窗口会产生重复用户结果，必须先保存该失败证据，再把幂等键下沉到 Personal Knowledge
canonical 写入口；在证据出现前不新增事务表或 outbox。

B02 在 archive `20260729T031804.415533Z-15972-214cb81c` 中从正式 HTTP 穿过 prepare、confirm
和 Personal Knowledge canonical write，自动证明精确结论缺失且控制语义 Claim 存在。修复前 E14
archive `20260729T031852.315661Z-14416-2f3c2aac` 因相同语义断言失败；最小 exact-span
selection 修复后最终 matching archive `20260729T033339.065714Z-22692-16415241` 只新增一个精确结论 Claim，
控制语义为零，原 Command 可恢复且 replay 不新增 Claim。B02 代码已在目标 E2E 通过后移除，
历史不足由 immutable archive 保存，防止默认 suite 同时要求缺陷存在和缺陷消失。

## Temporary Complexity Exception and Exit

当前生产 diff 为 `src +432/-47`，不满足 `AGENTS.md` 的默认“新增复杂度小于删除复杂度”门禁。
这是 B01 已证明的净新产品闭环，不以 LOC 冒充架构收益；本 ADR 仅允许实现留在实验工作区继续
验证，不授权合并或发布。

风险：Conversation Service 增长、Conversation journal 与其他 governed lifecycle 形成相似状态
机，以及跨 commit/Receipt 窗口未验证。当前定向验证为 Conversation 低层 17 passed 与 E14
通过；完整低层测试、Ruff、layer DAG、clean revision 和完整 release matrix 仍需重跑。

退出条件：2026-08-28 前必须以已证明的调用方删除或职责收敛使净复杂度满足门禁，并在 clean
matching revision 上重跑目标 E2E；否则删除本 ADR 对应的 Conversation capability、Command、
operation、decision endpoint 和 E14 catalog 条目，恢复到 Personal Knowledge 专用入口。禁止延期或增加
通用抽象来“摊薄”复杂度；确需改变门禁必须另建 ADR，而不能修改本例外的口径。
