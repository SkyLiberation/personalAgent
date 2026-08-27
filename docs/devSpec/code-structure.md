# 代码组织与实现约束细则（COD）

> 本细则在任务涉及类或模块拆分、内部类型、payload、依赖注入、LangGraph、Router、Planner、Workflow、错误分类、命名，或编码智能体的实现行为时生效。

## 1. 不变量必须有唯一归属

结构存在的意义是让不变量可定位。**每条结构性不变量只能有一个命名 owner，破坏它必须由类型检查或某条确定性断言机械失败。** 靠字符串键、散落条件分支或注释维持的不变量视为未实现；重命名字段或更换服务提供方后，它会静默消失而不产生失败信号。

提交前必须能说明三件事：承载不变量的类型或模块名、破坏它的最小改动，以及因此变红的类型错误或断言。只有依赖模型运行方差才偶发触发的门禁不算被覆盖。

概念也不得只以类型存在。理念映射到代码指的是不变量有归属，不是每个名词各得一个对象。

设计模式只用于隔离已经发生或由近期业务 E2E 明确要求的变化，并受复杂度准入和外部参考分级约束。Ports and Adapters、State Machine、Command、Repository、Saga、Decorator、ACL 和 Registry 均按需使用，不是默认目录模板。

禁止：

- 为每个类创建 Interface、Factory 或 Manager，或用模式掩盖职责不清；
- 让 Strategy 或 Router 承担开放语义，或让 Adapter 或 Converter 维护镜像事实；
- 为未来可能性创建通用 Task、Event、Workflow、Planner、Projection 或兼容层；
- 新增 Model、契约或分层在生产路径零构造点或零读取点。该结构是空转，必须删除或降为可选投影。

## 2. 类型边界与 payload 所有权

无 schema 的 `dict[str, Any]`、raw JSON 和裸字符串只允许承载**边界另一侧拥有的内容**，例如外部工具、服务提供方、MCP endpoint 或用户输入。判据是写入者与读取者，不是字段看起来是否规整。

- 由本层写入又由本层读取的字段必须是 typed 字段。它承载内部不变量而非外部契约，禁止穿 dict 传递。
- 外部拥有的 payload 在读取处必须经 typed 校验。校验失败按“该事实不存在”处理；禁止兜底填充、默认成功、字符串包含或相似度判断。
- identity、scope、digest 和资源引用跨层一律 typed。

自写自读却经由 dict 的字段是典型缺陷：键名漂移不产生类型错误，被它守护的门禁会静默失效，类型检查与测试都不会变红。

## 3. 模块职责、规模与生产可达性

一个模块的职责必须能用一句不含“以及”的话说清。说不清时，先检查它是否同时拥有多个 Application Capability 的准入、结果契约或展示投影；这是 God Service 的判据。文件行数、类长度、圈复杂度和类数量只作为评审触发器，禁止按行数机械拆成更多 Manager 或 Helper。拆分必须形成更清晰的 owner 与依赖方向，并使净理解成本下降。

- 一个 Service 只拥有一个 Application Capability 的 Admission、结果契约与展示投影。多个 capability 共用入口时，入口只做语义路由、Context 组装、预算与终止判据；各 capability 的准入与投影归各自 owner。
- 抽出的准入模块必须可被独立 contract test 覆盖，且不反向依赖编排。
- 新增或显著增长的文件或类必须报告职责、生产调用方和拆分或不拆分理由。类数量增长必须与同步删除量及新边界对应，禁止以“小类更多就是解耦”为理由。
- 每个 production class、字段、Repository 方法、Projection 和 Adapter 必须从正式入口可达，并有生产构造点及调用者或消费者。持久化事实和 Projection 还必须有写入者与读取者；注入式 Adapter 或 Service 必须在 Composition Root 装配。仅被测试、迁移脚本或文档引用的结构不是已落地能力，除非它本身就是明确保留期的测试或迁移设施。

## 4. LangGraph、Router、Planner 与 Workflow

- Graph 表达编排和迁移，不拥有领域事实；
- Node 只提取输入、调用 Use Case、写回结果，不复制业务规则；
- GraphState 仅存 typed 运行必需状态，大对象使用 `ArtifactRef`；
- checkpoint 恢复不得重复模型调用或副作用；
- Router 或 Agent 输出 Goal、Intent 或 Application Capability Proposal，不选择 Repository、Provider、内部 Workflow 或 Project 模式，也不输出执行完成事实；
- Workflow 不是框架层、用户入口或 capability 类型，只是具体 Application Capability 内对固定业务不变量的编排；
- 新增 Workflow 必须同时具有固定业务不变量、多阶段执行事实、真实审批、恢复、审计、重试或补偿消费者，以及已失败 baseline；否则使用 Service 或 Application Pipeline；
- 固定依赖由契约或具体 Workflow 定义；只有 Observation 会改变未知依赖时才使用 Planner；
- Planner 不负责授权、执行或完成判定；
- Plan 只有被生产代码消费依据、依赖、进度、预算或完成义务时才能成为强制契约。审阅前仅可执行 Policy 投影为 planning-safe 的低风险读取；planning-safe 不等于严格 read-only，任何其他执行都会关闭新 Plan 的审阅迁移；
- Project 是拥有动态 durable business facts 的 Product Aggregate，不得作为通用 Workflow、路由分支标签或所有长任务的容器；
- Workflow 内固定低风险步骤优先 Service 化；模型动态选择或需要统一执行网关治理的执行资源才 Tool 化。

## 5. 错误、注入与命名

错误至少区分 Validation、Semantic Rejection、Authorization Denied、Capability Missing、Execution Failure、Transient Failure、Verification Failure、Completion Failure 和 Invariant Violation。禁止捕获异常后返回空结果、默认成功或模糊 fallback。

模型、时钟、ID、Repository、工具、Policy 和外部服务提供方必须通过 Port 注入。测试不得 monkey patch 生产规则来构造通过结果。

命名必须表达业务角色和生命周期。除非边界明确，禁止使用 `data`、`info`、`manager`、`processor`、`handler` 等泛化名称。

## 6. 编码智能体行为

开始实现前必须输出变更类型、目标、所有权、影响边界、产品 baseline、消融、真实 target 与指标方案，或重构工程基线；同时说明生产可达性、文档影响和计划删除内容。

禁止：

- 因不确定新增 fallback，或为兼容保留新旧双轨；
- 未搜索调用方就修改公共模型；
- 用 raw dict 绕过类型边界；
- 新增抽象却不说明变化来源和生产消费者，或新增结构没有正式入口可达链、生产构造或装配点与调用者；
- 让自写自读的内部字段穿 dict 传递，使结构性不变量失去机械判据；
- 把 Model、DTO、Interface、Fake、测试或未装配 Adapter 的横向半成品描述为能力落地，或未接真实环境就宣称可上线；
- 引用外部实践却不给等级和可复核坐标，或未核对源码或规范正文就断言业界做法；
- 未运行测试就声称完成。

当同一阻塞经一次定位和一次有界修正后仍复现，或出现 Plan 或补丁分支增长、同一事实多个 owner、跨层 fallback、指标无改善时，必须停止继续追加局部修补。先保存失败证据、当前代码身份和未验证假设，再按外部参考规则核对至少两个独立 A 级实现，重新判断根因、owner、架构边界、最小纵向切片和验证顺序。随后在权威设计文档中只保留一个活动方案，合并或撤回失效分支并删除过期描述。

外部参考只能帮助调整实现方式，不能替代本工程 baseline 或证明必须新增机制。无法确认事实 owner、授权边界或外部契约时，应明确阻塞原因并停止相关实现，不得猜测。
