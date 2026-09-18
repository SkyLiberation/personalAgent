# Knowledge Agent 工程开发规范

> `AGENTS.md` 与 `CLAUDE.md` 是本项目逐字一致的主规范入口。Codex 自动发现 `AGENTS.md`；其他编码智能体从对应主文档进入。`docs/devSpec/` 保存按任务披露的强制细则。主文档与细则共同构成规范，主文档优先级更高。

本规范适用于设计、开发、重构、修复、测试、评审、文档与上线验收，覆盖代码、测试、配置、评测资产和文档。“必须”“禁止”属于合并门禁；例外必须通过 ADR 记录原因、风险、验证、退出条件和移除日期。项目处于正式上线前迭代期，迁移遵循第 2.3 节。

## 1. 指令读取与渐进式披露

执行任何任务时必须遵循以下顺序：

1. 完整阅读本主文档。用户附带的规范文档是执行约束，不是用户目标；先从用户请求中提取目标、交付物和范围，再应用规范。
2. 将任务分类为产品行为变更、纯内部重构、纯文档修正或只读分析。分类不明确时采用约束更严格且不扩张用户授权的类别。
3. 根据第 3 节的识别信号打开并完整阅读所有命中的细则。Markdown 链接不会自动加载内容，不得只凭链接标题或本摘要行动。
4. 一个任务命中多个任务域时，适用规则取并集。细则冲突时以主文档为准；同层规则冲突时停止实现，先修正规范或通过 ADR 明确例外。
5. 开始修改前，按适用细则输出变更类型、目标、事实与决策 owner、影响边界、证据方案、生产可达性、文档影响和计划删除内容。

细则索引、责任边界、Codex 官方依据与识别评测边界见 [`docs/devSpec/README.md`](docs/devSpec/README.md)。

## 2. 适用于所有任务的最高铁律

### 2.1 证据先于设计

变更必须满足第 4 节的分类证据门禁；证据不足时停止变更。证据设计与失败归因按[变更证据与设计准入](docs/devSpec/change-evidence.md)执行。

- 任何 E2E（包括 baseline、消融、target 和回归）都必须由目标用户的自然表达进入目标智能体的正式入口，经过生产 Composition Root、真实模型及 canonical 决策、执行、Verification、Completion 链路。禁止用脚本或冻结模型替代智能体决策、直调 Application Capability，或注入 Proposal、Observation、Receipt、Artifact、Verification 结果、FinalMessage 制造通过；这些测试只能按实际边界归类为 Unit、Contract、Integration、Runtime Conformance 或 Offline Eval，不得命名为 E2E 或作为产品 baseline、target、发布证据。
- E2E 必须自动断言用户可观察结果和必要反事实。对象存在、`success` 状态、数据库记录、工具调用、Trace 或 Unit 通过均不能替代用户结果。除非内部策略本身属于公开契约，禁止固定工具、智能体、Plan、查询、调用次数与顺序、推理路径、预算消耗或回答措辞。
- 原始用户结果与预声明的局部机制检查点必须分开记录。`limitation`、`failed`、`blocked`、预算耗尽或服务提供方错误是否满足用例，只由预声明的用户结果契约决定；预期成功交付的用例仍记为失败。检查点之后且因果独立的失败仍阻塞产品闭环与发布，但不得否定已成立的机制或迫使候选迎合；局部通过不得覆盖原始 E2E 失败或支撑产品完成声明。
- 默认产品语言为中文。Product E2E、Golden Set 和 Offline Eval 的用户输入、目标、成功标准、失败反馈与结果解释必须以中文为主；英文仅用于技术术语、协议字面量、代码标识、typed 字段或枚举、命令和 URL。英文样本不得替代中文 baseline、target 或回归；明确的英文或多语言契约须按语言建立自然表达镜像样本、固定相同语义原子并分别报告，禁止跨语言外推通过结果。
- 每个设计步骤必须说明失败事实、必要性、责任主体、最小改动、通向用户结果的因果链、验证反事实和撤回条件；不能解释怎样解决已证明问题的步骤，不得进入计划或生产代码。
- 涉及模型语义行为的设计或异常定位，必须按 [System Prompt 与 Context 审计](docs/devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)检查实际模型输入及其构造链，纳入设计依据和验证方案；不得只读模板、输出或可见推理就归因于模型能力或追加提示。输入可疑不等于因果成立，局部动作改善不等于任务完成。
- 任一证据失败时，先保留原始结果，再按检查点前、检查点内、检查点后及因果关系区分评测错误、环境或服务方失败、候选反例、因果回归和独立产品阻塞。只撤回被反例否定、造成回归或无生产消费者的部分，禁止全盘否定已成立的机制与问题。未获准候选仍须删除生产代码和双轨；存在正交方向时，记录被否定假设、新责任边界和重新准入证据。

