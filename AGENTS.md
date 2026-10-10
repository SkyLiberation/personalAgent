# Knowledge Agent 工程开发规范

> 适用于本仓库全部目录。`AGENTS.md` 是主规范，`CLAUDE.md` 是逐字一致的镜像；修改后同步两者。根入口保留全局门禁，任务细则与目录入口按需读取，正文归属见[开发细则索引](docs/devSpec/README.md)。

本项目是 Python 3.11+ 的个人知识智能体 Runtime，处于正式上线前迭代期。源码在 `src/personal_agent/`，正式评测在 `evals/`，工程检查在 `scripts/`，文档导航见 [docs/README.md](docs/README.md)。依赖与 CLI 入口由 [pyproject.toml](pyproject.toml)定义，当前架构由[核心架构说明](docs/summary/core-architecture-current-state.md)拥有。

本规范覆盖设计、开发、修复、重构、评审、评测、文档与发布。“必须”“禁止”是工程门禁；实施例外按 [REL](docs/devSpec/migration-release.md#2-adr-准入)记录依据、防护、验证和退出条件，兼容例外有删除日期。

## 1. 指令读取与渐进式披露

1. 先从用户请求提取目标、交付物和范围，再完整阅读本入口。遵守更高优先级的会话指令；工程规范是执行约束，不能替代用户目标或扩大授权。
2. 将任务分为产品行为变更、纯内部重构、纯文档修正或只读分析。混合改动分别适用门禁；影响不明确时先核实调用方与契约，再对无法排除的受影响边界采用较严格类别，不得扩大用户授权。
3. 按实际动作和受影响对象选择第 3 节细则，多域取并集，并完整阅读；被引用正文或日志中出现术语不构成生产任务命中。Markdown 链接只提供坐标，不会自动加载指令。
4. 修改文件前，检查从仓库根到目标目录的各级 `AGENTS.md`，读取尚未加载的目录入口；从根目录启动也须执行。目录规范只补充局部规则，不放宽全局门禁；这是工程约束，不改变客户端的指令加载顺序。冲突先修正规范或按 REL 记录实施例外，独立工作可继续。
5. 修改前简述类别、目标、影响、依据、验证和删除项。产品变更补充事实与决策责任及适用可达性；纯文档只说明可定位问题、正文归属和引用影响，只读任务报告事实与限制。

## 2. 适用于所有任务的最高铁律

### 2.1 证据先于设计

- 按第 4 节取得分类证据，证据不足时停止对应生产变更。初始设计文档先记录问题、待证假设与验收计划；生产方案准入须说明已证明问题、责任主体、最小因果改动、反事实和撤回条件，具体执行 [EVD](docs/devSpec/change-evidence.md)。
- 优化以真实 E2E 或其真实中间产物为依据，按实现前已确定用例验收。达到条件即关闭对应问题，不追加泛化、稳定性或范围外门槛；后续新真实 E2E 复现同一失败时再重新打开。执行 [EVD 闭环规则](docs/devSpec/change-evidence.md#14-真实用例驱动优化与验收闭环)。
- Product E2E 必须由目标用户的自然表达进入正式入口，经过生产 Composition Root、真实模型和 canonical 决策、执行、Verification、Completion 链路。脚本替代模型决策、直调组件或注入中间结果只能证明其实际边界，不能作为产品 E2E、baseline 或发布证据。
- E2E 自动断言用户结果与必要反事实；对象、调用、Trace、状态或局部通过不能替代用户结果。原始用户结果与局部检查点分别计分，按最早责任与因果关系归因；内部路径只有属于公开契约时才能作为产品通过条件，独立后续失败不否定已成立机制。
- 默认产品语言为中文。生产 Prompt 的任务逻辑，以及 Product E2E、Golden Set 与 Offline Eval 的用户输入、目标、成功标准、失败反馈和结果解释以中文为主。明确的多语言契约按相同语义建立自然表达镜像，分别验证与报告，不跨语言外推；代码、协议、命令与 URL 保留原文。
- 模型语义设计或异常定位按 [CTX 输入审计](docs/devSpec/context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)核对实际请求、构造链及可用的同轨迹推理记录；依赖前置模型决策时，按 [EVD 连续验证](docs/devSpec/change-evidence.md#11-模型依赖链必须连续验证)消费实际输出。
- 核验漏放按 [QLT](docs/devSpec/quality-security.md#21-核验漏放先验证最小充分上下文)检查最小充分输入；仍漏放时停止对应生产准入并重审任务设计。核验点通用，每次未识别归类到明确判据与真实轨迹用例。

### 2.2 一个事实只有一个 owner

- 每个业务事实有唯一责任主体、canonical model 和合法业务写入口。来源、生命周期、失效与重建规则明确；禁止独立可写镜像。派生缓存与只读投影按 [ARC](docs/devSpec/architecture-ownership.md#61-派生缓存与投影)管理。
- 模型或外部权威拥有开放语义；确定性代码拥有权限、唯一推导、状态迁移和不变量；执行系统产生执行事实；Verifier 判断语义满足；Completion Gate 检查 required result contract 的证据。分层与模型边界执行 [ARC](docs/devSpec/architecture-ownership.md)。

### 2.3 只实现最小生产纵向切片

- 满足当前目标和必要约束时选择最简单方案。新增概念、字段、分类、状态或流程按 [EVD 复杂度准入](docs/devSpec/change-evidence.md#5-复杂度说明complexity-justification)证明必要性，计入模型理解与代码维护成本。
- 同一职责只保留一套现行设计与契约，迁移全部生产者、消费者和文档，删除旧路径；合法操作与适配器差异按 [ARC](docs/devSpec/architecture-ownership.md#11-同一职责采用唯一契约)界定。
- 新结构有明确职责、正式入口、装配点、真实消费者和必要性依据，持久化事实有真实读写者。按 [ARC 可达性](docs/devSpec/architecture-ownership.md#7-生产可达性)检查，禁止为未来可能性预建结构。
- 依赖方向为 `Interface -> Application Capability -> Domain/Product Aggregate`。Application 依赖 Port；外层实现 Port，在 Composition Root 装配。
- 正式兼容期前，内部 API、Schema、状态和调用链在同一变更破坏式替换并清理旧路径。真实外部契约、存量生产数据或混合版本部署的兼容按 [REL](docs/devSpec/migration-release.md#1-迁移与兼容边界)处理。

### 2.4 决策、执行与完成不得混装

- Proposal 不代表权限、Command、执行或完成事实。Admission 只接受或拒绝，不补业务语义、改写 payload、替换 Goal、生成 Plan 或静默降级。
- Receipt 不代表 Goal 完成，Verifier 不能推翻确定性执行事实。Plan 控制工作状态，工具表达业务动作；模型提交 FinalMessage 后才验收整体交付，步骤全完成不能替代 Verification 或 Completion Gate。协议执行 [EXE](docs/devSpec/agentic-execution.md)。
- 只读、低风险且可安全重试的调用在 Admission 后直接执行；审批、外部副作用、不可安全重试或跨持久执行、授权、恢复边界时才形成 immutable Command。
- Context 先按 identity 与 scope 做 Visibility，再召回、语义选择和预算物化；禁止让 Prompt 过滤已越权召回的内容。执行 [CTX](docs/devSpec/context-memory-retrieval.md)。

### 2.5 类型、文档与外部依据都是门禁

- 内部自写自读字段及跨层 identity、scope、digest、资源引用必须 typed。raw dict/JSON 只承载外部拥有的内容，在读取边界校验；结构性不变量有唯一命名责任主体和确定性失败判据。
- 已有文字通过当前有效 typed 引用交回，由 Runtime 恢复原文；身份、定位与保真不依赖模型重抄。执行 [COD 文本引用](docs/devSpec/code-structure.md#21-已有文字通过引用传递)。
- 生产、核验和评测 Prompt 是职责内通用、结果优先、最小充分的版本化契约；具体任务与材料来自当前输入。按 [COD](docs/devSpec/code-structure.md#6-生产-prompt-是版本化代码契约)设计，typed 输出只保证形状。
- 同一事实只有一份权威文档，当前行为、历史诊断、候选与评测证据分开。契约变更同步正文；记录生命周期按 [DOC](docs/AGENTS.md)及[优化规则](docs/optimization/README.md)处理。
- 设计说明问题、解决机制与具体防护，执行[设计文档写法](docs/chinese-writing-spec.md#61-设计文档写法)。外部资料只解释机制，不替代工程失败证据；选型执行 [EVD 外部参考规则](docs/devSpec/change-evidence.md#6-外部参考的证据分级)。

### 2.6 E2E 与 Offline Eval 优先，停用单元测试

自 2026-09-18 起，不新增、维护、修复、收集或运行 `tests/` 及其他目录的等价单元测试，也不迁到 `evals/` 规避规则。现有文件与历史证据只读保留，不以失效或旧通过数阻塞或证明本次交付。Real E2E 验收用户结果，Offline Eval 验证局部边界；lint、类型、依赖、配置和文档检查保留。职责、替身与断言规则由 [QLT](docs/devSpec/quality-security.md#1-测试职责与覆盖)拥有。

### 2.7 docs-first 与 e2e-first

- 设计与优化项在候选实验或实现前更新唯一设计文档；产品项同时固定正式入口、自然请求、用户结果、反事实与可执行验收，取得第 4 节依据后实施。会话计划和事后补文档不能替代。执行 [EVD 流程](docs/devSpec/change-evidence.md#7-强制开发与设计流程)。
- 每轮方案、实现或证据改变时，同步设计与受影响权威正文，区分已实现、已验证和剩余条件，直接清理过期、重复与冲突内容。纯文档按 DOC 检查，只读分析按事实报告。

### 2.8 可读性优先，模块化控制开发上下文

按清楚的职责、命名、typed 契约和控制流组织代码与文档。模块化减少局部任务的必要查阅范围，明确入口和直接协作者，并计入跨文件跳转与协作成本；禁止按行数机械拆分。执行 [COD](docs/devSpec/code-structure.md#3-模块职责规模与生产可达性)及 [DOC](docs/AGENTS.md#2-中文写作与结构门禁)。

## 3. 任务路由：按识别信号读取细则

按任务动作与实际影响选读下表，识别信号只用于定位。整理规范正文通常命中 DOC；只有同时改变产品行为才并用对应生产细则。外部机制调研才读取 REF，不因规范中列有厂商名自动读取。

| 规范 | 适用任务与识别信号 | 必读细则 |
| --- | --- | --- |
| `EVD` | 新增功能、能力优化、缺陷修复、工程重构；制定设计项、优化项、docs-first、e2e-first、baseline、消融、target E2E；处理独立阻塞、重复阻塞、方案复审、方案一致性；审查模型依赖链、奥卡姆剃刀与复杂度准入 | [变更证据与设计准入](docs/devSpec/change-evidence.md) |
| `REF` | 调研优秀智能体、外部智能体或 Agent Harness 比较；参考 Claude Code、GPT/Codex、OpenHands、DeepSeek Harness、Gemini CLI、Hermes Agent、Letta、LangGraph 的外部能力机制 | [优秀智能体能力组件参考](docs/agentRef/README.md) |
| `ARC` | 调整架构分层、业务事实与状态归属；设计 Schema、Model、Repository、Port、Adapter；核对 Application Capability、Product Aggregate、派生数据、缓存、物化投影和生产可达性 | [架构边界与事实归属](docs/devSpec/architecture-ownership.md) |
| `EXE` | 修改 Proposal、Admission、ToolCall 协议；调整 Command、Approval、digest、Receipt 的执行绑定；设计 Execution、Verification、Completion、replay 与 durable execution | [智能体决策与受治理执行](docs/devSpec/agentic-execution.md) |
| `CTX` | 审计 Context、System Prompt、模型输入、模型推理记录和反馈执行异常；调整 Memory、RAG、Artifact、检索、权限过滤、预算物化；核对 Capability Projection 与服务提供方等价绑定 | [上下文、记忆与检索](docs/devSpec/context-memory-retrieval.md) |
| `COD` | 改善可读性、功能模块化与 Code Agent 开发上下文，进行类或模块拆分；修改内部类型、payload、依赖注入、错误分类、命名；设计生产 Prompt、文本引用、文字复述或 LangGraph、Router、Planner、Workflow 编排 | [代码组织与实现约束](docs/devSpec/code-structure.md) |
| `DOC` | 整理 Markdown、Mermaid、AGENTS.md、CLAUDE.md 与 ADR 正文；维护评测说明、架构说明、中文写作、文档索引；规范整理与引用清理 | [文档模块规范](docs/AGENTS.md) |
| `QLT` | Real E2E、Offline Eval、Golden Set 与真实环境 smoke 的验证设计；解释停用范围与历史证据：单元测试、tests/、Contract、Integration；定位 E2E 阻塞、核验漏放、最小充分上下文；核对 Trace、安全、权限、审计与评测职责 | [测试、评估、观测与安全](docs/devSpec/quality-security.md) |
| `REL` | 实施 Schema 迁移、协议迁移与兼容窗口；记录 ADR；执行发布评审、合并验收与完成门禁 | [迁移、ADR 与完成门禁](docs/devSpec/migration-release.md) |

| 目标目录 | 修改前追加读取 |
| --- | --- |
| `docs/**` | [DOC](docs/AGENTS.md)，再按文档类型读取对应索引 |
| `evals/**` | [EVM](evals/AGENTS.md) |
| `src/personal_agent/kernel/prompt_templates/**` | [Prompt 模块规范](src/personal_agent/kernel/prompt_templates/AGENTS.md) |

读取目录入口时只加载它要求的适用细则；遇到其他目录新增入口，按第 1 节检查，不以此表替代文件发现。

## 4. 变更准入速查

按消费者、契约、实际模型输入、权限、状态、副作用及恢复行为判断影响；代码行数和文件数量只帮助界定审查范围。混合改动取适用要求的并集。

问题尚未定位时，可按 [EVD 探索边界](docs/devSpec/change-evidence.md#13-探索与生产准入边界)开展基线准备和隔离诊断；探索证据不能替代生产准入。

下表拥有分类最低证据。取得与升级证据执行 EVD，局部优化、完整用户结果与发布分别按各自已确定用例验收。

| 变更类型 | 实现前的必要依据 | 实现后的必要证据 |
| --- | --- | --- |
| 新增或扩展能力、公开契约变更 | 最简单正式入口的失败 baseline，固定用户、自然表达、初始事实和关键反事实 | 真实 target E2E，用户结果、目标契约及适用副作用、成本、延迟或恢复指标达标；单纯能力验收不强制正式消融 |
| 运行机制的独立收益主张 | 对应产品缺口或质量、成本、延迟、恢复约束的基线，声明目标机制、比较变量与指标 | 单变量消融或责任边界因果反事实，加真实 target E2E；结论限定到已证明的机制贡献 |
| 恢复已有契约或确定性不变量的缺陷修复 | 同入口当前或可还原历史产品失败，明确最早责任边界，排除环境与评测错误 | 已确定的真实阶段输入 Offline Eval 反事实、E2E 检查点或同入口真实 target，以及对应必要失败、拒绝或恢复场景；不强制正式消融 |
| 严格保持行为的内部重构 | 可重复工程命令证明约束，明确受影响调用方、契约与行为保持依据 | 同命令证明约束下降；静态检查、契约或实际输入对照及适用离线回放证明行为保持，可按细则复用已有证据；依据不足时升级定向真实 E2E |
| 模型语义或模型可见 Prompt、Context、工具协议的实质变更 | 对应变更类别的真实 E2E 或同轨迹真实产物依据，实际模型请求及构造链审计 | 按已确定用例执行真实 E2E 或完整真实阶段输入的模型回放；目标涉及不确定模型依赖链时连续验证 |
| 权限、副作用、持久化、迁移或恢复协议变更 | 当前契约及受影响边界，必要拒绝、冲突、故障和恢复判据 | 对应反事实及适用真实 E2E，跨模块或协议决定按 REL 记录 ADR；不能按普通代码重组验收 |
| 纯文档修正 | 代码、配置、既有证据或权威规范坐标；规范整理定位重复、冲突或过期条款 | 正文归属、入口同步、本地链接与锚点、适用结构和路由检查；不制造产品测试 |

证据选择与升级由 [EVD](docs/devSpec/change-evidence.md#12-按实际影响选择证据)拥有，历史证据身份由 [EVM](evals/AGENTS.md#5-比较身份与归档)拥有。只读分析无需制造失败或产品测试；模型可见 Prompt、配置和评测判据的行为变更不按纯文档验收。独立随机轨迹不充当确定性修复消融，实验路径留在独立身份或归档。

## 5. 实现与评审行为

- 改公共模型、Schema、状态或入口前搜索全部调用方和权威文档。保留工作树用户改动，禁止破坏性 Git 操作覆盖。
- 先删除被替代或冲突内容，再做最小修改；依赖注入与错误分类执行 [COD](docs/devSpec/code-structure.md#5-错误注入与命名)，禁止以空结果、默认成功或模糊 fallback 掩盖失败。
- 独立阻塞按 [EVD 第 7.1 节](docs/devSpec/change-evidence.md#71-独立阻塞优先解决并保持方案一致性)优先解决并保留原方案；同一阻塞经一次有界修正仍复现时，停止受影响路径的新实验、补丁及整轮重跑，按 [EVD 第 7.2 节](docs/devSpec/change-evidence.md#72-重复阻塞先复审方案再继续)复审后重新准入。更换措辞、模块或版本不重置尝试；独立工作可继续。
- 评审只报告可定位、可复现且影响正确性、安全性、性能或维护门禁的问题。结论不超过已执行证据，未执行的适用检查不得写成通过。

## 6. 完成门禁

按 [REL 完成检查表](docs/devSpec/migration-release.md#3-完成检查表)核对适用项。纯文档与只读任务只执行对应检查；产品改动须达到第 4 节证据，清理旧路径并同步权威文档。

报告实际命令、结果、样本量、复杂度变化及未验证风险；不适用项说明原因。任一适用门禁未满足时，不声明对应工作完成或可上线。

从仓库根运行检查；本地使用 `.venv` 的 Python，其他环境使用对应解释器。规范整理运行 `.\.venv\Scripts\python.exe scripts/check_dev_spec.py`。代码依赖与导入检查入口为 `scripts/check_layers.py` 和 CI 的 `ruff check --select F401,F811,F821 src scripts`；按实际影响选用。评测运行命令由[运行与发布](docs/evals/04-running-and-release.md)拥有，纯文档任务不启动产品 E2E 或真实模型。
