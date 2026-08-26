# Knowledge Agent 工程开发规范

> 本文档是知识 Agent 项目的唯一强制工程规范，适用于业务与架构设计、文档规划、开发、重构、缺陷修复、测试、评审和上线验收。代码、测试、配置、评测资产和 `docs/` 文档都是受治理的工程资源；文档负责保存当前设计、操作契约、证据边界和未来准入条件，不是代码完成后的附属说明。当前项目处于正式上线前迭代期，全部工程资源按可上线产品标准设计、验证和审计；内部 API、Schema、状态与调用链默认允许破坏式替换并同步迁移全部调用方和权威文档。
> “必须/禁止”属于合并门禁；确需例外时，必须通过 ADR 记录原因、风险、验证、退出条件和移除日期。

---

## 1. 最高铁律

### 1.1 用户结果与工程约束的可执行基线

**任何新增或改变 Application Capability，或声称 Runtime Mechanism 提升用户结果、风险、恢复、成本或延迟的变更，必须依次具有当前最简单生产路径的失败 baseline、目标机制的单变量消融、真实 target E2E 和预先定义的对照指标；四者共同证明“当前不满足、收益来自该机制、真实路径已交付、收益大于代价”。纯内部重构不得编造产品失败：它必须由已执行的工程基线证明可量化约束，并由正式入口 E2E 锁定重构前后用户行为不变。**

**产品 E2E 的职责是证伪当前产品能力，不是演示预设设计能够运行。**必须先确定目标用户、其真实可见信息、自然表达、缺失结果和关键反事实，再选择最简单正式入口；禁止先设计机制，再反向编造恰好需要该机制的场景。

- 产品行为变更前必须从正式入口以用户自然表达执行 baseline，自动断言缺失结果或关键错误；能力/机制变更在 target 实现后，还必须于可还原的独立代码状态中只移除/禁用目标机制的生产消费点执行消融。任一缺口未复现、失败源于环境/测试、或当前路径已满足目标时停止变更。
- 纯内部重构必须声明用户行为不变，并用可重复命令证明具体工程约束，例如生产不可达代码、职责混装、依赖环、变更耦合或复杂度热点；文件行数和主观“不优雅”不能单独准入。其产品 E2E 是回归基线，不得写成失败的能力证据。
- 只有对应基线成立后才能定义 target E2E、适用的消融变量、指标门槛和最小改动；能力/机制变更的 baseline、消融、target 必须分别保存输入/身份/初始事实、环境/配置、模型与 Provider 版本、grader、可还原 commit/tree/patch、trace/report 和 checksum。代码可达性推断、竞品、文档或未执行测试都不能替代证据。
- 未实际执行测试时，禁止声称“已验证”“已修复”或“可上线”。
- Unit 通过、对象存在、状态为 success、数据库新增记录、Tool 被调用或 Trace 命中预期步骤都不能替代用户结果。

合格产品 E2E 必须：

1. 从正式 API、CLI、消息入口或 Application Use Case 进入；
2. 经过生产主路径，而非测试专用旁路；
3. 使用真实领域模型、状态迁移、编排和持久化协议；
4. 自动断言用户可观察结果和关键反事实；
5. 以明确命令在本地或 CI 重复执行，失败时由 trace、event、receipt 或 report 定位阶段；
6. 对 baseline、消融与 target 使用同一入口、用户输入、身份、初始事实和评测契约，消融除唯一目标机制外不偷换条件；
7. target 使用生产 Composition Root、真实持久化和用户结果所依赖的真实模型、Provider 与隔离沙箱；冻结 Provider 只用于可重复消融、故障注入或 Conformance，不能证明真实交付。

除非 Tool、Agent、Workflow、Model、内部 ID 或执行顺序本身就是用户可见产品契约，禁止在 Given/When、Prompt 或测试指令中指定它们，禁止直接构造 Proposal/Command/Checkpoint 替 Agent 完成选择，也禁止让 Fake 替语义决策。生产路径可在执行后通过 Trace/Receipt 断言，不能向用户输入泄漏预期实现来制造通过。需要指定内部对象、Tool、步骤、并发或协议的场景属于 Integration/Runtime Conformance Test，不能单独作为产品能力证据。

Fake/Stub 仅允许用于不可控第三方的可重复消融、危险副作用的故障注入和低层 Contract/Conformance。Fake 必须实现生产 Port 并有 contract test；不得创造生产中不存在的能力，不得替模型、Policy、Admission 或 Verifier 作决定，也不得支撑“真实 E2E 已交付”的声明。

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

正式上线兼容期前，功能、修复和重构默认采用破坏式替换：同一变更迁移全部调用方并删除旧字段、旧写入口和旧执行链。baseline 只保留不可变证据，消融只存在于独立 commit/tree/patch/worktree；禁止为复现实验保留生产 flag、alias、fallback、双写、永久 deprecated 字段或双轨测试入口。

兼容仅用于已确认的真实外部契约、存量生产数据或混合版本部署，并必须通过 ADR 记录适用范围、结束日期、迁移计划、观测指标和删除条件；无这些消费者时不得以回滚或未来上线为由保留旧链路。

