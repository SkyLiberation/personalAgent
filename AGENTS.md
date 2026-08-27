# Knowledge Agent 工程开发规范

> `AGENTS.md` 与 `CLAUDE.md` 是本项目逐字一致的主规范入口。Codex 自动发现 `AGENTS.md`；其他编码智能体从对应主文档进入。`docs/devSpec/` 保存按任务披露的强制细则。主文档与细则共同构成规范，主文档优先级更高。

本规范适用于业务与架构设计、文档规划、开发、重构、缺陷修复、测试、评审和上线验收。代码、测试、配置、评测资产和 `docs/` 文档都是受治理的工程资源。项目处于正式上线前迭代期；内部 API、Schema、状态与调用链默认允许破坏式替换，并同步迁移全部调用方和权威文档。“必须”“禁止”属于合并门禁；例外必须通过 ADR 记录原因、风险、验证、退出条件和移除日期。

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

- 新增或改变 Application Capability，或声称 Runtime Mechanism 改善用户结果、风险、恢复、成本或延迟时，必须依次取得当前最简单生产路径的失败 baseline、目标机制的单变量消融、真实 target E2E 和预先定义的对照指标。
- 其他产品行为变更必须有同输入失败 baseline 与真实 target E2E。纯内部重构不得编造产品失败，必须有已执行的工程约束基线和重构前后行为保持 E2E。纯文档修正不制造产品测试，但必须核对权威事实并执行文档检查。
- 产品 E2E 从正式入口以目标用户的自然表达进入生产主路径，自动断言用户可观察结果和关键反事实。Unit、对象存在、状态 success、数据库记录、工具调用或 Trace 不能替代用户结果。
- 未实际执行测试时，禁止声称“已验证”“已修复”“可上线”或“完成”。

### 2.2 一个事实只有一个 owner

- 每个业务事实必须有一个权威 owner、一个 canonical model、一个合法写入口，以及明确的来源、生命周期、失效和重建规则。
- 禁止镜像事实、双写、用 validator/listener/converter 同步副本，或持久化可由 canonical facts 确定性重建的派生值。
- 开放世界语义由模型或外部权威决定；权限、唯一推导、状态迁移和不变量由确定性代码决定；执行系统产生执行事实；Verifier 判断 Goal 的语义满足；Completion Gate 判断 required result contract 的证据是否齐全。

### 2.3 只实现最小生产纵向切片

- 禁止因框架范式、论文、形式完整或未来可能性预建抽象、状态、表、层、Planner、Workflow、Agent、缓存、持久化或治理机制。
- 每个新增生产结构必须有正式入口可达链、生产构造或装配点、真实调用者或消费者，以及删除后会失败的测试。持久化事实或投影还必须有真实写入者与读取者。
- 稳定依赖方向是 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 只依赖 Port；Runtime、Governance 和 Provider Adapter 从外层实现 Port，并统一在 Composition Root 装配。
- 正式上线兼容期前默认破坏式替换：同一变更迁移全部调用方，并删除旧字段、旧写入口、旧执行链、fallback 和双轨。真实外部契约、存量生产数据或混合版本部署的兼容例外必须有期限 ADR。

### 2.4 决策、执行与完成不得混装

- Proposal 不是权限、Command、执行事实或完成证明。Admission 只能接受或拒绝 Proposal，不得补业务语义、改写 payload、替换 Goal、生成 Plan 或静默降级。
- Execution Fact、Semantic Verification 与 Completion 必须分离。Receipt 不能直接代表 Goal 完成，Verifier 不能推翻确定性执行事实。
- 只读、低风险且可安全重试的工具调用在 Admission 后直接执行。需要审批、具有外部副作用、不可安全重试、需要 durable execution 或跨授权或恢复边界的调用才形成 immutable Command。
- Context 必须先按 identity 与 scope 做 Visibility，再进行 Requirement Retrieval、Semantic Selection 和 Budget Materialization。禁止先召回全部内容再让 Prompt 过滤权限。

### 2.5 类型、文档与外部依据都是门禁

- 内部自写自读字段必须 typed；identity、scope、digest 和资源引用跨层一律 typed。raw dict 或 raw JSON 只承载边界另一侧拥有的内容，并在读取处做 typed 校验。
- 一条结构性不变量只能有一个命名 owner；破坏它必须触发类型错误或确定性断言。只存在于类型、测试、文档或未装配 Adapter 中的概念不算能力落地。
- 同一事实只能有一份权威文档。当前事实、历史诊断、未来候选和评测证据分开保存；行为或契约变化必须在同一变更更新权威文档。
- 外部参考只解决“机制怎么做”，不能替代本工程 baseline 来证明“要不要做”。机制候选必须按机制域核对至少两个独立 A 级实现；只有一个时记录检索缺口与不确定性，并停止进入实现。

## 3. 任务路由：按识别信号读取细则

下表的“识别信号”用于选择细则，不用于缩小用户请求。命中任一信号就必须阅读该行文件；涉及测试、文档或发布的实现任务通常会命中多行。

