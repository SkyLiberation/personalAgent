# Knowledge Agent 工程开发规范

> 本文档是知识 Agent 项目的唯一强制工程规范，适用于业务与架构设计、文档规划、开发、重构、缺陷修复、测试、评审和上线验收。
> “必须/禁止”属于合并门禁；确需例外时，必须通过 ADR 记录原因、风险、验证、退出条件和移除日期。

---

## 1. 最高铁律

### 1.1 E2E 可执行验证

**任何优化必须先由当前最简单生产路径的 baseline E2E 证明当前 Agent 无法满足同一用户目标；没有配套可执行、可重复、可自动断言用户结果的 E2E，任何落地设计都视为未经验证。**

- 优化设计前必须从正式入口以用户自然表达实际执行 baseline，自动断言缺失的用户结果或发生的关键错误结果，并保存 trace、event、receipt 或 report 证据。
- baseline 未失败、失败源于测试/环境缺陷、或现有路径已满足目标时，必须停止优化；代码不可达、架构推断、竞品对比、文档或低层测试不能替代该证据。
- 只有 baseline 证明不足后才能定义目标 E2E 和最小改动；目标 E2E 可以先失败，但编码前不得缺失。
- 未实际执行测试时，禁止声称“已验证”“已修复”或“可上线”。
- Unit 通过、对象存在、状态为 success、数据库新增记录都不能替代 E2E。
- E2E 必须由目标用户的真实目标和自然表达驱动，同时断言正确结果发生，以及关键错误结果没有发生。

合格 E2E 必须：

1. 从正式 API、CLI、消息入口或 Application Use Case 进入；
2. 经过生产主路径，而非测试专用旁路；
3. 使用真实领域模型、状态迁移、编排和持久化协议；
4. 自动断言用户可观察结果和关键反事实；
5. 能以明确命令在本地或 CI 重复执行；
6. 失败时能由 trace、event、receipt 或 report 定位阶段。

E2E 的输入必须符合目标用户实际掌握的信息。除非 Tool、Agent、Workflow、Model、内部 ID
或执行顺序本身就是该用户可见的产品契约，禁止在 Given/When、Prompt 或测试指令中指定它们，
替 Agent 完成能力选择、规划或结束判断。生产路径可以在执行后通过 Trace/Receipt 断言，不能
通过向用户输入泄漏预期实现来制造通过。需要精确指定 Tool、步骤、并发、Checkpoint 或内部
协议的场景属于 Integration/Runtime Conformance Test，不能单独作为用户 E2E 或产品能力证据。

Fake/Stub 仅允许替代不可控第三方、付费模型、危险副作用和故障注入。Fake 必须实现生产 Port 并有 contract test；不得创造生产中不存在的能力，也不得替模型、Policy、Admission 或 Verifier 作决定。

### 1.2 单一事实与单一写入口

每个业务事实必须只有一个权威 owner、一个 canonical model、一个合法写入口，以及一套生命周期、版本和失效规则。无法说明字段的 owner、来源、写入者、失效条件和重建方式时，禁止编码。

禁止：

- 新旧字段双写或 singular/plural 双轨状态；
- 多个 Model 镜像同一业务事实；
- 用 validator、listener 或 converter 同步副本；
- 为读取方便新增可写镜像字段；
- 持久化可由 canonical facts 确定性重建的派生值。

### 1.3 决策所有权

- **模型或外部权威**：开放世界语义判断；
- **确定性代码**：权限、唯一推导、状态迁移和不变量；
- **执行系统**：产生执行事实；
- **Verifier**：判断 Goal 是否语义满足；
- **Completion Gate**：判断 required result contract 的证据是否齐全。

新增分支必须归属于 Semantic Decision、Deterministic Derivation、Policy Decision、Environment Fact、Execution Fact、Semantic Verification 或 Completion Decision 之一。

### 1.4 删除优先与兼容边界

重构默认迁移全部调用方。能替换旧结构时，禁止新增 alias、fallback、双写、永久 deprecated 字段或无期限兼容层。

兼容仅用于真实外部契约，并必须记录适用范围、结束日期、迁移计划、观测指标和删除条件。

### 1.5 禁止无证据优化、过度设计与能力空转