### 1.5 禁止无证据优化、过度设计与能力空转

**禁止为了对齐“优秀 Agent”、论文、框架范式、形式完整或未来可能性，提前增加抽象、Model、状态、digest、表、层、Planner、Workflow、Agent、缓存、持久化或治理机制。**外部参考的正确用法见 1.6。

出现以下任一情况即视为过度设计，禁止合并：

- 没有明确业务扩展、当前用户错误或已执行失败的可量化工程约束；
- 能力/机制变更缺少同输入失败 baseline、单变量消融、真实 target E2E 或对照指标，其他产品行为变更没有失败 baseline 与真实 target E2E，或纯重构没有工程基线与行为保持 E2E；
- 新机制只有 Model、DTO、Interface、配置、Fake、测试、Trace、Prompt、文档或展示消费者，没有正式入口、生产构造点、调用者或结果消费者；
- 一个职责被拆成多个 Model、digest、表或层，却没有独立 owner、信任边界、生命周期、事务边界或保留策略；
- 可确定性派生的状态被持久化，或固定流程被包装成通用 Planner/Task/Event 系统；
- 只证明对象存在、字段生成、流程 fail closed，未用预设门槛和样本/重复次数证明用户结果、错误副作用、恢复、成本或延迟得到改善；
- 产品变更新增超过已证明用户结果所需的复杂度，或纯重构没有降低已测约束；旧路径、无消费者投影或临时状态仍保留。

任何新增架构机制必须先提交一份 `Complexity Justification`，并依次证明：

1. 变更类型；能力/机制变更给出用户场景、反事实、失败 baseline、消融变量、真实 target E2E 和指标门槛，其他产品行为变更给出 baseline/target，纯重构给出工程约束基线与行为保持 E2E；
2. 所需能力盘点和完整生产路径，标明已有、需扩展、不存在及真实环境交付；
3. 真实目标 E2E、生产消费者、baseline/消融/target 对照指标和正式入口到结果的可达性；
4. 每个新增 Model/状态/digest/表/流程不可合并的 owner、生命周期或边界；
5. 替代方案、净复杂度预算、同步删除的旧链路、消融代码隔离方式和退出条件。

最小充分设计是默认选择：

- 一个事实、状态、digest、表或流程能满足当前已证明需求时，禁止拆分；
- 只有一个实现且没有外部边界、测试替换需求或近期第二变化来源时，禁止创建 Interface/Factory/Registry；
- Command、Event、Receipt、Projection、View 按各自真实职责选择，禁止为“配套完整”成套创建；
- 已存在但无法补齐上述证据的机制，必须删除、合并，或降为非权威可选投影。

能力只有形成 `正式入口 -> Application Capability -> Domain/canonical state -> 真实 Runtime/Provider/Persistence -> Verification/Completion -> 用户结果` 的最小纵向切片才算落地。每个新增生产结构必须能指出正式入口可达链、生产构造点、调用者/消费者和删除后会失败的测试；持久化事实或投影还必须有真实写入者与读取者，注入式协作者必须在 Composition Root 装配。缺一项即删除，不得以阶段名称或未来接入保留。不可控第三方可以使用生产 Port 的 Fake，但必须有 contract test，并在宣称真实交付或上线前通过真实环境 smoke/E2E；多个独立用例不能拼成组合能力证据。

### 1.6 外部参考的证据分级

**机制选型必须优先参考已落地的优秀 Agent 与业界实现；参考解决“机制怎么做”，不解决“要不要做”。每项产品设计、能力优化或架构机制在提出候选前，必须按机制域核对至少两个相互独立的 A 级实现；确实只有一个时，必须记录检索范围、缺口和不确定性，禁止直接进入实现。**

来源分级。引用时必须标注等级和可复核坐标——仓库路径、规范版本或日期、常量值与契约原文：

- **A 级，可直接采信**：可读源码或规范正文的已发布实现，包括主干仓库代码、协议规范、官方产品文档；能定位到文件、常量和接口契约。
- **B 级，需交叉验证**：官方博客、release note、官方演讲；表明了意图但看不到实现，必须与 A 级或第二个独立来源交叉核对后使用。
- **C 级，仅辅助分析**：论文、教程、示例代码、厂商宣传、个人博客、未合并的 PR 或 issue 描述；只能用于提出候选方案和解释原理。

禁止：

- 用 C 级来源冒充业界实践，或以“最新优秀 Agent 都这么做”替代具体来源；
- 引用转述而未在目标分支源码或规范正文核对（尤其 PR 描述与文章摘要），或给出结论却不给可复核坐标使他人无法独立复核；
- 复制外部实现的对象数量、层次或拓扑，或移植与已证明缺口无关的机制。

正确用法：

