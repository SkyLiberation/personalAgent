# 高频追问：一句结论，一个边界

> **先回答判断，再按追问跳转到唯一机制文档。** 本篇不复制第二套架构说明，也不为真实缺口增加防御性话术。

## 1. 定位与总体架构

### 这是 RAG 还是 Agent？

**产品边界是 Agent，RAG 只是证据子系统。** 模型还会决定下一步 action、Tool/MCP 或 Agent delegation；Runtime 治理权限、执行、恢复和完成。见[项目故事](01-project-story.md)。

### Conversation、Workflow、Project 是三种产品模式吗？

**不是同一维度。** Conversation 是交互 owner，Workflow 是 Capability 内固定编排，Project 是动态长任务 Aggregate；Conversation 可以调用或创建后两者。见[请求路径](02-request-walkthroughs.md)。

### 为什么不用通用 DurableTask？

**交互、删除、投递和调查没有共同的业务事实、状态机和完成契约。** 共享 journal/queue/gateway 等 runtime mechanism，领域状态仍归各自 owner。

### 当前工程有没有 Plan？

**有，但不强制每个 Conversation 产生持久化 Plan。** Conversation 逐轮基于 Observation 决策；InvestigationProject 的 ready set、steering、恢复和 Completion 真正消费 accepted Plan，因此才持久化。`PLAN-001` 证明同 Conversation 可恢复并调整同一 Project。

### LangGraph 是领域核心吗？

**不是。** 它可承载编排/checkpoint，Claim、Command、Plan 和 Completion 的语义仍由 Domain/Application contract 拥有。

## 2. Capability、Tool 与决策

### Application Capability 为什么不是 Workflow 别名？