**禁止为了对齐“优秀 Agent”、论文、框架范式、形式完整或未来可能性，提前增加抽象、Model、状态、digest、表、层、Planner、Workflow、Agent、缓存、持久化或治理机制。**

出现以下任一情况即视为过度设计，禁止合并：

- 没有明确业务扩展、当前用户错误或可量化工程约束；
- 不满足 1.1：没有同输入 baseline E2E 的已执行失败证据，或失败根因不是当前 Agent 的产品行为；
- 新机制只有测试、Trace、Prompt、文档或展示消费者，不改变生产行为；
- 一个职责被拆成多个 Model、digest、表或层，却没有独立 owner、信任边界、生命周期、事务边界或保留策略；
- 可确定性派生的状态被持久化，或固定流程被包装成通用 Planner/Task/Event 系统；
- 只证明对象存在、字段生成、流程 fail closed，未证明用户结果、风险、恢复、成本或延迟得到改善；
- 新增复杂度不小于被删除复杂度，或旧路径、无消费者投影和临时状态继续保留。

任何新增架构机制必须先提交一份 `Complexity Justification`，并依次证明：

1. 业务场景、目标用户结果和关键反事实；
2. 最简单生产 baseline E2E、同输入执行结果、失败根因及不足；
3. 所需生产能力盘点，以及“已有、需扩展、不存在”的代码与已执行证据；
4. 目标 E2E、生产消费者和可观测收益；
5. 为什么一个 Model/状态/digest/表/流程不够，拆分后的独立职责是什么；
6. 替代方案、复杂度预算、同步删除项和退出条件。

最小充分设计是默认选择：

- 一个事实、状态、digest、表或流程能满足当前已证明需求时，禁止拆分；
- 只有一个实现且没有外部边界、测试替换需求或近期第二变化来源时，禁止创建 Interface/Factory/Registry；
- Command、Event、Receipt、Projection、View 按各自真实职责选择，禁止为“配套完整”成套创建；
- 外部优秀 Agent 的内部结构只能作为候选方案，不能作为需求来源；
- 已存在但无法补齐上述证据的机制，必须删除、合并，或降为非权威可选投影。

设计新能力或 E2E 前，必须盘点其依赖的模型、Tool、Service、Agent、Provider、Gateway、权限、持久化、恢复和验证能力。依赖能力不存在时，必须在同一设计中定义其业务 owner、canonical contract、唯一入口、生产消费者、实现阶段、失败语义和 E2E/contract test；否则禁止进入实现。接口、DTO、配置、Fake、单项能力存在或未来阶段名称都不能证明能力已落地，多个独立用例也不能拼成组合能力证据。

---

## 2. 架构边界与事实模型

系统目标是高内聚、低耦合、可替换、可验证、可恢复、可审计和可演进；这些目标不构成创建空壳层或提前抽象的理由。

### 2.1 分层与依赖方向

分层用于约束职责和依赖，不要求每项功能机械创建全部层：

1. **Domain**：实体、值对象、领域服务、不变量和状态机；
2. **Application / Orchestration**：Use Case、Workflow 和事务边界；
3. **Semantic Decision**：Router、Planner、Replanner、模型 Verifier；
4. **Governance / Control Plane**：Policy、Admission、Gateway、Approval；
5. **Capability / Execution**：Tool、Service、MCP/A2A Adapter、Executor；
6. **Runtime / Persistence**：Checkpoint、Repository、Event/Receipt、Artifact Store；
7. **Interface**：API、CLI、消息入口和 DTO；
8. **Observability / Evaluation**：Trace、Metric、Golden Set、E2E 和 Eval。

依赖方向必须指向更稳定的内层：`Interface / Infrastructure -> Application -> Domain`。

- Domain 禁止依赖 LangGraph、ORM、模型/MCP SDK 或 Web 框架；
- Application 依赖 Port，不直接依赖具体 Adapter；
- Interface 只做协议转换、身份解析和输入校验；
- Adapter 不得补全业务语义或决定业务流程；
- 框架对象不得跨模块成为业务契约；
- 依赖装配集中在 Composition Root；
- 禁止循环依赖和跨层反向调用。