1. 形成 `External Mechanism Comparison`：逐项记录实现与提交/版本、生产构造点和消费者、事实 owner、写入/合并/删除或取消语义、生命周期与失效、权限/恢复/失败边界、已付出的复杂度，以及本工程采纳与拒绝的部分；不能因对象、字段或 ID 同名就推定语义等价；
2. 需求来源仍是 1.1 的对应基线——产品变更证明用户结果不足，纯重构证明工程约束；必须先把外部机制映射到本工程失败阶段和责任主体，无法映射的部分不得采用；
3. 对应基线成立后，优先复用本工程现有 contract 和写入口，再选择等级更高、对象更少、可单变量消融的现成语义；禁止照搬外部拓扑、成套对象或为对齐产品名称新增层；
4. 设计评审、实现计划和变更文档必须包含比较结论与可复核坐标；实现中若相同阻塞重复、补丁或 Plan 分支继续增长、责任主体跨层漂移，或 target 指标没有改善，必须暂停局部修补并重新核对外部机制、本工程失败阶段和最小架构边界，允许据此合并或撤回候选、调整框架边界与优化顺序，但不得绕过 1.1 的准入证据；采用后仍必须由本工程的消融、真实目标 E2E 和对照指标证明用户结果改善，外部已验证不等于在本工程有效。

**按机制域检索，不按框架名检索。**下表给出本工程相关机制域的起点，不是推荐技术栈、需求来源或采用理由；清单不完备也不排他，出现等级更高的实现时优先采用并在本表补充坐标。坐标随版本漂移，引用时必须在目标分支源码或规范正文重新核对并按上述分级标注：

| 机制域 | 优先检索对象（起点坐标） |
| --- | --- |
| Tool/资源协议与权限边界 | Model Context Protocol 规范正文（标注 spec 日期版本）；本工程边界见 `src/personal_agent/capabilities/contracts/execution.py` |
| 编排、checkpoint、HITL 中断与 durable execution | 本工程锁定版本对应的 LangGraph/checkpointer 源码；Temporal / Restate 的 determinism、replay、重试与补偿规范 |
| 知识生命周期与时间性失效 | graphiti-core 已发布源码中的 `valid_at` / `invalid_at` 及 provenance；本工程适配见 `src/personal_agent/memory/graphiti/llm_strategies.py` |
| Memory 纠错与污染控制 | Hermes 等已发布源码的 add/replace/remove、scope 和并发语义；必须核对目标提交，不能用 issue 或文档镜像代替实现 |
| Agent 循环、工具调用与安全策略 | OpenAI / Anthropic 官方产品与 API 文档（A 级，标注日期与契约原文） |
| Goal、Plan、Todo 修订与取消 | Gemini CLI 已发布 Plan/Todo 契约、Hermes 已发布 todo 源码及其他可复核 Agent 实现；重点核对完整替换、增量合并、取消/失效、已完成事实保护和上下文重注入语义 |
| 检索与证据组织 | 官方检索/rerank 实现与评测协议正文；论文仅按 C 级用于提出候选 |

---

## 2. 架构边界、能力分层与事实模型

系统目标是高内聚、低耦合、可替换、可验证、可恢复、可审计和可演进；这些目标不构成创建空壳层或提前抽象的理由。禁止把框架协议、运行机制、业务能力和产品生命周期并列称为“能力”或“运行形态”。

### 2.1 强制术语与能力分层

| 层次 | 定义与 owner | 典型内容 |
| --- | --- | --- |
| **Framework Protocol** | 跨业务成立的交互与权力不变量；不拥有业务事实 | Proposal/DecisionFeedback/Observation 契约，Execution/Verification/Completion 分离 |
| **Runtime Mechanism** | 实现 Port 并拥有必要技术执行事实；不决定业务目标或生命周期 | Model/Tool/Agent Adapter、Gateway、Queue/Lease、checkpoint/journal substrate、ArtifactRef、Trace |
| **Application Capability** | 用户可理解、可验收的业务动作；由唯一 Application Use Case 拥有语义、入口和结果契约 | grounded answer、删除知识、创建订阅、启动调查 |
| **Product Aggregate** | 拥有需要独立一致性和持久生命周期的 canonical business facts | Knowledge Item、ResearchSubscription、InvestigationProject |
| **Interface / Projection** | 转换协议或展示 canonical facts；禁止成为第二写入口 | API/CLI/消息 DTO、进度 View、Capability projection |

架构文档中未加限定的 `Capability` 一律指 **Application Capability**。Tool、MCP endpoint、Agent profile、Provider、Workflow 和 Project 都不得与其并列为同类能力：前四者是执行资源或机制，Workflow 是能力内部的固定编排，Project 是业务 Aggregate。`EffectiveCapabilities`、inventory 或模型可见 schema 只是按 identity/scope/policy 生成的只读投影，不拥有 capability definition、可用性或业务事实。

用户或顶层语义路由选择“完成什么”而不是选择 Tool、Workflow 或 Project。Application Capability owner 根据已证明的契约调用 Service/Tool/Agent、执行具体 Workflow，或通过另一明确 Use Case 创建 durable Aggregate；直接 API 与 Agent 入口必须复用同一 Application 写入口。进入已准入 capability 后，模型可以按其公开 contract 提出 ToolCall/AgentDelegation 作为执行步骤，但不能借此改变 Goal、事实 owner 或用户产品路径。

### 2.2 Framework Capability 准入与边界

框架能力是 Framework Protocol 与 Runtime Mechanism 的组合。新增或抽取框架能力除满足 1.1/1.5 外，还必须同时证明：

