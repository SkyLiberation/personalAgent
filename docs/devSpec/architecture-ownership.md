# 架构边界与事实归属细则（ARC）

> 本细则在任务涉及架构分层、业务事实、状态、Schema、Model、Repository、Port、Adapter、Application Capability、Runtime Mechanism、Product Aggregate 或生产可达性时生效。

## 1. 单一事实与单一写入口

每个业务事实必须只有一个权威 owner、一个 canonical model、一个合法写入口，以及一套生命周期、版本和失效规则。无法说明字段的 owner、来源、写入者、失效条件和重建方式时，禁止编码。

禁止：

- 新旧字段双写或 singular/plural 双轨状态；
- 多个 Model 镜像同一业务事实；
- 用 validator、listener 或 converter 同步副本；
- 为读取方便新增可写镜像字段；
- 持久化可由 canonical facts 确定性重建的派生值。

## 2. 决策所有权

- **模型或外部权威**：负责开放世界语义判断；
- **确定性代码**：负责权限、唯一推导、状态迁移和不变量；
- **执行系统**：产生执行事实；
- **Verifier**：判断 Goal 是否语义满足；
- **Completion Gate**：判断 required result contract 的证据是否齐全。

新增分支必须归属于 Semantic Decision、Deterministic Derivation、Policy Decision、Environment Fact、Execution Fact、Semantic Verification 或 Completion Decision 之一。

## 3. 强制术语与能力分层

系统目标是高内聚、低耦合、可替换、可验证、可恢复、可审计和可演进；这些目标不构成创建空壳层或提前抽象的理由。禁止把框架协议、运行机制、业务能力和产品生命周期并列称为“能力”或“运行形态”。

| 层次 | 定义与 owner | 典型内容 |
| --- | --- | --- |
| **Framework Protocol** | 跨业务成立的交互与权力不变量；不拥有业务事实 | Proposal/DecisionFeedback/Observation 契约，Execution/Verification/Completion 分离 |
| **Runtime Mechanism** | 实现 Port 并拥有必要技术执行事实；不决定业务目标或生命周期 | Model/Tool/Agent Adapter、Gateway、Queue/Lease、checkpoint/journal substrate、ArtifactRef、Trace |
| **Application Capability** | 用户可理解、可验收的业务动作；由唯一 Application Use Case 拥有语义、入口和结果契约 | grounded answer、删除知识、创建订阅、启动调查 |
| **Product Aggregate** | 拥有需要独立一致性和持久生命周期的 canonical business facts | Knowledge Item、ResearchSubscription、InvestigationProject |
| **Interface / Projection** | 转换协议或展示 canonical facts；禁止成为第二写入口 | API/CLI/消息 DTO、进度 View、Capability projection |

架构文档中未加限定的 `Capability` 一律指 **Application Capability**。Tool、MCP endpoint、Agent profile、Provider、Workflow 和 Project 都不得与其并列为同类能力：前四者是执行资源或机制，Workflow 是能力内部的固定编排，Project 是业务 Aggregate。`EffectiveCapabilities`、inventory 或模型可见 schema 只是按 identity、scope 和 policy 生成的只读投影，不拥有 capability definition、可用性或业务事实。

用户或顶层语义路由选择“完成什么”，而不是选择 Tool、Workflow 或 Project。Application Capability owner 根据已证明的契约调用 Service、Tool 或 Agent，执行具体 Workflow，或通过另一明确 Use Case 创建 durable Aggregate。直接 API 与 Agent 入口必须复用同一 Application 写入口。进入已准入 capability 后，模型可以按其公开 contract 提出 ToolCall 或 AgentDelegation 作为执行步骤，但不能借此改变 Goal、事实 owner 或用户产品路径。

## 4. Framework Capability 准入与边界

框架能力是 Framework Protocol 与 Runtime Mechanism 的组合。新增或抽取框架能力除满足变更证据与复杂度准入外，还必须同时证明：

1. 机制语义与具体业务无关，且被至少两个独立生产消费者需要；仅有一个消费者时，除非外部协议或安全边界强制标准化，否则保留在该 Application 内；
2. 有稳定 typed contract、owner、失败语义、版本或兼容边界及 Contract/Runtime Conformance Test；
3. 不拥有 intent、业务 payload、业务 pending 状态、领域合法迁移、语义完成标准或 canonical business facts；
4. 抽取后由 Application 通过 Port 使用，且删除的重复复杂度大于新增抽象、Registry 和适配成本；
5. 产品 E2E 仍从用户目标验证结果，不能以框架对象存在或 conformance test 代替。