### 2.2 模块职责

- **Domain**：拥有 canonical facts、核心不变量、Command 适用性和确定性迁移；禁止调用模型、网络、数据库、UI 或 Prompt。
- **Application / Orchestration**：接收 Use Case、协调 Domain/Port/Policy、管理事务和阶段；不得猜测 payload、修复 Proposal、复制领域规则或把工具失败伪装成成功。
- **Semantic Decision**：Router 识别 Goal/Intent；Planner 仅处理无法预定义的动态依赖；Replanner 只基于新 Observation 修订未冻结计划；输出必须 typed。
- **Governance**：负责身份、scope、授权、风险、审批、Admission、幂等和预算；不得创造 intent、target、payload、计划或业务回答。
- **Capability / Execution**：Service 用于固定低风险调用，Tool 用于模型动态选择或统一治理，Adapter 转换协议，Executor 返回 typed result/receipt；Tool 不决定授权或 Goal 完成。
- **Runtime / Persistence**：负责 checkpoint、恢复、幂等、重放和生命周期；Repository 只保存 Domain/Application 认可的事实，不隐式创建业务对象。
- **Observability / Evaluation**：记录和评估事实，不改变生产业务行为。

### 2.3 Canonical Model 与状态

禁止在同一 Model 混装：

- Definition：不可变定义；
- Proposal/Command：建议或请求发生什么；
- Event/Receipt：已经发生什么；
- Runtime Projection：当前执行视图；
- View/DTO：展示结构。

只有恢复、审计、重放、授权/审批边界、长生命周期一致性，或无法确定性重建时，才允许持久化派生信息。“以后可能有用”不是理由。

Event 只记录已发生事实。只有具有恢复、审计、重放或长生命周期消费者的核心 Aggregate 才使用完整 Event + Projection；固定小状态机不得默认事件化。

Identity 和 scope 禁止使用空字符串、裸字符串或 raw dict。读取、检索、Tool、Artifact 和 Memory 必须携带并校验适用的 tenant/workspace/user/thread/task scope。

---

## 3. Agentic 决策与受治理执行

### 3.1 Proposal、Admission 与 fallback

模型可以提出 Goal、Plan、ToolCall、业务参数、恢复建议或最终回答，但 Proposal 不是权限、Command、执行事实或完成证明。直接回答不得为形式统一伪造 Task、Command、Receipt 或 CompletionReport。

Admission 只能接受或拒绝 Proposal，禁止补业务字段、拼接约束、修改 payload、替换 Goal、生成/重排 Plan 或静默降级。拒绝必须返回 typed `DecisionFeedback`，说明原因、mutable/immutable fields、required repair、revision scope 和 disposition。

模型不可用或 Proposal 连续不合法时，只允许 fail closed、暂停、请求用户/外部权威输入、请求缺失能力、等待环境变化、执行已冻结 Command，或对同一 digest 做幂等技术重试。禁止生成替代 Goal、Plan、查询、写入内容或业务回答。

Procedure 只封装 prepare、confirm、commit、receipt、compensate、reconcile 等稳定事务不变量；不得选择目标、决定 payload 或猜测失败后的替代路径。

确定性检查只能证明机械关系；禁止用模型自述、字符串包含、相似度、排名或自然语言断言冒充语义保持、授权或唯一性证明。

### 3.2 Execution、Verification 与 Completion

必须分离：

1. **Execution Fact**：Tool 或 Command 是否执行；
2. **Semantic Verification**：Goal 是否达到；
3. **Completion**：required result contract 是否全部满足。

Receipt 不能直接代表 Goal 完成；模型 Verifier 也不能推翻确定性执行事实。

### 3.3 Tool、Command、digest 与 Receipt

只读、低风险、可安全重试的 ToolCall 在 Admission 后直接执行，禁止为形式统一持久化 Command。

需要审批、具有外部副作用、不可安全重试、需要 durable execution，或跨授权/恢复边界的调用，必须形成 immutable Command。Command 只能缩权、不可覆盖；参数变化必须创建 superseding command。

digest 是冻结 canonical payload 的一致性指纹，不是身份、授权或执行证明。默认使用一个 canonical `CommandDigest` 绑定 Confirmation、Journal 和 Receipt。