1. 机制语义与具体业务无关，且被至少两个独立生产消费者需要；仅有一个消费者时，除非外部协议或安全边界强制标准化，否则保留在该 Application 内；
2. 有稳定 typed contract、owner、失败语义、版本/兼容边界及 Contract/Runtime Conformance Test；
3. 不拥有 intent、业务 payload、业务 pending 状态、领域合法迁移、语义完成标准或 canonical business facts；
4. 抽取后由 Application 通过 Port 使用，且删除的重复复杂度大于新增抽象、Registry 和适配成本；
5. 产品 E2E 仍从用户目标验证结果，不能以框架对象存在或 conformance test 代替。

框架可以统一 identity/scope 传播、Proposal/Feedback/Observation envelope、Policy/Admission/Gateway 协议、digest/幂等/审计原语、Queue/Lease、资源引用、Trace 以及 Verification/Completion 的阶段协议。具体 Application/Aggregate 必须继续拥有 Command payload、等待原因、审批后的合法迁移、补偿、Receipt 业务含义和 required result contract。

审批是边界范例：框架可规定认证、授权决策、确认绑定、digest 校验、审计和 typed outcome；Delete Workflow 或 InvestigationProject 分别拥有待确认 Command、confirm/reject 后迁移和恢复行为。禁止创建通用 Approval/Task/Workflow 表成为第二事实 owner，也禁止要求所有业务机械实现 pause/resume/cancel 全套控制。

同一名称或结构若同时出现在 framework 与 domain，必须证明语义完全相同并由 framework contract 单一拥有；否则使用领域限定名称并保持独立。禁止用 converter 同步两个 `Decision`、`State`、`Receipt` 或 `Evidence` 模型。

### 2.3 依赖方向与模块职责

稳定依赖方向为：`Interface -> Application Capability -> Domain/Product Aggregate`；Application 只依赖 Port，Runtime/Governance/Provider Adapter 从外层实现 Port，统一在 Composition Root 装配。

- **Domain / Product Aggregate**：拥有 canonical facts、核心不变量、Command 适用性和确定性迁移；禁止依赖 LangGraph、ORM、模型/MCP SDK、网络、UI 或 Prompt。
- **Application Capability**：接收 Use Case，协调 Domain、语义决策 Port、Governance Port 和 Runtime Port，管理事务和阶段；不得猜测 payload、复制领域规则或把执行失败伪装成成功。
- **Semantic Decision implementation**：模型可提出 Goal/Intent、动态 Plan、下一步和语义验证；必须返回 typed Proposal，不能产生权限、执行事实或业务写入。
- **Governance / Runtime**：执行通用机械协议并返回 decision/result；不得创造 intent、target、payload、业务计划、业务 pending state 或完成结论。
- **Interface / Adapter**：只做协议转换、身份解析、输入校验和 Port 适配；不得补全业务语义、选择业务流程或隐式创建 Aggregate。
- **Observability / Evaluation**：记录和评估事实，不改变生产业务行为。

框架对象不得跨模块成为业务契约；Repository 只保存 Domain/Application 认可的事实；依赖装配集中在 Composition Root；禁止循环依赖和跨层反向调用。分层用于约束职责，不要求每项功能机械创建全部目录、Interface 或 Adapter。

### 2.4 Canonical Model 与状态

禁止在同一 Model 混装：

- Definition：不可变定义；
- Proposal/Command：建议或请求发生什么；
- Event/Receipt：已经发生什么；
- Runtime Projection：当前执行视图；
- View/DTO：展示结构。

只有恢复、审计、重放、授权/审批边界、长生命周期一致性，或无法确定性重建时，才允许持久化派生信息。“以后可能有用”不是理由。

Event 只记录已发生事实。只有具有恢复、审计、重放或长生命周期消费者的核心 Aggregate 才使用完整 Event + Projection；固定小状态机不得默认事件化。

Identity 和 scope 禁止使用空字符串、裸字符串或 raw dict。Identity、reference 或 status 跨 Proposal、Admission、Execution 等阶段沿用时，不得因值相同而隐式继承权威；必须明确各阶段的 owner、权威生效与失效条件、合法消费者和边界断言。语义与权威边界可机械证明不变时允许沿用同一值，禁止为形式分层复制 ID。读取、检索、Tool、Artifact 和 Memory 必须携带并校验适用的 tenant/user/thread/task scope。

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

框架只允许统一 Confirmation 的认证、授权、digest 绑定、审计和 outcome contract；具体 Application/Aggregate 拥有待确认 Command、pending/rejected/executed 状态、合法 decision、确认后的事务/恢复和 Receipt 业务含义。通用确认入口只能分发到 canonical Application 写入口，禁止直接改写业务状态。

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

### 3.4 Durable execution contract

具体 Application Capability 或 Product Aggregate 只有确需跨请求、进程、审批或恢复边界时才使用 durable execution，并至少支持：

- 明确生命周期和合法状态迁移；
- checkpoint 与恢复；
- 相同 digest 的幂等执行；
- replay 不重新调用模型生成 Command；
- typed 失败、retry policy、补偿或 reconcile；
- required report 缺失时 fail closed。