框架可以统一 identity/scope 传播、Proposal/Feedback/Observation envelope、Policy/Admission/Gateway 协议、digest/幂等/审计原语、Queue/Lease、资源引用、Trace 以及 Verification/Completion 的阶段协议。具体 Application 或 Aggregate 必须继续拥有 Command payload、等待原因、审批后的合法迁移、补偿、Receipt 业务含义和 required result contract。

审批是边界范例：框架可规定认证、授权决策、确认绑定、digest 校验、审计和 typed outcome；Delete Workflow 或 InvestigationProject 分别拥有待确认 Command、confirm/reject 后迁移和恢复行为。禁止创建通用 Approval、Task 或 Workflow 表成为第二事实 owner，也禁止要求所有业务机械实现 pause、resume 和 cancel 全套控制。

同一名称或结构若同时出现在 framework 与 domain，必须证明语义完全相同并由 framework contract 单一拥有；否则使用领域限定名称并保持独立。禁止用 converter 同步两个 `Decision`、`State`、`Receipt` 或 `Evidence` 模型。

## 5. 依赖方向与模块职责

稳定依赖方向为：`Interface -> Application Capability -> Domain/Product Aggregate`。Application 只依赖 Port；Runtime、Governance 和 Provider Adapter 从外层实现 Port，并统一在 Composition Root 装配。

- **Domain / Product Aggregate**：拥有 canonical facts、核心不变量、Command 适用性和确定性迁移；禁止依赖 LangGraph、ORM、模型或 MCP SDK、网络、UI 或 Prompt。
- **Application Capability**：接收 Use Case，协调 Domain、语义决策 Port、Governance Port 和 Runtime Port，并管理事务和阶段；不得猜测 payload、复制领域规则或把执行失败伪装成成功。
- **Semantic Decision implementation**：模型可提出 Goal、Intent、动态 Plan、下一步和语义验证；必须返回 typed Proposal，不能产生权限、执行事实或业务写入。
- **Governance / Runtime**：执行通用机械协议并返回 decision 或 result；不得创造 intent、target、payload、业务计划、业务 pending 状态或完成结论。
- **Interface / Adapter**：只做协议转换、身份解析、输入校验和 Port 适配；不得补全业务语义、选择业务流程或隐式创建 Aggregate。
- **Observability / Evaluation**：记录和评估事实，不改变生产业务行为。

框架对象不得跨模块成为业务契约。Repository 只保存 Domain 或 Application 认可的事实；依赖装配集中在 Composition Root；禁止循环依赖和跨层反向调用。分层用于约束职责，不要求每项功能机械创建全部目录、Interface 或 Adapter。

## 6. Canonical Model 与状态

禁止在同一 Model 混装：

- Definition：不可变定义；
- Proposal/Command：建议或请求发生什么；
- Event/Receipt：已经发生什么；
- Runtime Projection：当前执行视图；
- View/DTO：展示结构。

只有恢复、审计、重放、授权或审批边界、长生命周期一致性，或无法确定性重建时，才允许持久化派生信息。“以后可能有用”不是理由。

Event 只记录已发生事实。只有具有恢复、审计、重放或长生命周期消费者的核心 Aggregate 才使用完整 Event 与 Projection；固定小状态机不得默认事件化。

Identity 和 scope 禁止使用空字符串、裸字符串或 raw dict。Identity、reference 或 status 跨 Proposal、Admission、Execution 等阶段沿用时，不得因值相同而隐式继承权威；必须明确各阶段的 owner、权威生效与失效条件、合法消费者和边界断言。语义与权威边界可机械证明不变时允许沿用同一值，禁止为形式分层复制 ID。读取、检索、工具、Artifact 和 Memory 必须携带并校验适用的 tenant、user、thread 和 task scope。

## 7. 生产可达性

能力只有形成 `正式入口 -> Application Capability -> Domain/canonical state -> 真实 Runtime/Provider/Persistence -> Verification/Completion -> 用户结果` 的最小纵向切片才算落地。

每个新增生产结构必须能指出正式入口可达链、生产构造点、调用者或消费者，以及删除后会失败的测试。持久化事实或投影还必须有真实写入者与读取者；注入式协作者必须在 Composition Root 装配。缺一项即删除，不得以阶段名称或未来接入保留。

不可控第三方可以使用生产 Port 的 Fake，但必须有 contract test，并在宣称真实交付或上线前通过真实环境 smoke 或 E2E。多个独立用例不能拼成组合能力证据。