只有同时满足以下条件时，才允许拆分 `AuthorizationDigest` 与 `ExecutionCommandDigest`：

- 用户授权后仍存在独立的 Command 编译、Provider binding 或 Grant 阶段；
- 两个 digest 有不同 owner、输入字段和信任边界；
- 系统可机械证明最终执行命令未超出授权；
- ADR 和 E2E 覆盖重绑定、参数变化、越权拒绝与 replay。

若授权内容与最终执行内容相同，禁止使用双 digest。客户端回传服务端生成的 digest 不能替代认证、Policy 或 Confirmation。

Command、Event、Receipt 不得机械成套创建：

- 仅当操作需跨请求、审批、重试或恢复时创建 Command；
- 仅当已发生事实有独立审计、订阅或重放消费者时创建 Event；
- 仅当需要 exactly-once 证明、外部结果关联或恢复依据时创建 Receipt；
- Projection/View 必须可从 canonical facts 重建且禁止成为第二写入口。

### 3.4 Durable Task

Durable Task 至少支持：

- 明确生命周期和合法状态迁移；
- checkpoint 与恢复；
- 相同 digest 的幂等执行；
- replay 不重新调用模型生成 Command；
- typed 失败、retry policy、补偿或 reconcile；
- required report 缺失时 fail closed。

---

## 4. Context、Memory、RAG 与 Capability

Context 必须依次经过：

1. Visibility：先按权限和 scope 过滤；
2. Requirement Retrieval：按当前需求召回；
3. Semantic Selection：模型选择语义相关内容；
4. Budget Materialization：压缩并注入 LLM Context。

禁止先召回全部内容再让 Prompt 过滤权限。

存储边界：

- Agent State：当前运行所需结构化状态；
- LLM Context：当前模型调用实际可见内容；
- Checkpoint：恢复执行所需快照；
- Artifact Store：大文本、文件和中间产物；
- Long-term Memory：跨会话可召回事实或经验；
- Retrieval Index：检索投影，不是事实权威源。

State 优先保存 ArtifactRef，不复制大型 Artifact。RAG 只负责检索和证据组织，不得成为隐藏 Router/Planner；检索策略由数据与评测驱动，禁止为单一 benchmark 硬编码，中间检索指标不能替代最终答案与证据正确性。

只有完整满足同一 `CapabilityEquivalenceClass` 的 Provider 才能确定性绑定；存在语义差异时必须由模型或外部权威选择。

---

## 5. 代码组织与模式使用

设计模式只用于隔离已经发生或由近期业务 E2E 明确要求的变化，并受 1.5 的复杂度准入约束。Ports and Adapters、State Machine、Command、Repository、Saga、Decorator、ACL、Registry 均按需使用，不是默认目录模板。

禁止：

- 为每个类创建 Interface、Factory、Manager，或用模式掩盖职责不清；
- 创建 God Service、God State、God Workflow；
- 让 Strategy/Router 承担开放语义，或让 Adapter/Converter 维护镜像事实；
- 为未来可能性创建通用 Task、Event、Workflow、Planner、Projection 或兼容层；
- 复制外部 Agent 的对象数量、层次或拓扑来证明“先进”。

### 5.1 LangGraph、Router、Planner 与 Workflow

- Graph 表达编排和迁移，不拥有领域事实；
- Node 只提取输入、调用 Use Case、写回结果，不复制业务规则；
- GraphState 仅存 typed 运行必需状态，大对象使用 ArtifactRef；
- checkpoint 恢复不得重复模型调用或副作用；
- Router 输出 Goal/Intent，不输出执行完成事实；
- 固定依赖由契约或 Workflow 定义，只有动态依赖才使用 Planner；
- Planner 不负责授权、执行或完成判定；
- Plan 只有被生产代码消费依赖、进度、预算或完成义务时才能成为强制契约；
- Workflow 内固定低风险步骤优先 Service 化，动态或受控能力 Tool 化。

### 5.2 错误、注入与命名

错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure 和 Invariant Violation。禁止捕获异常后返回空结果、默认成功或模糊 fallback。