---

## 4. Context、Memory、RAG 与 Capability Projection

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

Capability definition 由对应 Application owner 管理；模型可见 capability、Tool schema、Provider availability 和检索结果都是临时只读投影，必须先 visibility/policy 再 materialize。投影可帮助模型选择 Application Capability，不能替 Agent 完成开放语义选择，也不能反向成为定义或可用性事实源。

只有完整满足同一 `CapabilityEquivalenceClass` 的 Provider 才能确定性绑定；存在语义差异时必须由模型或外部权威选择。

---

## 5. 代码组织与不变量归属

结构存在的意义是让不变量可定位：**每条结构性不变量只能有一个命名 owner，破坏它必须由类型检查或某条确定性断言机械失败。**靠字符串键、散落条件分支或注释维持的不变量视为未实现——重命名字段或更换 provider 后它会静默消失而不亮红灯。提交前必须能说出三件事：承载它的类型或模块名、破坏它的最小改动、因此变红的类型错误或断言。只有依赖模型运行方差才偶发触发的门禁不算被覆盖。

反面同样禁止：概念不得只以类型存在。理念映射到代码指的是不变量有归属，不是每个名词各得一个对象。

设计模式只用于隔离已经发生或由近期业务 E2E 明确要求的变化，并受 1.5 的复杂度准入和 1.6 的参考分级约束。Ports and Adapters、State Machine、Command、Repository、Saga、Decorator、ACL、Registry 均按需使用，不是默认目录模板。

禁止：

- 为每个类创建 Interface、Factory、Manager，或用模式掩盖职责不清；
- 让 Strategy/Router 承担开放语义，或让 Adapter/Converter 维护镜像事实；
- 为未来可能性创建通用 Task、Event、Workflow、Planner、Projection 或兼容层；
- 新增 Model、契约或分层在生产路径零构造点或零读取点：该结构是空转，必须删除或降为可选投影（见 1.5）。

### 5.1 类型边界与 payload 所有权

无 schema 的 `dict[str, Any]`、raw JSON 和裸字符串只允许承载**边界另一侧拥有的内容**：外部 Tool、Provider、MCP endpoint 或用户输入。判据是写入者与读取者，不是字段看起来是否规整：

- 由本层写入又由本层读取的字段必须是 typed 字段。它承载内部不变量而非外部契约，禁止穿 dict 传递；
- 外部拥有的 payload 在读取处必须经 typed 校验，校验失败按「该事实不存在」处理；禁止兜底填充、默认成功、字符串包含或相似度判断；
- identity、scope、digest 和资源引用跨层一律 typed（另见 2.4）。

自写自读却经由 dict 的字段是典型缺陷：键名漂移不产生类型错误，被它守护的门禁静默失效，类型检查与测试都不会亮红。

### 5.2 模块职责、规模与生产可达性

一个模块的职责必须能用一句不含「以及」的话说清。说不清时先检查它是否同时拥有多个 Application Capability 的准入、结果契约或展示投影——这是 God Service 的判据。文件行数、类长度、圈复杂度和类数量只作为评审触发器，禁止按行数机械拆成更多 Manager/Helper；拆分必须形成更清晰的 owner 与依赖方向，并使净理解成本下降。

- 一个 Service 只拥有一个 Application Capability 的 admission、结果契约与展示投影；多 capability 共用入口时，入口只做语义路由、Context 组装、预算与终止判据，各 capability 的准入与投影归各自 owner；
- 抽出的准入模块必须可被独立 contract test 覆盖，且不反向依赖编排。
- 新增或显著增长的文件/类必须报告职责、生产调用方和拆分/不拆分理由；类数量增长必须与同步删除量及新边界对应，禁止以“小类更多就是解耦”为理由。
- 每个 production class、字段、Repository 方法、Projection 和 Adapter 必须从正式入口可达，并有生产构造点及调用者/消费者；持久化事实和 Projection 还必须有写入者与读取者，注入式 Adapter/Service 必须在 Composition Root 装配。仅被测试、迁移脚本或文档引用的结构不是已落地能力，除非它本身就是明确保留期的测试/迁移设施。

### 5.3 LangGraph、Router、Planner 与 Workflow

- Graph 表达编排和迁移，不拥有领域事实；
- Node 只提取输入、调用 Use Case、写回结果，不复制业务规则；
- GraphState 仅存 typed 运行必需状态，大对象使用 ArtifactRef；
- checkpoint 恢复不得重复模型调用或副作用；
- Router/Agent 输出 Goal、Intent 或 Application Capability Proposal，不选择 Repository、Provider、内部 Workflow/Project 模式，也不输出执行完成事实；
- Workflow 不是框架层、用户入口或 capability 类型，只是具体 Application Capability 内对固定业务不变量的编排；
- 新增 Workflow 必须同时具有固定业务不变量、多阶段执行事实、真实审批/恢复/审计/重试/补偿消费者和已失败 baseline；否则使用 Service 或 Application Pipeline；
- 固定依赖由契约或具体 Workflow 定义，只有 Observation 会改变未知依赖时才使用 Planner；
- Planner 不负责授权、执行或完成判定；
- Plan 只有被生产代码消费依据、依赖、进度、预算或完成义务时才能成为强制契约；审阅前仅可执行 Policy 投影为 planning-safe 的低风险读取，planning-safe 不等于严格 read-only，任何其他执行都会关闭新 Plan 的审阅迁移；
- Project 是拥有动态 durable business facts 的 Product Aggregate，不得作为通用 Workflow、路由分支标签或所有长任务的容器；
- Workflow 内固定低风险步骤优先 Service 化；模型动态选择或需要统一 Gateway 治理的执行资源才 Tool 化。