| 规范 | 识别信号 | 必读细则 |
| --- | --- | --- |
| `EVD` | 新增功能、能力优化、机制收益、缺陷修复、baseline、消融、target E2E、工程重构、复杂度准入、外部机制比较 | [变更证据与设计准入](docs/devSpec/change-evidence.md) |
| `ARC` | 架构分层、业务事实、决策归属、状态、Schema、Model、Repository、Port、Adapter、Application Capability、Product Aggregate、生产可达性 | [架构边界与事实归属](docs/devSpec/architecture-ownership.md) |
| `EXE` | Proposal、Admission、ToolCall、Command、Approval、digest、Receipt、Execution、Verification、Completion、replay、durable execution | [智能体决策与受治理执行](docs/devSpec/agentic-execution.md) |
| `CTX` | Context、Memory、RAG、Artifact、检索、权限过滤、预算物化、Capability Projection、服务提供方等价绑定 | [上下文、记忆与检索](docs/devSpec/context-memory-retrieval.md) |
| `COD` | 类或模块拆分、内部类型、payload、依赖注入、LangGraph、Router、Planner、Workflow、错误分类、命名、编码智能体行为 | [代码组织与实现约束](docs/devSpec/code-structure.md) |
| `DOC` | 新增、修改、移动或评审 Markdown、Mermaid、ADR、评测归档、架构说明、中文写作、文档索引 | [文档模块规范](docs/AGENTS.md) |
| `QLT` | Unit、Contract、Integration、Golden Set、Real E2E、真实环境 smoke、Trace、安全、权限、审计、评测 | [测试、评估、观测与安全](docs/devSpec/quality-security.md) |
| `REL` | Schema 迁移、协议迁移、兼容窗口、ADR、发布评审、合并验收、完成门禁 | [迁移、ADR 与完成门禁](docs/devSpec/migration-release.md) |

目录局部规范作为第二层路由：修改 `docs/**` 时必须读取 [`docs/AGENTS.md`](docs/AGENTS.md)；修改 `evals/**` 时必须读取 [`evals/AGENTS.md`](evals/AGENTS.md)。模块规范只收紧或细化根规则，不能放宽全局门禁。

## 4. 变更准入速查

| 变更类型 | 实现前的失败证据 | 实现后的必要证据 |
| --- | --- | --- |
| Application Capability 新增或改变、声称 Runtime Mechanism 改善结果 | 同一正式入口的失败 baseline；目标用户、自然表达、初始事实和关键反事实固定 | target-minus-mechanism 单变量消融；真实 target E2E；预设用户结果、错误副作用、成本、延迟或恢复指标达标 |
| 其他产品行为变更或缺陷修复 | 同输入失败 baseline，证明失败来自产品而非环境或测试 | 同入口真实 target E2E；成功与失败、拒绝或恢复场景；旧路径删除 |
| 纯内部重构 | 可重复命令证明生产不可达、职责混装、依赖环、变更耦合或复杂度热点；重构前正式入口行为通过 | 同命令证明工程约束下降；重构后同一正式入口行为保持；无新产品能力声明 |
| 纯文档修正 | 代码、配置、测试、既有执行证据或 A 级外部规范坐标 | 权威文档唯一；主入口一致；链接、标题、代码块、表格、Mermaid 和适用识别样本检查通过 |

对应证据不成立时必须停止变更。baseline、消融和 target 只保存在可还原的独立代码身份或归档中；不得用生产 flag、alias、fallback 或双轨入口保留实验链路。

## 5. 实现与评审行为

- 搜索全部调用方和权威文档后再改公共模型、Schema、状态或入口。工作树中的用户改动必须保留，禁止用破坏性 Git 操作覆盖。
- 先删除过期、重复和冲突内容，再实现最小改动；禁止在旧链末尾追加补丁式分支。
- 模型、时钟、ID、Repository、工具、Policy 和外部 Provider 通过 Port 注入；测试不得 monkey patch 生产规则来制造通过。
- 错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure 和 Invariant Violation。禁止捕获异常后返回空结果、默认成功或模糊 fallback。
- 当同一阻塞经一次定位和一次有界修正后仍复现，或 Plan、补丁分支、事实 owner 或跨层 fallback 继续增长时，停止局部修补；保存失败证据，重新判断 root cause、owner、最小边界和验证顺序。
- 代码、测试、配置和文档的结论强度不得超过已执行证据。评审只报告可定位、可复现并影响正确性、安全性、性能或维护门禁的问题。

## 6. 完成门禁

交付前必须确认：

- 变更类型、目标、Out of Scope、事实与决策 owner、唯一写入口、依赖方向和生产可达性明确；
- 适用的 baseline、单变量消融、真实 target E2E、工程基线或文档事实核对已经实际执行，结果达到预设门槛；
- 每个新增 Model、状态、digest、表、层、类或投影有不可合并职责、生产消费者和确定性失败判据；
- 旧字段、旧路径、镜像事实、临时状态、无消费者结构、测试旁路和无期限兼容已删除，或存在满足期限要求的 ADR；
- 适用的 Unit、Contract、Integration、Golden Set、Real E2E、真实环境 smoke、lint、type check、dead-code 和文档检查已通过；
- 权威文档已同步，没有冲突正文、重复 owner、失效链接或未来设计冒充当前事实；
- 验证命令、实际结果、样本量、净复杂度变化和未验证风险已经如实报告。

任一适用项未满足时，不得声称完成或可上线。完整检查表见[迁移、ADR 与完成门禁](docs/devSpec/migration-release.md)。