模型、时钟、ID、Repository、Tool、Policy 和外部 Provider 必须通过 Port 注入；测试不得 monkey patch 生产规则来构造通过结果。

命名必须表达业务角色和生命周期。除非边界明确，禁止使用 `data`、`info`、`manager`、`processor`、`handler` 等泛化名称。

---

## 6. 强制开发与文档流程

任何功能、修复或重构必须按顺序执行：

1. 定义待验证的业务扩展/当前错误假设、用户结果、反事实和 Out of Scope；
2. 编写并实际执行当前最简单生产 baseline E2E，保存不足和失败根因证据；baseline 不失败则停止优化；
3. 基于已证明缺口完成 Decision/Fact Ownership Analysis 和所需能力盘点；
4. 定义目标 E2E、影响边界、复杂度预算和删除路径；
5. 实现使目标 E2E 通过的最小整体改动；
6. 补充必要的 Unit、Contract、Integration Test 和语义 Eval；
7. 删除旧字段、旧入口、旧 converter、无消费者投影和临时 fallback；
8. 执行 E2E、对照 Eval、相关低层测试及 lint/type check；
9. 记录命令、结果、净复杂度变化和剩余风险。

### 6.1 变更分析最小模板

```markdown
## Goal / Current Incorrect Behavior / Expected User-visible Result
## Business Expansion or Proven Constraint / Out of Scope
## Simplest Baseline E2E / Executed Result / Root Cause
## Target E2E and Counterfactuals
## Decision Ownership / Fact Owner and Write Path
## Required Production Capabilities and Missing-capability Delivery
## Affected Modules and Dependency Direction
## Complexity Added, Removed and Rejected Alternatives
## Removed Legacy Path / Risks
```

### 6.2 E2E 最小模板

```markdown
## E2E: <name>
Persona: <目标用户、其真实可见信息和公开产品契约>
Given: <身份、初始事实和不可由模型预知的测试数据>
When: <从正式入口以该用户的自然表达执行，不泄漏预期内部能力或步骤>
Baseline: <相同正式入口和输入下已执行的命令、结果、失败根因与不足；未执行不得进入优化>
Then: <用户可观察结果>
And not: <禁止发生的副作用或错误结果>
Path evidence: <执行后由 trace/event/receipt/report 证明的生产组件，不注入用户输入>
Required capabilities: <已有证据、需扩展项、缺失能力落地章节>
Allowed fakes: <仅外部边界>
Command: <本地或 CI 命令>
```

### 6.3 文档规范

- 变更前通读目标文档结构，确认 canonical owner、相关事实源和受影响章节；
- 语义或架构变化必须整体重组定位、主链、所有权、E2E、状态和风险，禁止末尾叠加“补充/最新更新”并保留冲突正文；
- 一个事实只允许一个 canonical 文档 owner；其他文档链接引用，不复制可漂移状态表；
- 当前实现、目标设计、历史诊断和执行证据必须分开；
- 修改公共术语、路径或架构后，搜索并删除旧表述、断链、失效引用和重复章节；
- 文档按读者任务组织，不按代码包机械分章；
- 根 `AGENTS.md` 必须保持 500 行以内；新增规则必须合并重复内容。

### 6.4 AI Coding Agent 行为

编码前必须输出目标、所有权、影响边界、E2E 和计划删除内容。

禁止：

- 因不确定新增 fallback，或为兼容保留新旧双轨；
- 未搜索调用方就修改公共模型；
- 用 raw dict 绕过类型边界；
- 新增抽象却不说明变化来源和生产消费者；
- 缺少能力时只写 E2E、Fake、接口或未来阶段，不设计生产落地；
- 未运行测试就声称完成。

无法确认事实 owner、授权边界或外部契约时，应停止相关实现并明确阻塞原因，不得猜测。

---

## 7. 测试、评估、观测与安全

### 7.1 测试职责与覆盖

- Unit：领域不变量和纯函数；
- Contract：Port 与 Adapter 契约；
- Integration / Runtime Conformance：数据库、Checkpoint、Gateway、指定 Tool/Agent、执行顺序和内部协议等白盒组合；
- E2E：目标用户以真实场景和自然表达从正式入口获得可自动断言的用户结果；
- Offline Eval：模型、检索和语义质量；
- Online Evaluation：线上质量、成本、延迟和失败分布。