### 5.4 错误、注入与命名

错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure 和 Invariant Violation。禁止捕获异常后返回空结果、默认成功或模糊 fallback。

模型、时钟、ID、Repository、Tool、Policy 和外部 Provider 必须通过 Port 注入；测试不得 monkey patch 生产规则来构造通过结果。

命名必须表达业务角色和生命周期。除非边界明确，禁止使用 `data`、`info`、`manager`、`processor`、`handler` 等泛化名称。

---

## 6. 强制开发、设计与文档流程

每项功能、修复、重构或设计变更都必须同时检查代码链和文档链。纯文档修正可以不制造产品测试，但必须说明事实依据、权威文档和验证范围。

1. 分类为产品行为变更、纯内部重构或纯文档修正；定义用户结果或行为保持契约、反事实、范围外事项，并从 `docs/README.md` 确认受影响主题的权威文档；
2. 产品变更执行同输入失败 baseline；纯重构执行失败的工程约束基线和通过的正式入口行为基线；纯文档修正核对代码、配置、测试或既有执行证据；依据不成立则停止；
3. 基于已证明缺口完成 Decision/Fact Ownership Analysis、Framework/Runtime/Application/Aggregate 分类、所需能力盘点和文档事实归属分析；
4. 按 1.6 检索已落地的业界机制，标注等级和可复核坐标，说明采纳与不采纳的部分；
5. 定义同一真实用户目标的 target E2E、关键反事实、指标门槛与样本量、影响边界、净复杂度预算、证据归档、旧链路删除路径和文档迁移范围；能力或机制变更另定义单变量消融；
6. 以破坏式修改实现最小纵向切片，同步迁移调用方和权威文档，并删除旧代码、冲突正文、失效链接与重复说明；
7. 能力或机制变更在独立可还原代码状态执行 target-minus-mechanism 消融；所有产品行为变更在最终代码执行真实 target E2E；禁止通过当前生产 flag 或测试旁路切换新旧链路；
8. 补充必要的 Unit、Contract、Integration、Golden Set 和真实环境 smoke；执行生产可达性、dead-code、lint、type check，以及文档链接、标题、代码块和 Mermaid 检查；
9. 按预设口径汇总 baseline、消融和 target 的用户结果、错误副作用、成本、延迟与恢复结果；文档只能陈述相应证据支持的结论；
10. 分别封存可复核证据，记录命令、结果、样本量与方差、净复杂度变化、文档变更和剩余风险。

### 6.1 变更分析最小模板

```markdown
## 目标 / 当前错误行为 / 预期用户可见结果
## 变更类型 / 业务扩展或已测工程约束 / 范围外事项
## 产品 baseline / 适用的单变量消融或重构工程与行为基线 / 结果 / 根因
## 真实 target E2E / 关键反事实 / 指标门槛与结果
## 架构分类 / 决策、事实与身份归属 / 权威生命周期与写入口
## 业界机制（等级与坐标）/ 生产责任主体、权威和生命周期证据 / 采纳与拒绝项
## 所需 Application Capability 与 Runtime Mechanism / 尚未交付项
## 生产可达性 / 真实环境证据 / 受影响依赖
## 复杂度增减 / 拒绝方案 / 旧链路删除 / 风险
## 文档影响 / 权威文档 / 当前、未来与证据归档 / 链接和写作检查
```

### 6.2 E2E 最小模板

```markdown
## E2E：<名称>
目标用户：<目标用户、其真实可见信息和公开产品契约>
前置事实：<身份、初始事实和不可由模型预知的测试数据>
用户操作：<从正式入口以该用户的自然表达执行，不泄漏预期内部能力或步骤>
Baseline / 消融：<产品变更记录当前路径失败；能力或机制变更另记录 target-minus-mechanism 退化；纯重构记录重构前行为结果和失败工程约束>
用户结果：<用户可观察结果>
禁止结果：<不得发生的副作用或错误结果>
路径证据：<执行后由 trace、event、receipt 或 report 证明的生产组件，不注入用户输入>
生产可达性：<正式入口、生产构造与装配、调用者与消费者、事实读写和环境>
所需能力与机制：<已有证据、需扩展项、缺失能力落地章节>
允许的 Fake：<仅外部边界>
指标：<预设门槛、样本量与重复次数、完成率或正确性、错误副作用、成本、延迟和恢复对照>
命令：<本地或 CI 命令>
```

### 6.3 文档资源、事实归属与生命周期

**`docs/` 是产品设计和工程交付的一部分。** 代码拥有可执行行为，权威文档解释行为边界、责任主体、使用方式和证据限制；两者必须指向同一当前设计，但文档不能替代运行证据，代码存在也不能替代必要的设计说明。

