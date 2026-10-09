# Knowledge Agent 工程开发规范

> `AGENTS.md` 与 `CLAUDE.md` 是逐字一致的主规范入口。根入口拥有全局门禁；`docs/devSpec/` 拥有任务域细则；目录级 `AGENTS.md` 只补充局部约束。正文归属与检查入口见[开发细则索引](docs/devSpec/README.md)。

本规范覆盖设计、开发、重构、修复、评审、评测、文档与发布。“必须”“禁止”是门禁；实施例外须按 [REL](docs/devSpec/migration-release.md#2-adr-准入)记录依据、风险、验证和退出条件。兼容例外须有删除日期。项目处于正式上线前迭代期。

## 1. 指令读取与渐进式披露

1. 完整阅读根规范，先从用户请求提取目标、交付物和范围。用户附带的规范是约束，不能替代用户目标。
2. 将任务分为产品行为变更、纯内部重构、纯文档修正或只读分析。混合改动分别适用门禁；影响不明确时先核实调用方与契约，再对无法排除的受影响边界采用较严格类别，不得扩大用户授权。
3. 按第 3 节识别实际工作涉及的任务域，打开并完整阅读命中细则；Markdown 链接不会自动加载正文。规范中出现某个术语本身不构成命中。
4. 多任务域取并集；根规范优先，模块规范不得放宽根门禁。同层冲突先修正规范或通过 ADR 明确实施例外，再继续受影响实现；独立工作可继续。
5. 修改前简述变更类型、目标、事实与决策责任主体、影响边界、证据方案、文档影响及删除项。涉及生产结构时补充可达性；文档与只读任务不填造生产证据。说明深度与改动规模相称。

## 2. 适用于所有任务的最高铁律

### 2.1 证据先于设计

- 按第 4 节取得分类证据，证据不足时停止对应生产变更。初始设计文档先记录问题、待证假设与验收计划；生产方案准入须说明已证明问题、责任主体、最小因果改动、反事实和撤回条件，具体执行 [EVD](docs/devSpec/change-evidence.md)。
- Product E2E 必须由目标用户的自然表达进入正式入口，经过生产 Composition Root、真实模型和 canonical 决策、执行、Verification、Completion 链路。脚本替代模型决策、直调组件或注入中间结果只能证明其实际边界，不能作为产品 E2E、baseline 或发布证据。
- E2E 自动断言用户可观察结果与必要反事实。对象存在、工具调用、Trace、状态或局部检查通过不能替代用户结果；内部路径只有属于公开契约时才能成为通过条件。
- 原始用户结果与预声明的局部检查点分别计分。失败按发生位置与因果关系归因；局部通过不能覆盖 E2E 失败，后续独立失败也不能否定已成立机制。候选保留、撤回和重新准入按 [EVD](docs/devSpec/change-evidence.md#1-用户结果与工程约束的可执行基线)处理。
- 默认产品语言为中文。生产 Prompt 的任务逻辑，以及 Product E2E、Golden Set 与 Offline Eval 的用户输入、目标、成功标准、失败反馈和结果解释以中文为主。明确的多语言契约按相同语义建立自然表达镜像，分别验证与报告，不跨语言外推；代码、协议、命令与 URL 保留原文。
- 模型语义设计或异常定位必须审计实际模型请求及构造链，不能只凭模板、输出或可见理由归因。执行 [CTX 输入审计](docs/devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)。
- 核验器漏放已确认错误时，先按 [QLT 最小充分上下文诊断](docs/devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)排除干扰并保留必要事实；充分准确输入仍漏放时，停止当前核验任务的生产准入，重审任务合理性、职责、判据与输入输出契约。
- 后置行为依赖不确定模型前置决策时，按 [EVD 连续验证](docs/devSpec/change-evidence.md#11-模型依赖链必须连续验证)消费同一轨迹的实际输出；理想中间状态、独立采样和成功筛选只能作为条件局部证据。

### 2.2 一个事实只有一个 owner

- 每个业务事实有唯一责任主体、canonical model 和合法业务写入口，明确来源、生命周期、失效与重建规则。禁止多个权威写入口和可独立修改的事实镜像；有实际需求的派生缓存与只读投影可按 [ARC 派生存储规则](docs/devSpec/architecture-ownership.md#61-派生缓存与投影)持久化，不成为第二事实源。
- 模型或外部权威拥有开放语义；确定性代码拥有权限、唯一推导、状态迁移和不变量；执行系统产生执行事实；Verifier 判断语义满足；Completion Gate 检查 required result contract 的证据。分层与模型边界执行 [ARC](docs/devSpec/architecture-ownership.md)。

### 2.3 只实现最小生产纵向切片

- 同一职责只保留一套现行设计与契约，迁移全部生产者、消费者和文档，禁止生产双轨。不同操作和外部适配器的合法差异按 [ARC 契约一致性](docs/devSpec/architecture-ownership.md#11-同一职责采用唯一契约)界定。
- 新结构必须有明确职责、正式入口、装配点、真实消费者及与实际影响匹配的必要性证据，执行 [ARC 生产可达性](docs/devSpec/architecture-ownership.md#7-生产可达性)；持久化事实还须有真实写读者。禁止为框架形式或未来可能性预建抽象、状态、表、流程或治理层。
- 依赖方向为 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 依赖 Port；外层实现 Port，在 Composition Root 装配。
- 正式兼容期前，内部 API、Schema、状态和调用链在同一变更破坏式替换并清理旧路径。真实外部契约、存量生产数据或混合版本部署的兼容按 [REL](docs/devSpec/migration-release.md#1-迁移与兼容边界)处理。

### 2.4 决策、执行与完成不得混装

- Proposal 不代表权限、Command、执行或完成事实。Admission 只接受或拒绝，不补业务语义、改写 payload、替换 Goal、生成 Plan 或静默降级。
- Receipt 不代表 Goal 完成，Verifier 不能推翻确定性执行事实。Plan 控制工作状态，工具表达业务动作；模型提交 FinalMessage 后才验收整体交付，步骤全完成不能替代 Verification 或 Completion Gate。协议执行 [EXE](docs/devSpec/agentic-execution.md)。
- 只读、低风险且可安全重试的调用在 Admission 后直接执行；审批、外部副作用、不可安全重试或跨持久执行、授权、恢复边界时才形成 immutable Command。
- Context 先按 identity 与 scope 做 Visibility，再召回、语义选择和预算物化；禁止让 Prompt 过滤已越权召回的内容。执行 [CTX](docs/devSpec/context-memory-retrieval.md)。

### 2.5 类型、文档与外部依据都是门禁

- 内部自写自读字段及跨层 identity、scope、digest、资源引用必须 typed。raw dict/JSON 只承载外部拥有的内容，在读取边界校验；结构性不变量有唯一命名责任主体和确定性失败判据。
- 模型复述、引用或转交已有具体文字时，通过当前有效的 typed 引用交回，由 Runtime 从唯一责任主体恢复原文；身份、定位与保真不得依赖模型重抄。执行 [COD 文本引用规则](docs/devSpec/code-structure.md#21-已有文字通过引用传递)。
- 生产、核验和评测 Prompt 在职责内通用；具体任务、资料、验收项和答案来自有归属的当前输入。新增或实质修改的 Prompt 是结果优先、最小充分的版本化代码契约，typed 输出只能保证形状。具体执行 [COD](docs/devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)。
- 同一事实只有一份权威文档；当前行为、历史诊断、候选和评测证据分开保存，契约变更同步权威文档。优化候选、失效清理及已解决问题固化由[优化记录规则](docs/optimization/README.md)统一拥有。
- 设计文档写清要解决的问题、解决机制与防护设计。设计时考虑方案引入的问题，并通过责任、契约、执行约束和验证条件避免；正文不列“方案不能做什么”或潜在问题清单。具体写法见[设计文档写法](docs/chinese-writing-spec.md#61-设计文档写法)。
- 外部资料只说明机制，不能替代本工程失败证据。引入或替换架构机制时比较独立 A 级实现，适用范围与不足时的处理按 [EVD 外部参考规则](docs/devSpec/change-evidence.md#6-外部参考的证据分级)执行。

### 2.6 E2E 与 Offline Eval 优先，停用单元测试

自 2026-09-18 起，不新增、维护、修复、收集或运行 `tests/` 下的测试及其他目录的等价单元测试。现有文件和历史证据只读保留，不因其失效阻塞交付，不将旧通过数用于当前验收，也不得迁到 `evals/` 规避规则。

验证投入围绕用户结果、关键契约和真实失败边界组织，不以逐函数覆盖或测试通过数替代能力验收。Real E2E 验收用户结果，Offline Eval 验证真实失败或代表性样本的局部边界；确定性不变量由生产类型、断言及适用回放守住。lint、类型、依赖、配置和文档检查保留。职责与断言取舍执行 [QLT](docs/devSpec/quality-security.md#1-测试职责与覆盖)。

### 2.7 docs-first 与 e2e-first

- 所有设计和优化项必须执行 `docs-first`：在候选实验或实现前创建或更新唯一设计文档，明确要解决或优化的问题、事实与待证假设、目标结果、范围和责任主体。已有对应文档时修订原文，不另建重复方案；会话计划和事后补文档不能替代。流程由 [EVD](docs/devSpec/change-evidence.md#7-强制开发与设计流程)拥有。
- 产品设计同时执行 `e2e-first`：实现前确定正式入口、自然用户请求、可自动断言的用户结果和必要反事实，建立可执行验收并取得第 4 节依据，再实施和运行真实 target E2E。验收判据未明确或无法执行时，不进入对应生产实现；工程重构和纯文档任务按第 4 节选择适用验收，不制造产品 E2E。
- 落地过程中，每轮方案、实现或证据变化必须同步更新对应设计文档及受影响权威正文，明确已实现、已验证和剩余条件，直接删除或改写过期、冗余及冲突描述，不能只在文末追加纠偏，也不能推迟到任务结束。正文归属与生命周期执行 [DOC](docs/AGENTS.md)。

## 3. 任务路由：按识别信号读取细则

识别信号帮助定位实际任务域，不缩小用户请求。涉及多域时读取所有适用细则。

| 规范 | 识别信号 | 必读细则 |
| --- | --- | --- |
| `EVD` | 新增功能、能力优化、设计项、优化项、docs-first、e2e-first、独立阻塞、重复阻塞、方案复审、方案一致性、机制收益、缺陷修复、模型依赖链、baseline、消融、target E2E、工程重构、复杂度准入、外部机制比较 | [变更证据与设计准入](docs/devSpec/change-evidence.md) |
| `REF` | 优秀智能体、外部智能体、Agent Harness 比较、Claude Code 能力参考、GPT/Codex 能力参考、OpenHands 能力参考、DeepSeek Harness 能力参考、Gemini CLI 能力参考、Hermes Agent 能力参考、Letta 能力参考、LangGraph 能力参考 | [优秀智能体能力组件参考](docs/agentRef/README.md) |
| `ARC` | 架构分层、业务事实、决策归属、状态、Schema、Model、Repository、Port、Adapter、Application Capability、Product Aggregate、派生数据、缓存、物化投影、生产可达性 | [架构边界与事实归属](docs/devSpec/architecture-ownership.md) |
| `EXE` | Proposal、Admission、ToolCall、Command、Approval、digest、Receipt、Execution、Verification、Completion、replay、durable execution | [智能体决策与受治理执行](docs/devSpec/agentic-execution.md) |
| `CTX` | Context、System Prompt、模型输入、反馈执行异常、Memory、RAG、Artifact、检索、权限过滤、预算物化、Capability Projection、服务提供方等价绑定 | [上下文、记忆与检索](docs/devSpec/context-memory-retrieval.md) |
| `COD` | 类或模块拆分、内部类型、payload、依赖注入、生产 Prompt、指令模板、文本引用、文字复述、LangGraph、Router、Planner、Workflow、错误分类、命名、编码智能体行为 | [代码组织与实现约束](docs/devSpec/code-structure.md) |
| `DOC` | 新增、修改、移动或评审 Markdown、Mermaid、ADR、评测归档、架构说明、中文写作、文档索引 | [文档模块规范](docs/AGENTS.md) |
| `QLT` | 单元测试、tests/、Offline Eval、Unit、Contract、Integration、Golden Set、Real E2E、E2E 阻塞、核验漏放、最小充分上下文、真实环境 smoke、Trace、安全、权限、审计、评测 | [测试、评估、观测与安全](docs/devSpec/quality-security.md) |
| `REL` | Schema 迁移、协议迁移、兼容窗口、ADR、发布评审、合并验收、完成门禁 | [迁移、ADR 与完成门禁](docs/devSpec/migration-release.md) |

修改 `docs/**`、`evals/**` 或生产 Prompt，分别读取 [DOC](docs/AGENTS.md)、[EVM](evals/AGENTS.md)或 [Prompt 模块规范](src/personal_agent/kernel/prompt_templates/AGENTS.md)。从仓库根启动时也须显式读取，不能假定子目录入口已自动加载。

## 4. 变更准入速查

按消费者、契约、实际模型输入、权限、状态、副作用及恢复行为判断影响；代码行数和文件数量只帮助界定审查范围。混合改动取适用要求的并集。

问题尚未定位时，可按 [EVD 探索边界](docs/devSpec/change-evidence.md#13-探索与生产准入边界)开展基线准备和隔离诊断；探索证据不能替代生产准入。

| 变更类型 | 实现前的必要依据 | 实现后的必要证据 |
| --- | --- | --- |
| 新增或扩展能力、公开契约变更 | 最简单正式入口的失败 baseline，固定用户、自然表达、初始事实和关键反事实 | 真实 target E2E，用户结果、目标契约及适用副作用、成本、延迟或恢复指标达标；单纯能力验收不强制正式消融 |
| 运行机制的独立收益主张 | 对应产品缺口或质量、成本、延迟、恢复约束的基线，声明目标机制、比较变量与指标 | 单变量消融或责任边界因果反事实，加真实 target E2E；结论限定到已证明的机制贡献 |
| 恢复已有契约或确定性不变量的缺陷修复 | 同入口当前或可还原历史产品失败，明确最早责任边界，排除环境与评测错误 | 真实失败输入的 Offline Eval 反事实或 E2E 检查点，同入口真实 target，必要失败、拒绝或恢复场景；不强制正式消融 |
| 严格保持行为的内部重构 | 可重复工程命令证明约束，明确受影响调用方、契约与行为保持依据 | 同命令证明约束下降；静态检查、契约或实际输入对照及适用离线回放证明行为保持，可按细则复用已有证据；依据不足时升级定向真实 E2E |
| 模型语义或模型可见 Prompt、Context、工具协议的实质变更 | 对应变更类别的依据，实际模型请求及构造链审计 | 代表性真实模型评测与受影响任务的真实 E2E；不确定模型依赖链连续验证 |
| 权限、副作用、持久化、迁移或恢复协议变更 | 当前契约及受影响边界，必要拒绝、冲突、故障和恢复判据 | 对应反事实及适用真实 E2E，跨模块或协议决定按 REL 记录 ADR；不能按普通代码重组验收 |
| 纯文档修正 | 代码、配置、既有证据或权威规范坐标；规范整理定位重复、冲突或过期条款 | 正文归属、入口同步、本地链接与锚点、适用结构和路由检查；不制造产品测试 |

证据选择与升级条件由 [EVD](docs/devSpec/change-evidence.md#12-按实际影响选择证据)拥有，历史证据复用的身份与声明边界由 [EVM](evals/AGENTS.md#5-比较身份与归档)拥有。权限、事实归属、E2E 资格与如实报告结论始终适用；发布仍验收目标版本的完整矩阵。

只读分析核实事实并报告依据与限制，不要求制造失败或运行产品测试。纯文档规则不适用于实际改变产品行为的 Prompt、配置或评测契约。存在模型或服务方方差时，两条独立随机轨迹不能作为确定性修复消融；按 EVD 取得责任边界反事实。实验路径只保存在独立代码身份或归档，不保留生产开关、别名或双轨。

## 5. 实现与评审行为

- 改公共模型、Schema、状态或入口前搜索全部调用方和权威文档。保留工作树用户改动，禁止破坏性 Git 操作覆盖。
- 先清理被替代或冲突的内容，再做最小修改。外部依赖与非确定性输入通过 Port 注入，错误分类按 [COD](docs/devSpec/code-structure.md#5-错误注入与命名)，禁止用空结果、默认成功或模糊 fallback 掩盖失败。
- 落地出现已确认非本方案引入的独立阻塞时，必须优先定位并解决，再继续原方案实施与验收；保留原目标、职责边界、核心机制和验收标准，执行 [EVD 独立阻塞处理](docs/devSpec/change-evidence.md#71-独立阻塞优先解决并保持方案一致性)。
- 失败先封存结果、审查断言，定位最早责任主体；一次有界修正后先回跑原失败边界。同一阻塞仍复现时，必须停止受影响路径的候选实验、生产补丁和整轮重跑，按 [EVD 方案复审](docs/devSpec/change-evidence.md#72-重复阻塞先复审方案再继续)重审实际输入、根因、责任和机制，取得新因果依据并更新唯一设计后再准入。更换 Prompt、模块或版本不重置同一阻塞的尝试；独立工作可继续，原方案调整与撤回须有对应因果证据。E2E 的阶段处理执行 [QLT](docs/devSpec/quality-security.md#2-e2e-阻塞按目标阶段和单变量处理)。
- 评审只报告可定位、可复现且影响正确性、安全性、性能或维护门禁的问题。结论不超过已执行证据，未执行的适用检查不得写成通过。

## 6. 完成门禁

按 [REL 完成检查表](docs/devSpec/migration-release.md#3-完成检查表)核对适用项。纯文档与只读任务只执行对应检查；产品改动须达到第 4 节证据，清理旧路径并同步权威文档。

报告实际命令、结果、样本量、复杂度变化及未验证风险；不适用项说明原因。任一适用门禁未满足时，不声明对应工作完成或可上线。