核心变更按适用性覆盖 Direct Message、只读 ToolCall、Governed Action、Durable Task、Admission/Authorization Denied、Capability Missing、Execution/Verification Failure、replay 不重算且不重复副作用、tenant/context 隔离，以及新路径生效且旧路径不可达。每项变更至少包含一个成功场景和一个失败、拒绝、恢复或重放场景。

新增或改变语义决策、检索、回答、规划和验证时必须先补 Golden Set，覆盖目标用户的多种自然表达、真实目标、边界、失败、反事实和历史回归；禁止用内部 Tool/Agent 名称或预期步骤提示模型来替代能力选择评测。新增 Planner、反思、记忆、路由、缓存、多 Agent 或恢复机制时，必须与最简单 baseline 做同输入对照，比较完成率、错误副作用、模型轮次、token、延迟和恢复结果；无可观察收益时不得进入强制主链。

### 7.2 Observability、安全与审计

Trace 按适用性记录 trace_id、tenant/workspace/user、thread/task、goal、proposal/version、policy/version、command/authorization digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和 error taxonomy；不得记录不必要的密钥、完整敏感内容或跨 scope 数据。

- Identity 和 scope 在入口解析并贯穿调用链；
- Policy 决定是否允许及是否需要审批；
- Gateway 统一执行授权、风险、预算和审计；
- Prompt 不能代替权限控制；
- 高风险操作必须绑定明确 target、payload、授权和确认；
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。

审批、授权、Command、Journal、Receipt、补偿和 Completion 必须关联到同一任务和 canonical digest 链路。审计记录不可被普通业务更新覆盖。

---

## 8. 迁移、ADR 与完成门禁

Schema 或 Model 迁移必须说明 canonical 新模型、数据迁移、调用方迁移、旧写入口关闭、回滚、E2E 和最终删除日期。

以下情况必须创建 ADR：

- 跨模块边界调整或引入新框架/基础设施；
- 新增 Planner、通用状态、持久化投影、多 Agent 拓扑或其他主链复杂度；
- 新增持久化事实，或引入 Event Sourcing、Saga、兼容窗口；
- 改变 Command、digest、Replay、Approval、Verification 或 Completion 语义；
- 偏离本文档中的“必须/禁止”。

ADR 必须包含 1.5 的 `Complexity Justification`、事实/决策 owner、迁移/退出条件、未采用方案和已执行 E2E 证据；ADR 不能代替 E2E。

一项变更只有全部满足下列条件才可合并并视为完成：

- [ ] 用户目标、错误行为、验收结果和 Out of Scope 明确；
- [ ] 同一用户目标的最简单 baseline E2E 已实际执行，失败来自当前 Agent 产品行为且不足得到证明；
- [ ] 所需生产能力已盘点，缺失能力有完整落地设计；
- [ ] Decision/Fact owner、canonical model 和唯一写入口明确；
- [ ] 新增 Model、状态、digest、表、层和模式分别具有不可合并职责及生产消费者；
- [ ] 新增复杂度小于删除复杂度，不存在镜像事实、双写、隐藏 fallback 或无期限兼容；
- [ ] Proposal、Command、Execution Fact、Verification 和 Completion 边界正确；
- [ ] 依赖方向正确，Orchestrator、Validator、Adapter 未创造业务语义；
- [ ] 旧字段、旧路径、临时状态和无消费者投影已删除或具有期限 ADR；
- [ ] 正式入口 E2E 已由目标用户自然表达驱动，未以内部名称或步骤替用户决策，并通过用户结果、关键反事实及至少一个失败/拒绝/恢复/replay 场景；
- [ ] Unit/Contract/Integration/Golden Set 按风险补齐，Trace 和错误分类足以定位问题；
- [ ] 文档整体更新，无冲突正文、重复 owner、失效链接或未来设计冒充当前事实；
- [ ] 验证命令、结果、净复杂度变化和未验证风险已如实记录。

**没有 baseline E2E 证明当前 Agent 的不足，就不得优化；没有目标 E2E 证明用户结果改善，就没有可信落地。**