- `docs/README.md` 负责目录分工和主题权威文档索引；新增文档前必须先确认现有主题是否已有责任主体，能够修改原文时禁止创建第二份说明；
- 当前架构与能力说明进入 `summary/` 或 `topics/`，固定业务链进入 `workflow/`，已接受决策进入 `adr/`，执行结果进入 `evals/`，未解决且已满足准入要求的问题进入 `future/`，面试材料只组织已有事实并链接权威来源；
- 同一事实只能有一个权威文档。其他文档保存面向特定读者的摘要和链接，不复制容易漂移的状态表、流程拓扑、配置清单或证据结论；
- 业务语义、事实归属、公开契约、状态迁移、配置、部署方式或正式路径变化时，必须在同一变更更新相应权威文档；局部实现细节没有文档影响时，也必须在变更说明中明确判断；
- 当前事实、历史诊断、未来候选和评测证据必须分开保存。内容迁移后删除旧正文，不以“补充”“最新版本”或时间流水继续叠加；
- 文档专属变更必须给出代码、配置、测试、执行归档或外部规范坐标。没有事实依据时只能标为待核实，禁止把设计意图写成当前能力。

### 6.4 中文写作与结构门禁

**`docs/chinese-writing-spec.md` 是 `docs/` 全目录中文表达的唯一规范。** 修改文档前必须完整阅读该规范和目标文档；本节只定义工程接入，不复制其中的语法、术语和排版细则。

- 新文档和本次修改的全部段落必须立即符合中文规范；未迁移的存量文字可以保留，但不得继续新增同类问题；
- 先给判断，再说明责任主体、信息流、证据和边界；中文承担句子逻辑，有同名实现的架构角色和代码标识按规范保留；
- 先删除过期、重复和无来源内容，再按读者任务重组章节；禁止在末尾叠加修正段落来掩盖冲突正文；
- 修改公共术语、文件路径或标题后，必须搜索旧表述，并以可重复命令检查本地链接、标题锚点、代码块、表格与 Mermaid；
- 根 `AGENTS.md` 与 `CLAUDE.md` 必须逐字一致且各自不超过 500 行。规则变化必须重组现有章节，禁止仅在末尾累加。

### 6.5 AI Coding Agent 行为

开始实现前必须输出变更类型、目标、所有权、影响边界、产品 baseline/消融/真实 target/指标方案或重构工程基线、生产可达性、文档影响和计划删除内容。

禁止：

- 因不确定新增 fallback，或为兼容保留新旧双轨；
- 未搜索调用方就修改公共模型；
- 用 raw dict 绕过类型边界（判据见 5.1）；
- 新增抽象却不说明变化来源和生产消费者，或新增结构没有正式入口可达链、生产构造/装配点与调用者；
- 让自写自读的内部字段穿 dict 传递，使结构性不变量失去机械判据；
- 把 Model/DTO/Interface/Fake/测试或未装配 Adapter 的横向半成品描述为能力落地，或未接真实环境就宣称可上线；
- 引用外部实践却不给等级和可复核坐标，或未核对源码/规范正文就断言业界做法；
- 未运行测试就声称完成。

当同一阻塞经一次定位和一次有界修正后仍复现，或出现 Plan/补丁分支增长、同一事实多个 owner、跨层 fallback、指标无改善时，必须停止继续追加局部修补：先保存失败证据、当前代码身份和未验证假设，再按 1.6 核对至少两个独立 A 级实现，重新判断根因、owner、架构边界、最小纵向切片和验证顺序；随后在权威设计文档中只保留一个活动方案，合并或撤回失效分支并删除过期描述。外部参考只能帮助调整实现方式，不能替代本工程 baseline 或证明必须新增机制；无法确认事实 owner、授权边界或外部契约时，应明确阻塞原因并停止相关实现，不得猜测。

---

## 7. 测试、评估、观测与安全

### 7.1 测试职责与覆盖

- Unit：领域不变量和纯函数；
- Contract：Port 与 Adapter 契约；
- Integration / Runtime Conformance：数据库、Checkpoint、Gateway、指定 Tool/Agent、执行顺序和内部协议等白盒组合；
- Ablation：在独立可还原代码状态从同一正式入口只移除目标机制，证明收益来自该机制；不得成为生产模式；
- Real E2E：目标用户以真实场景和自然表达，经生产 Composition Root、真实模型/持久化/Provider 获得可自动断言的用户结果；
- Offline Eval：模型、检索和语义质量；
- Online Evaluation：线上质量、成本、延迟和失败分布。

核心变更按适用性覆盖 Direct Message、只读 ToolCall、Governed Action、Durable Execution、Admission/Authorization Denied、Capability Missing、Execution/Verification Failure、replay 不重算且不重复副作用、tenant/context 隔离，以及新路径生效且旧路径不可达。每项变更至少包含一个成功场景和一个失败、拒绝、恢复或重放场景。