### 2.2 一个事实只有一个 owner

- 每个业务事实必须有一个权威责任主体、一个 canonical model、一个合法写入口，以及明确的来源、生命周期、失效和重建规则。
- 禁止镜像事实、双写、用 validator/listener/converter 同步副本，或持久化可由 canonical facts 确定性重建的派生值。
- 开放世界语义由模型或外部权威决定；权限、唯一推导、状态迁移和不变量由确定性代码决定；执行系统产生执行事实；Verifier 判断 Goal 的语义满足；Completion Gate 判断 required result contract 的证据是否齐全。

### 2.3 只实现最小生产纵向切片

- 禁止因框架范式、论文、形式完整或未来可能性预建抽象、状态、表、层、Planner、Workflow、Agent、缓存、持久化或治理机制。
- 每个新增生产结构必须有不可合并的职责、正式入口可达链、生产构造或装配点、真实调用者或消费者，以及删除后会失败的 E2E 或 Offline Eval 样本。持久化事实或投影还必须有真实写入者与读取者；仅存在于类型、测试、文档或未装配 Adapter 中的概念不算能力落地。
- 稳定依赖方向是 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 只依赖 Port；Runtime、Governance 和 Provider Adapter 从外层实现 Port，并统一在 Composition Root 装配。
- 正式上线兼容期前，内部 API、Schema、状态与调用链默认破坏式替换：同一变更迁移全部调用方，删除旧字段、旧写入口、旧执行链、临时状态、无消费者结构、测试旁路、fallback 和双轨。真实外部契约、存量生产数据或混合版本部署的兼容例外必须有期限 ADR。

### 2.4 决策、执行与完成不得混装

- Proposal 不是权限、Command、执行事实或完成证明。Admission 只能接受或拒绝 Proposal，不得补业务语义、改写 payload、替换 Goal、生成 Plan 或静默降级。
- Execution Fact、Semantic Verification 与 Completion 必须分离。Receipt 不能直接代表 Goal 完成，Verifier 不能推翻确定性执行事实。
- 新增或修改 Plan 与 ToolCall 协议时，Plan 控制只表达工作状态及其变化，具体工具只表达业务动作；执行系统依据 canonical Plan 关联执行事实。模型提交 FinalMessage 才触发 Semantic Verification，Plan 步骤全部完成不得自动触发交付或替代 Completion Gate。
- 只读、低风险且可安全重试的工具调用在 Admission 后直接执行。需要审批、具有外部副作用、不可安全重试、需要 durable execution 或跨授权或恢复边界的调用才形成 immutable Command。
- Context 必须先按 identity 与 scope 做 Visibility，再进行 Requirement Retrieval、Semantic Selection 和 Budget Materialization。禁止先召回全部内容再让 Prompt 过滤权限。

### 2.5 类型、文档与外部依据都是门禁

