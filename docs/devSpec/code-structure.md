# 代码组织与实现约束细则（COD）

> 本细则适用于模块拆分、内部类型、payload、依赖注入、生产 Prompt、编排、错误分类、命名和编码智能体行为。事实与分层由[ARC](architecture-ownership.md)拥有；证据和复杂度准入由[EVD](change-evidence.md)拥有。

## 1. 不变量必须有唯一归属

每条结构性不变量须有命名责任主体和确定性失败判据。提交前必须指出承载类型或模块、破坏不变量的最小改动，以及因此失败的类型检查或断言；仅依赖模型方差偶发触发不算覆盖。

靠字符串键、散落条件或注释维持的内部不变量视为未实现；重命名字段或更换服务方后不得静默失效。概念映射到代码不等于为每个名词创建对象。

设计模式只隔离已经发生或近期业务 E2E 明确要求的变化，并受[EVD 复杂度准入](change-evidence.md#5-复杂度说明complexity-justification)约束。禁止为每个类创建 Interface、Factory 或 Manager，使用模式掩盖职责不清，或让 Strategy/Router 承担开放语义、Adapter/Converter 同步镜像事实。

## 2. 类型边界与 payload 所有权

判定类型边界要看谁写入、谁读取，不能只看字段是否规整。内部自写自读字段及跨层 identity、scope、digest、资源引用遵守根规范的 typed 门禁。

无 schema 的 `dict[str, Any]`、raw JSON 和裸字符串只允许承载边界另一侧拥有的内容，例如外部工具、服务提供方、MCP endpoint 或用户输入。读取处 typed 校验失败时按事实缺失处理；禁止兜底填充、默认成功，或用字符串包含与相似度代替校验。

内部 typed contract 不要求将整个对象原样注入模型。面向模型的语义说明与面向程序的结构化消费，按 [CTX 表达分工](context-memory-retrieval.md#11-模型输入优先表达语义机器消费保持结构化)处理；可读文本只投影已有事实，不承担内部状态或控制协议。

## 3. 模块职责、规模与生产可达性

一个模块的职责必须能用一句不含“以及”的话说清。说不清时，检查它是否同时拥有多个 Application Capability 的准入、结果契约或展示投影；这是 God Service 的判据。

- 一个 Service 只拥有一个 Application Capability 的上述职责。多个能力共用入口时，入口只做语义路由、Context 组装、预算与终止判断；各能力的准入与投影归各自责任主体。
- 抽出的准入模块必须可由 E2E 检查点或真实失败输入的 Offline Eval 覆盖，且不得反向依赖编排。
- 文件行数、类长度、圈复杂度和类数量只触发评审，不能据此机械增加 Manager 或 Helper。拆分必须使责任与依赖更清楚，降低净理解成本。
- 新增或显著增长的文件、类须报告职责、生产调用方和拆分或不拆分理由。类数量增长须对应删除量与新边界，不得以“小类更多就是解耦”为由。
- 类、字段、Repository 方法、投影、Adapter 及注入式协作者均须通过[生产可达性检查](architecture-ownership.md#7-生产可达性)。仅测试、迁移脚本或文档引用的结构不算能力落地；明确保留期的测试或迁移设施按其真实用途声明。

## 4. LangGraph、Router、Planner 与 Workflow

编排只组织工作，不接管业务事实或开放语义决策。具体边界如下：

- Graph 表达编排与迁移，不拥有领域事实；Node 只提取输入、调用 Use Case、写回结果，不复制业务规则。
- GraphState 只保存 typed 运行必需状态，大对象使用 `ArtifactRef`；checkpoint 恢复不得重复模型调用或副作用。
- Router 或智能体输出 Goal、Intent 或 Application Capability Proposal，不选择 Repository、Provider、内部 Workflow 或 Project 模式，也不输出执行完成事实。
- Workflow 只编排具体能力内的固定业务不变量，不是框架层、用户入口或能力类型。新增 Workflow 必须具备固定不变量、多阶段执行事实、真实审批、恢复、审计、重试或补偿消费者，以及已失败 baseline；否则使用 Service 或 Application Pipeline。
- 固定依赖由契约或具体 Workflow 定义；只有 Observation 会改变未知依赖时才使用 Planner，Planner 不负责授权、执行或完成判定。
- Plan 只有其依据、依赖、进度、预算或完成义务被生产代码消费时，才能成为强制契约。审阅前只可执行 Policy 投影为 planning-safe 的低风险读取；planning-safe 不等于严格 read-only，其他执行会关闭新 Plan 的审阅迁移。
- Project 是拥有动态、需持久保存的业务事实的 Product Aggregate，不得作为通用 Workflow、路由分支标签或所有长任务的容器。
- Workflow 内固定低风险步骤优先由 Service 执行；模型动态选择或需要统一执行网关治理的执行资源才封装为工具。

## 5. 错误、注入与命名

错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure 和 Invariant Violation。禁止捕获异常后返回空结果、默认成功或模糊 fallback。

模型、时钟、ID、Repository、工具、Policy 和外部服务提供方必须通过 Port 注入；测试不得 monkey patch 生产规则来构造通过结果。

命名须表达业务角色和生命周期。除非边界明确，禁止使用 `data`、`info`、`manager`、`processor`、`handler` 等泛化名称。

## 6. 生产 Prompt 是版本化代码契约

本文拥有生产 Prompt 的通用语义契约。新增、迁移或实质修改的 Prompt 必须经[Prompt 模块规范](../../src/personal_agent/kernel/prompt_templates/AGENTS.md)统一注册、版本化和生产消费；只迁移位置时必须保持实际发送字节不变，不能声称修复语义缺陷。

新增或实质修改前，必须完成 [System Prompt 与 Context 设计审计](context-memory-retrieval.md#12-system-prompt-与-context-的设计及问题分析)，将动态物化和实际请求纳入分析；不能仅修改模板而遗漏运行系统、工具说明或历史反馈中仍生效的同类指引。

新增或实质修改的 Prompt 采用结果优先、最小充分表达，以清楚且不重叠的分区说明：

| 分区 | 必须表达的内容 |
| --- | --- |
| 任务目标 | 本轮语义决定或最终产物；先说明用户或下游消费者需要什么 |
| 必要 Context | 每类输入的权威来源、作用域、可信边界与清楚分隔；外部内容是数据而非指令 |
| 成功标准 | 动态投影当前用户要求、领域 `required result contract` 或工作清单中的用户可见结果，逐项可判断 |
| 硬约束 | 禁止编造、越权、扩大范围或覆盖确定性事实 |
| 输出形式 | typed schema、字段语义、字段间一致性及只允许返回的内容 |

Structured Outputs、`json_schema`、字段和枚举只约束形状。结果 Prompt 必须指出下游实际消费的完整产物字段；标题、提纲、占位符、写作意图、状态自述或主题复述不能替代该产物，除非用户请求的就是这些形式。判别 Prompt 同样须说明被评对象、逐项判据与相邻边界，不能把词面提及当成语义满足。

中文必须承担任务逻辑、Context 边界、成功标准、决策规则、约束、示例、失败处理和停止条件。英文仅保留翻译会失真的技术术语、Provider 或协议字面量、代码标识、typed 字段或枚举及 URL；不得用整段英文规避中文语义问题。明确的英文或多语言产品契约须独立版本化、独立评测，保留中文主 Prompt 的独立 target。

复杂智能体 Prompt 还须明确可见工具与权限、失败处理、重试上限和停止条件。只暴露当前可用的最小工具面，不能假装代码中不存在的能力。权限、执行事实、唯一推导、状态迁移和预算强制终止由确定性责任主体拥有；Prompt 不能替代。工具、查询、推理顺序或实现路径只有本身属于产品契约、安全协议或事务不变量时才能固定。

分类、路由和准入 Prompt 先给出互斥且有优先级的决策规则；出现实测歧义时，必须给出来自该失败类别的相邻正反例，并在返回前检查分类、理由和下一阶段一致。示例须贴近真实输入分布、覆盖相邻边界、保持输入输出结构一致；只能泛化失败类别，不能复制某条 E2E 的专有名词、答案、URL、标题或措辞，也不能每个反例追加一条例外。

每条指令只陈述一次。出现歧义先重组既有规则，不在扁平长段落末尾追加补丁。没有证据表明示例优于清楚规则时，优先使用短目标、动态成功标准与返回前自检；Prompt 增长须报告输入成本，并以代表性评测证明必要。

Prompt 变更按行为影响执行真实模型 Golden Set 或 Offline Eval，以及适用的真实 target E2E。比较固定 Prompt、Provider、模型、输入、schema、预算和重复次数，声明的候选变量除外；不得改写评测期望、只挑成功重跑或解析反馈文本制造稳定性。

静态检查及离线输入回放验证注册、输入分隔、typed 输出和代码侧不变量；真实模型评测验证语义边界；Product E2E 只验收用户结果，不固定措辞、工具路径或中间分类。模块内版本字段与具体检查遵守 Prompt 模块规范。

## 7. 编码智能体行为

实现前的变更说明、用户改动保护和完成声明遵守根规范；设计步骤与遇阻复核执行[EVD 流程](change-evidence.md#7-强制开发与设计流程)，E2E 失败执行[QLT 阻塞处理](quality-security.md#2-e2e-阻塞按目标阶段和单变量处理)。

无法确认事实责任主体、授权边界或外部契约时，明确阻塞原因并停止相关实现，不得猜测或用新增降级路径掩盖缺口。