新增或改变语义决策、检索、回答、规划、验证及任何声称提升能力的 Runtime 机制时，必须先补 Golden Set，覆盖多种自然表达、真实目标、边界、失败、反事实和历史回归；禁止用内部名称或预期步骤提示模型。必须用同一评测契约对照 baseline、单变量消融和真实 target，预先定义门槛与样本/重复次数，报告完成率/正确性、错误副作用及适用的模型轮次、Tool/Agent 调用、token/cost、延迟、重复副作用和恢复结果；无可观察净收益时不得进入主链。

Framework Protocol 使用 Contract Test，Runtime Mechanism 使用 Runtime Conformance/Integration Test；二者都不能替代 Application Capability 的正式入口 Real E2E。抽取框架能力必须为每个独立生产消费者保留至少一个契约用例，并由原用户目标 Real E2E 证明抽取后行为未退化。

### 7.2 Observability、安全与审计

Trace 按适用性记录 trace_id、tenant/user、thread/task、goal、proposal/version、policy/version、command/authorization digest、tool/provider、attempt、latency、token/cost、receipt、verification、completion 和 error taxonomy；不得记录不必要的密钥、完整敏感内容或跨 scope 数据。

- Identity 和 scope 在入口解析并贯穿调用链；
- Policy 决定是否允许及是否需要审批；
- Gateway 统一执行授权、风险、预算和审计；
- Prompt 不能代替权限控制；
- 高风险操作必须绑定明确 target、payload、授权和确认；
- 批量、删除、外发、不可逆和高成本操作默认提高风险等级。

审批、授权、Command、Journal、Receipt、补偿和 Completion 必须关联到同一任务和 canonical digest 链路。审计记录不可被普通业务更新覆盖。

---

## 8. 迁移、ADR 与完成门禁

正式上线兼容期前，Schema、Model 和内部协议迁移默认直接建立 canonical 新模型、迁移全部数据/调用方并在同一变更关闭旧写入口；回滚依赖版本控制和数据备份，不依赖旧生产链。只有真实外部契约、存量生产数据或混合版本部署需要兼容窗口、迁移观测和最终删除日期。

以下情况必须创建 ADR：

- 跨模块边界调整或引入新框架/基础设施；
- 新增 Planner、通用状态、持久化投影、多 Agent 拓扑或其他主链复杂度；
- 新增持久化事实，或引入 Event Sourcing、Saga、兼容窗口；
- 改变 Command、digest、Replay、Approval、Verification 或 Completion 语义；
- 偏离本文档中的“必须/禁止”。

ADR 必须包含 1.5 的 `Complexity Justification`、1.6 的参考来源与分级、事实/决策 owner、迁移/退出条件、未采用方案和已执行 E2E 证据；ADR 不能代替 E2E。

一项变更只有全部满足下列条件才可合并并视为完成：

- [ ] 变更类型、目标和 Out of Scope 明确；产品能力变更有同输入失败 baseline、单变量消融、真实 target E2E 和预设指标门槛/结果，纯重构有失败工程基线及重构前后通过的行为保持 E2E；
- [ ] 产品 E2E 没有泄漏内部名称、对象或步骤来迎合设计；重构 E2E 未被冒充为产品能力改善；
- [ ] 所需能力已盘点，并形成从正式入口、Application/Domain、真实 Adapter/Provider/Persistence 到 Verification/Completion 和用户结果的纵向切片；
- [ ] 架构分类、Decision/Fact owner、canonical model、唯一写入口和依赖方向明确，Tool/Workflow/Project 未冒充用户能力；
- [ ] 机制选型及适用的遇阻复核已检索优秀 Agent 与业界实现，来源分级和可复核坐标已记录；活动方案已经收敛，未采纳、撤回和调整部分有理由；
- [ ] 每个新增 Model/状态/digest/表/层/类具有不可合并职责、生产构造点和调用者/消费者；持久化事实/投影有真实写读者，注入式协作者已装配；结构性不变量有确定性失败判据；
- [ ] 新增/增长文件与类已报告职责和拆分理由，类数量及净复杂度受控；不存在镜像事实、双写、隐藏 fallback、无期限兼容或仅测试可达的死代码；
- [ ] Proposal、Command、Execution Fact、Verification、Completion 和框架/Application 边界正确；框架抽取具有两个生产消费者或强制边界；
- [ ] 旧字段、旧路径、临时状态和无消费者结构已删除或有期限 ADR；baseline/消融代码未作为生产 flag、fallback 或双轨保留，Fake 未被外推为真实接入；
- [ ] baseline/消融/真实 target 证据分别可还原并封存；Real E2E 及适用的 Unit/Contract/Integration/Golden Set 已通过，指标达到预设门槛并覆盖失败、拒绝、恢复或 replay；
- [ ] 已按 `docs/README.md` 更新权威文档，没有冲突正文、重复 owner、失效链接或未来设计冒充当前事实；新增和修改段落符合 `docs/chinese-writing-spec.md`，文档结构与链接检查已通过；
- [ ] 验证命令、结果、净复杂度变化和未验证风险已如实记录。

**产品能力变更没有失败 baseline、单变量消融、真实 target E2E 和达标对照指标就不得落地；正式代码只保留 target。纯重构没有工程约束证据与行为保持 E2E 就不得合并。**