**Capability 是用户可验收动作和业务 owner；Workflow 是该动作内部的固定步骤。** “删除知识”是 Capability，prepare/confirm/execute/receipt 是 Workflow。见[能力设计 §3](03-capability-axes.md#3-application-capability-与执行资源按-owner-分开)。

### Application action 为什么不全做成普通 Tool？

**模型侧可以共享 callable schema，执行侧不能丢掉领域 owner。** ToolGateway 不拥有 Claim 生命周期、订阅迁移或 Project plan version。

### Effective projection 有什么价值？

**它只把当前 identity/scope/policy 下可见的 action schema 临时交给模型。** 它不是 capability definition 或 availability 的第二事实源；零消费者 revision/digest 应删除。

### Tool 很多时一定做两阶段 discovery 吗？

**不一定。** 只有全量 schema 已由真实 baseline 证明损害选择质量、token 或延迟，才准入候选发现与按需加载。

### Tool schema 为什么不是授权？

**可见、获准、健康是三个事实。** MCP discovery 声明 schema，Policy 决定调用许可，Gateway 才产生 Provider 执行事实。

### 为什么不用关键词 Router？

**词面不能证明开放语义。** “不要保存”“如何删除”“删除它”共享关键词但目标不同；模型提出 typed Proposal，确定性代码只做可证明的准入。

### Admission 能补 `note_id` 或换 Tool 吗？

**不能。** 这会把语义选择藏进 Validator；Admission 只能接受或返回 typed repair feedback。

## 3. Command、协作与恢复

### Proposal、Command、Event、Receipt 有什么区别？

**Proposal 是建议，Command 是冻结待执行动作，Event 是已发生事实，Receipt 是执行关联/幂等依据。** 按真实消费者选用，不机械成套创建。

### 为什么读取不建 Command，删除要建？

**安全可重试读取直接执行；删除跨确认、恢复和不可重复副作用边界。** 给读取套 Command/Receipt 只会增加状态。

### CommandDigest 是否过度设计？

**当确认必须绑定同一冻结 payload 时，一个 digest 有价值；没有该边界就不创建。** 它不替代身份、授权或 Receipt，也不在授权/执行相同时拆双 digest。

### 子 Agent completed 为什么不等于完成？

**它只产生 child execution fact/Artifact。** 父 Runtime 仍要综合、验证并完成父 Goal。

### 崩溃后怎样避免重复执行？

**恢复 committed inputs、immutable Command、Receipt 和 stable submission key，不重新让模型生成动作。** 外部结果不确定时 reconcile；checkpoint 本身不保证 exactly-once。

## 4. Context、Knowledge 与 Memory

### Context 很大怎么办？

**先过滤 visibility，再召回选择；大结果保存真源并提交 ResourceRef，模型按需有界重读。** `CTX-001` 证明对应 workload 的增长受控。见[能力设计 §2](03-capability-axes.md#2-context-只注入当前允许且需要的信息)。

### 模型何时停止重读？

**按目标证据充分性与终止事实停止，不只看 EOF。** 证据齐全、资源耗尽、预算不足、能力失败或需要用户输入都可结束。

### Grounded Ask 和通用多源 RAG 为什么不再分两条答案链？

**最终答案只有 Conversation 一个 owner。** Personal Knowledge 和 Web/MCP 是同一 answer contract 的不同 evidence/Observation 来源；`ASK-001A`、`ASK-001B` 分别验证 personal-only 与 personal + official web。

### 为什么向量库和 Graph 不是事实源？

**它们是可重建检索投影。** Artifact、Evidence、Claim 才拥有 provenance、状态和纠错语义。见[领域设计](04-knowledge-and-domain-workflows.md)。

### 如何防止记忆污染？

**Ask 默认只读，Save 要明确意图和 exact source；纠错新增 Claim 并 supersede 旧 Claim。** 当前不自动保存 assistant candidate。

### 当前有 Workspace/RBAC Aggregate 吗？

**没有已证明的该产品能力。** 当前证据只支持 principal ownership，不把跨 principal 隔离外推成 membership/role。

## 5. 完成、预算与诊断

### Tool success 为什么不等于完成？

**Tool success 只证明动作执行。** Verifier 判断 Goal 语义，Completion Gate 检查 required evidence；Project created、Delivery sent 和 child completed 同理。

### Verifier 能推翻真实副作用吗？

**不能。** 它可拒绝“目标已满足”，不能声称已经发生的删除或发送没有发生。

### 预算参数会不会过多？

**只保留约束不同资源和失败语义的参数，并集中成 interaction policy。** batch 前原子预留；无独立消费者的旋钮合并或删除。

### 可观测性记录什么？

**记录 Proposal、Admission、Execution、Verification、Completion 的 typed stage fact 和关联引用。** Trace 用于定位，不是授权或业务状态写入口。

### 一个失败如何定位？

**找最后一个已提交权威事实，再检查下一阶段缺失或拒绝原因。** 例如删除依次检查 Proposal、Command、Confirmation、Event、Receipt 和 replay。

## 6. 证据与外部框架

### 怎样证明设计有效？

**产品变更用同入口同输入的失败 baseline 与 target E2E；纯重构用失败工程约束基线和行为保持 E2E。** 对象存在、Unit 或竞品实现不能替代。见[证据与发布](05-evidence-and-release.md)。

### 当前有哪些框架级指标？

**EVAL-001 已能从同 profile checksum archive 统计完成率、token、调用、延迟和恢复，但没有第二个可比 runtime。** 因此能测当前基线，不能宣称相对外部框架更优。

### 为什么不能说当前可发布？

**当前工作树没有 clean matching revision 的完整 eligible matrix。** 定向 E2E 只证明自己的 archive，release gate 还检查 catalog、checksum、commit 和 clean tree。

### 与优秀 Agent 框架的关系是什么？

**本地 baseline 决定要不要做，A 级源码/规范帮助选择怎么做。** 参考 OpenAI Agents SDK 的 loop/session/tool、LangGraph checkpoint 和 Hermes context 机制，但不复制对象数量或强制 Planner。

### 当前最大缺口是什么？

**证据层缺口是建立目标 revision 的完整 clean release matrix；产品层没有预设“下一个最大功能”。** 新能力必须由真实用户扩展或失败 baseline 准入。

## 7. 收尾口径

> 这个项目的核心不是抽象多，而是每个判断和事实有明确 owner：模型负责开放语义提议，确定性系统负责治理，Application/Domain 负责业务事实，Verifier 与 Completion Gate 负责完成证据。成立到什么范围由正式入口 E2E 和反事实决定；证据不足就明确说不足。