- 内部自写自读字段必须 typed；identity、scope、digest 和资源引用跨层一律 typed。raw dict 或 raw JSON 只承载边界另一侧拥有的内容，并在读取处做 typed 校验。
- 每条结构性不变量只能有一个命名责任主体；破坏它必须触发类型错误或确定性断言。
- 新增或实质修改的生产 Prompt 必须是以中文表达、结果优先、最小充分的版本化代码契约，明确动态用户结果、完整产物与成功标准。typed 输出只保证形状，不能证明语义完成；Prompt 不能替代确定性责任主体、无依据固定执行策略或复制 E2E 答案制造通过。结构、Context 边界、分类正反例、失败与停止条件、语言例外和评测要求必须遵守[生产 Prompt 契约](docs/devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)；存量 Prompt 的字节保持迁移不得声称修复语义缺陷。
- 同一事实只能有一份权威文档。当前事实、历史诊断、未来候选和评测证据分开保存；行为或契约变化必须在同一变更更新权威文档。
- 已证明解决特定问题的方案必须按问题固化到 `docs/optimization/completed/`，注明证据适用范围与接入状态；失败尝试只保留方案、失败原因推理及结果总结，移除中间过程正文。确认非本方案引入的新问题须单独登记，禁止作为原问题未完成的理由。固化后其他 optimization 文档只保留 completed 引用，不再跟踪该成功问题。归档、引用迁移与重新打开条件遵循 [optimization 固化规则](docs/optimization/README.md#已解决问题的固化规则)。
- 外部参考只解决“机制怎么做”，不能替代本工程 baseline 来证明“要不要做”。机制候选必须按机制域核对至少两个独立 A 级实现；只有一个时记录检索缺口与不确定性，并停止进入实现。

### 2.6 E2E 与 Offline Eval 优先，停用单元测试

自 2026-09-18 起，后续开发、设计、修复、评审与验收不再新增、维护、修复、收集或运行 `tests/` 下的测试，也不在其他目录新建等价单元测试。现有文件和历史证据只读保留；不得因其未运行或失效而阻塞交付，不得将旧通过数当作当前验收证据。

验证以真实 E2E 和 Offline Eval 为主：E2E 验收正式用户结果，Offline Eval 验证固定样本、历史失败、模型输入和局部因果边界。确定性不变量继续由生产类型及断言保证，按需在 E2E 检查点或真实失败数据的离线回放中检查；禁止把单元测试搬到 `evals/`、改名或改写类别规避本规则。lint、类型检查、依赖、文档及配置检查保留。具体范围与执行顺序见 [QLT](docs/devSpec/quality-security.md#1-测试职责与覆盖)。

## 3. 任务路由：按识别信号读取细则

下表的“识别信号”用于选择细则，不用于缩小用户请求。命中任一信号就必须阅读该行文件；涉及测试、文档或发布的实现任务通常会命中多行。

| 规范 | 识别信号 | 必读细则 |
| --- | --- | --- |
| `EVD` | 新增功能、能力优化、机制收益、缺陷修复、baseline、消融、target E2E、工程重构、复杂度准入、外部机制比较 | [变更证据与设计准入](docs/devSpec/change-evidence.md) |
| `REF` | 优秀智能体、外部智能体、Agent Harness 比较、Claude Code 能力参考、GPT/Codex 能力参考、OpenHands 能力参考、DeepSeek Harness 能力参考、Gemini CLI 能力参考、Hermes Agent 能力参考、Letta 能力参考、LangGraph 能力参考 | [优秀智能体能力组件参考](docs/agentRef/README.md) |
| `ARC` | 架构分层、业务事实、决策归属、状态、Schema、Model、Repository、Port、Adapter、Application Capability、Product Aggregate、生产可达性 | [架构边界与事实归属](docs/devSpec/architecture-ownership.md) |
| `EXE` | Proposal、Admission、ToolCall、Command、Approval、digest、Receipt、Execution、Verification、Completion、replay、durable execution | [智能体决策与受治理执行](docs/devSpec/agentic-execution.md) |
| `CTX` | Context、System Prompt、模型输入、反馈执行异常、Memory、RAG、Artifact、检索、权限过滤、预算物化、Capability Projection、服务提供方等价绑定 | [上下文、记忆与检索](docs/devSpec/context-memory-retrieval.md) |
| `COD` | 类或模块拆分、内部类型、payload、依赖注入、生产 Prompt、指令模板、LangGraph、Router、Planner、Workflow、错误分类、命名、编码智能体行为 | [代码组织与实现约束](docs/devSpec/code-structure.md) |
| `DOC` | 新增、修改、移动或评审 Markdown、Mermaid、ADR、评测归档、架构说明、中文写作、文档索引 | [文档模块规范](docs/AGENTS.md) |
| `QLT` | 单元测试、tests/、Offline Eval、Unit、Contract、Integration、Golden Set、Real E2E、真实环境 smoke、Trace、安全、权限、审计、评测 | [测试、评估、观测与安全](docs/devSpec/quality-security.md) |
| `REL` | Schema 迁移、协议迁移、兼容窗口、ADR、发布评审、合并验收、完成门禁 | [迁移、ADR 与完成门禁](docs/devSpec/migration-release.md) |

目录局部规范作为第二层路由：修改 `docs/**` 时必须读取 [`docs/AGENTS.md`](docs/AGENTS.md)；修改 `evals/**` 时必须读取 [`evals/AGENTS.md`](evals/AGENTS.md)；修改生产 Prompt 时必须读取 [`src/personal_agent/kernel/prompt_templates/AGENTS.md`](src/personal_agent/kernel/prompt_templates/AGENTS.md)。模块规范只收紧或细化根规则，不能放宽全局门禁。

## 4. 变更准入速查

| 变更类型 | 实现前的失败证据 | 实现后的必要证据 |
| --- | --- | --- |
| 新增或扩展 Application Capability、改变公开契约，或声明新 Runtime Mechanism 收益 | 同一正式入口的失败 baseline；目标用户、自然表达、初始事实和关键反事实固定 | target-minus-mechanism 单变量消融；真实 target E2E；预设用户结果、错误副作用、成本、延迟或恢复指标达标 |
| 恢复已有权威契约或确定性不变量的缺陷修复 | 同一正式入口的当前失败或可还原历史失败，证明失败来自产品而非环境或测试；最早责任边界与前置条件明确 | 基于真实失败输入的 Offline Eval 反事实或 E2E 机制检查点；同入口真实 target E2E；成功与失败、拒绝或恢复场景；旧路径删除；不强制正式消融 |
| 纯内部重构 | 可重复命令证明生产不可达、职责混装、依赖环、变更耦合或复杂度热点；重构前正式入口 E2E 通过 | 同命令证明工程约束下降；重构后同一正式入口 E2E 证明行为保持；无新产品能力声明 |
| 纯文档修正 | 代码、配置、测试、既有执行证据或 A 级外部规范坐标 | 权威文档唯一；主入口一致；链接、标题、代码块、表格、Mermaid 和适用识别样本检查通过 |

新设计的 baseline 必须来自当前最简单生产路径；依据成立后，先定义指标门槛再实现。缺陷修复不得扩展产品结果、作用域或策略，无法证明恢复既有契约或确定性不变量时按新设计处理。确定性责任主体之前存在模型或服务方方差时，禁止把两条独立随机轨迹当作消融；须用历史反例证明旧错误、责任边界反事实证明修正、真实 target 验收用户结果。

纯内部重构不得编造产品失败；纯文档修正不制造产品测试。baseline、适用的消融和 target 只保存在可还原的独立代码身份或归档中，禁止用生产 flag、alias、fallback 或双轨入口保留实验链路。

## 5. 实现与评审行为

- 搜索全部调用方和权威文档后再改公共模型、Schema、状态或入口。工作树中的用户改动必须保留，禁止用破坏性 Git 操作覆盖。
- 先删除过期、重复和冲突内容，再实现最小改动；禁止在旧链末尾追加补丁式分支。
- 模型、时钟、ID、Repository、工具、Policy 和外部服务提供方通过 Port 注入；测试不得 monkey patch 生产规则来制造通过。错误分类必须遵守[错误、注入与命名](docs/devSpec/code-structure.md#5-错误注入与命名)，禁止捕获异常后返回空结果、默认成功或模糊 fallback。
- E2E 阻塞时，先审查用例目的与每条断言，再沿正式路径定位最早关键失败，只对一个责任主体做一次有界修正并先回跑原用例；通过前不得扩大修改或运行其余昂贵 E2E。完整流程见[阻塞处理](docs/devSpec/quality-security.md#2-e2e-阻塞按目标阶段和单变量处理)。
- 同一阻塞经一次定位和一次有界修正后仍复现，或 Plan、补丁分支、事实责任主体或跨层 fallback 继续增长时，停止局部修补；保存失败证据，重新判断根因、责任主体、最小边界和验证顺序。停止局部补丁不得扩大为停止继续设计，候选取舍遵循第 2.1 节。
- 代码、测试、配置和文档的结论强度不得超过已执行证据；未实际执行适用测试或文档检查时，禁止声称“已验证”“已修复”“可上线”或“完成”。评审只报告可定位、可复现并影响正确性、安全性、性能或维护门禁的问题。

## 6. 完成门禁

交付前必须按[迁移、ADR 与完成门禁](docs/devSpec/migration-release.md#3-完成检查表)逐项核对本文件及适用细则，确认目标与范围外事项、责任归属和生产可达性明确，第 4 节证据达标，旧路径已清理且权威文档同步。

适用的 Real E2E、Offline Eval（含 Golden Set）、真实环境 smoke、lint、type check、dead-code 和文档检查必须通过；不再要求 `tests/` 或单元测试门禁；如实报告命令、实际结果、样本量、净复杂度变化和未验证风险。任一适用门禁未满足时，不得声称完成或可上线。
