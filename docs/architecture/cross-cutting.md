# 横切机制与 AOP

横切关注点是多个调用边界共同需要的技术职责，例如追踪、用量、限流和协议内重试。本工程优先通过 typed Port 包装器、中间件和上下文管理器显式组合这些职责，使业务代码围绕目标、事实与合法迁移组织。

本文拥有现有组合、装配与证据；通用机制选择由[编码质量 skill](../../.agents/skills/write-quality-code/SKILL.md#2-隔离切面保持业务主流程清楚)拥有，强制边界由 [COD](../devSpec/code-structure.md#51-横切关注点与显式组合)拥有。当前组合复用既有包装器；新机制仍须满足 [ARC 框架准入](../devSpec/architecture-ownership.md#4-framework-capability-准入与边界)和 [EVD 复杂度准入](../devSpec/change-evidence.md#5-复杂度说明complexity-justification)。

## 1. 现有实现与责任

| 关注点 | 当前实现与装配 | 责任边界 |
| --- | --- | --- |
| HTTP 认证与入口限流 | [AuthMiddleware](../../src/personal_agent/adapters/web/auth.py)，由 Web 应用装配 | 认证身份与传输限流；不替代业务资源和工具授权 |
| 模型调用准入 | [GovernedModelClient](../../src/personal_agent/capabilities/model_resolution.py)，由模型工厂装配 | 根据当前请求与 Context 引用建立单次调用 grant；语义结果仍由调用方消费和核验 |
| 模型 Provider 参数 | [策略契约](../../src/personal_agent/kernel/model_provider.py)及[配置工厂与独立实现](../../src/personal_agent/infra/model_providers/)，在构造时选择并注入 | 公共编码与厂商规则分别拥有；不持有 SDK Client，不接管业务、重试或恢复 |
| 模型重试 | [RetryingStructuredModelClient](../../src/personal_agent/infra/structured_model.py) | typed 调用边界的暂时失败重试，汇总已知耗用；SDK transport 重试由 Adapter 禁用 |
| 模型计量与观测 | 同文件的 `UsageRecordingStructuredModelClient`、`ObservedStructuredModelClient` | 记录实际响应、耗用、失败和追踪；不决定业务成功 |
| 模型 HTTP 诊断 | [model_transport.py](../../src/personal_agent/infra/model_transport.py)，由 `OpenAIModelClient._client()` 为 SDK 默认 HTTPX Client 显式装配 hook | 请求内 recorder 记录响应头、原始正文块进度和实际连接对端；typed 快照随原异常传至 retry／Conversation 日志，不改变模型载荷、传输策略或用量 |
| 请求内用量收集 | [collect_llm_usage](../../src/personal_agent/kernel/llm_telemetry.py) | `ContextVar` 与上下文管理器限定收集范围，退出时恢复；不作为身份或授权来源 |
| 工具治理 | [ToolExecutor](../../src/personal_agent/governance/gateway.py) | 显式处理 grant、Policy、限流、幂等、执行和审计，不通过方法名匹配插入 |
| 策略观测归属 | [PolicyDecisionRecorder](../../src/personal_agent/kernel/observability.py) 与 [PolicyDecisionEvent](../../src/personal_agent/kernel/contracts/policy.py)，由 `AgentRuntime` 注入三个调用点 | Runtime 实例绑定本实例存储；事件不决定授权，可选 sink 失败语义保持，见 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md) |
| 业务确认与迁移 | [KnowledgeLifecycleService](../../src/personal_agent/application/knowledge_lifecycle/service.py) 等业务用例 | 业务 owner 拥有 Command、确认绑定、合法迁移和恢复，通用切面不接管这些判断 |

这些实现共享横切分离的设计思路，尚未形成统一 AOP 引擎。工具网关包含其协议内的执行策略，不能与模型重试合并成自动重跑任意操作的全局切面。

## 2. 模型调用的实际组合

`AgentService` 从 typed `Settings.prompt_language` 取得不可变 `PromptCatalog`，显式装配到 Runtime、Graphiti、Conversation、工具及模型工厂。默认中文，英文资源由 `kernel.prompts.create_prompt_catalog` 注册；Application 拥有业务指令，Adapter 拥有结构化包装和修复指令。Schema 说明／标题在 Adapter 发出前投影，原校验模型、字段和历史事实不变。语言与 Provider 分别配置，不通过全局变量或模型品牌选择语言。资源、版本及拒绝规则由 [Prompt 模块规范](../../src/personal_agent/kernel/prompt_templates/AGENTS.md)拥有。

工程自有长指令以 Markdown 标题和原段落组织，短反馈可直接为正文；主循环执行输入通过同一 Catalog 的具名包装呈现，内部载荷仍为原 typed facts 的 JSON。正文格式不改变工具协议、来源材料或历史；第三方独立提示继续由其原契约拥有。迁移及实际验证范围见[表达统一方案](../optimization/completed/prompt-markdown-presentation.md)。

工程生成的读取、搜索、截断、工具与拒绝反馈同样由对应 owner 消费实例 Catalog；原始用户／来源／历史正文和捕获输出不参与递归翻译。参数、冻结模型和模型输出的 Pydantic 校验通过既有 `ValidationInfo.context` 接收同一 typed Catalog，只选择原拒绝条件的文字，不改字段、Schema、分类或恢复次数。`CaptureService` 可接收 Catalog，未提供时按其 Settings 构造，并注入自己创建的默认 URL provider；Runtime 不事后修改外部依赖的语言状态。

[`build_structured_model_client()`](../../src/personal_agent/infra/structured_model.py) 在结构化路径选择 Adapter；`build_chat_model_client()` 为文本与原生工具调用构造 Adapter。两者的实际调用方向为：

```text
Application 调用 StructuredModelClient.generate(request)
  -> GovernedModelClient：单次模型调用准入
  -> ObservedStructuredModelClient：可选追踪
  -> UsageRecordingStructuredModelClient：记录聚合耗用
  -> RetryingStructuredModelClient：有界暂时失败重试
  -> 配置选定的 Adapter：SDK 调用、协议解析和 typed 输出
```

返回与异常沿相反方向传播。计量位于重试外层，消费重试器汇总的响应信息；观测开关决定追踪包装是否装配。输出协议修复与暂时失败重试是不同边界，额度由现行请求和配置约束，不能叠加为无界重试。

Conversation 的普通核验工作流由 Runtime 注入按受信 `ExecutionScope` 绑定的模型调用方法；各次分段／整体核验分别执行当前 run 准入及 Journal 消费提交。工具同步执行，模型单请求超时及运行截止拥有停止责任，避免外层线程超时遗留继续消费的核验。该入口仍调用上述模型 Port 组合，任务额度由 Conversation／Journal 拥有，不由遥测收集器授权或计费。

模型调用统一消费完整的 `StructuredModelResponse`。Adapter 的 `_create_structured_completion()` 可用 SDK 流式 transport 取得最终完整响应；MiMo 官方 API／中国区 Token Plan 的原生工具调用也使用 SDK 流式合并及完整用量，wire 选择为服务方支持的 `auto`，原请求的 required 校验与有界修复保持。工具流仅关闭 SDK 本地 strict 自动参数解析，完整参数交原解码器，部分增量不进入执行；其上下文关闭、deadline、重试及耗用继续经过上述组合。协议依据及验证边界见[传输规格](../optimization/model-provider-transport.md#2026-10-23-mimo-工具流式接入规格)。

MiMo策略在最终出站工具参数中，对缺少显式type且可证明为对象的直接参数采用有限本地引用展开；仅支持无环、纯defs引用且无作用域变化的闭包，其他Schema保持原样。复用既有LangChain helper，保留definitions、联合约束和canonical本地校验，不再strictify，也不接纳字符串参数。其他Provider不消费该适配；实际容量仍按最终wire计算。采用依据及局部验收见[引用投影方案](../optimization/completed/tool-schema-reference-projection.md)。

HTTPX 观测状态附着在单次 Request 的 extensions，随 deadline 工作线程中的实际请求建立，不从调用线程的 `ContextVar` 或共享“最后一次请求”取值。response hook 在正文读取前记录状态和白名单头；透明正文包装计数并转发原字节及关闭，失败快照保持原状态码与独立的 SDK 失败分类。`llm.http.headers`、`llm.http.failed`、`llm.http.body_closed` 通过请求内 `attempt_id` 关联；首末时间指 HTTPX 正文块交付，不能用来推算 tokens 或证明 SDK／任务完成。详细字段由[Runtime](../topics/runtime.md)拥有。

原生工具续接通过原 Model Port 的 typed envelope／exchange 传递完整 assistant 字段及按原 ID 配对的 tool 结果。Adapter 绑定实际请求端点与请求模型，保留服务方回执的模型名及思考字段；非法原生消息不能执行，但完整回执的费用仍通过原 typed failure 交接。Conversation Journal 保存不可变决策响应，业务结果、拒绝及控制接纳仍由各自 owner 产生；派生消息不成为新执行事实。恢复与完整组压缩见 [ADR 0042](../adr/0042-native-model-tool-continuation.md)，局部验证不替代参数或用户结果验收。

主循环允许完整可见assistant正文形成候选，工具与正文并存时优先处理工具；回答模块和原Completion仍决定能否交付。内部结果由typed Port声明请求级策略：意图判断的prompted_json在Infra映射为无工具／无API格式的文本请求，直接严格解析原content；其他native_tool的parameters仍用公共转换从原Pydantic类导出，canonical类型不变，修复声明由原逻辑request显式保留，不从已替换的chat_request猜承载，JSON消费者不切到另一传输。流式角色按结构元数据聚合，不能和正文一样累加；其sticky协议失败事实随原ModelResponseRecord／Journal保存，完整响应先记录再校验，恢复读取同一事实。SDK内部载体与观察器不另建响应库或收费账本，详见[统一契约](../optimization/to_verify/conversation-loop-schema.md#13-流式结构角色按元数据聚合)。

Loop 已将逐响应记录和续接接入同一 Port：response_sink 在 typed 解码前交原 Journal 保存一次原件；before_send 只对新增物理发送执行原预算准入；continuation 先解码已付费原件。它们是具名记录／准入接口，不是通用业务 hook；包装器透明传递，不保存进程全局当前 run。主循环修复由 Application 唯一负责，内层原有限输出修复仍按请求计量；中性错误由 REST／SSE 统一安全投影。实现与未验收边界见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。

正式 [SSE 入口](../../src/personal_agent/adapters/web/routes/entry_stream.py)调用 `AgentService.converse()`，将 Conversation 已验收答案分块返回，协议见 [API](../api.md)。子 Agent 的事件流由 [AgentGateway](../../src/personal_agent/agents/gateway.py)承接。旧模型 token 流 Port 与包装器没有当前消费者，已退役，删除及行为保持证据见[完成记录](../optimization/completed/model-streaming-retirement.md)。

生成式 Provider 在构造时由配置与[唯一策略工厂](../../src/personal_agent/infra/model_providers/__init__.py)选定，SDK 请求过程只调用注入的 `ModelProviderPolicy.prepare_chat_parameters()`。未显式声明时识别已知官方 hostname；自定义服务可以使用注册 ID。未注册 ID 在装配时明确拒绝，不能静默降为通用服务。配置加载器只向相同实际 provider/endpoint/model 的消费者继承 canonical 附加参数；独立绑定、显式空对象和非法 JSON 仍分别表示独立配置、清空与拒绝。不同图片模型及 `model_override` 不自动继承主模型参数，环境契约由[环境说明](../env.md#provider-选择与参数绑定)拥有。

参数适配按以下职责分开，原 SDK、解析、重试、容量和预算准入位置保持：

| 职责 | 唯一实现与直接协作者 |
| --- | --- |
| 共享 typed 契约 | [`kernel/model_provider.py`](../../src/personal_agent/kernel/model_provider.py)：provider ID、官方端点识别、`ChatModelCapabilities` 和 `ModelProviderPolicy` Protocol |
| 公共编码 | [`OpenAICompatiblePolicy`](../../src/personal_agent/infra/model_providers/openai_compatible.py)：合并默认值、校验受管字段/effort、按能力投影 token 和采样字段；`ChatParameters` 仅持有单次请求的外部 SDK 载荷 |
| 服务方规则 | [`MiniMaxPolicy`](../../src/personal_agent/infra/model_providers/minimax.py)、[`MiMoPolicy`](../../src/personal_agent/infra/model_providers/mimo.py)、[`DeepSeekPolicy`](../../src/personal_agent/infra/model_providers/deepseek.py)：分别处理实际模型的 thinking/effort 和工具传输差异 |
| 选择与装配 | Infra 的不可变默认注册表和 `build_provider_policy()`；主模型工厂可注入策略，直接构造 Adapter 时也只选择一次。AgentService 向 GraphitiStore 注入，Runtime 向 ArtifactService 注入；LangExtract 实验构造链显式传入策略 |

公共编码器先建立请求内载荷，调用策略 `configure()` 取得能力，再投影 token/采样字段，调用 `prepare_tools()` 处理传输约束，最后写回 effort 和附加参数。SDK 使用所得字典发送；策略没有模型调用、历史、重试和计量状态。`ModelProviderProfile` 集中品牌分支已删除，memory/application 只依赖 kernel Protocol，不反向导入 infra。

新增兼容服务时，在 `infra/model_providers/` 增加实现，并在同目录注册表增加 ID→工厂；配置显式指定该 ID，已有消费者便会从同一工厂取得策略。只有静态能力差异时，可直接注册 `lambda: OpenAICompatiblePolicy(ChatModelCapabilities("max_completion_tokens", ("temperature",)))`。有动态协议差异时继承公共策略，覆写 `configure()` 或 `prepare_tools()`，公共 SDK 和已有策略无需修改。注册表也可作为工厂参数传入，不依赖进程全局可变注册或动态包扫描。

该选择属于外部协议适配；观测、重试等调用 middleware 仍沿用本节原有 Decorator 链。实际接入和离线证据由[策略重构记录](../optimization/completed/model-provider-extensibility.md)拥有，不外推三家全部业务路径的真实模型集成。旧 `kernel/llm_trace.py` 请求辅助没有生产消费者，不列作额外生成入口。

## 3. 选择最小隔离机制

按[编码质量 skill 的机制选择表](../../.agents/skills/write-quality-code/SKILL.md#2-隔离切面保持业务主流程清楚)选择最小隔离方式，并沿本页第 1、2 节核对现行实现与装配。

能力模块的可装配性与调用 middleware、生命周期 hook 是三个扩展维度：前者组织业务协作者，中者包装明确调用，后者通知事实消费者。当前已有模型包装器和工具注册，尚未实现统一能力插件协议或通用 HookBus。目标装配、切入点、顺序及失败语义由[主循环扩展设计](../optimization/to_verify/conversation-loop-boundaries.md#35-扩展架构能力模块middleware-与-hook)拥有；它是候选，不改变本页现行组合或 COD 强制边界。

## 4. 横切实现的强制边界

横切实现的六项通用强制边界由 [COD](../devSpec/code-structure.md#51-横切关注点与显式组合)拥有；本节保留现行观测装配与证据限制。

当前 [`PolicyDecisionRecorder`](../../src/personal_agent/kernel/observability.py) 由 `AgentRuntime` 按实例构造，并经 ToolExecutor 转交 ToolGateway，以及直接注入 MemoryFacade、ConversationService；不再注册进程全局 sink。内部事件 typed 且 immutable，保留原字段。可选 sink 仍捕获持久化异常，不能把它当作必需审计原子提交的保证；实施与正式验收见 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)。

## 5. 变更时如何验收

变更说明、行为保持对照、验证升级和退出要求统一执行 [COD 横切约束](../devSpec/code-structure.md#51-横切关注点与显式组合)，证据类别由 [EVD](../devSpec/change-evidence.md#12-按实际影响选择证据)判断。通过后同步本页的现有实现、装配与顺序。

## 6. 外部机制依据

以下为 A 级官方文档，复核日期为 2026-10-16；动态页面不绑定本工程依赖版本，外部机制不能证明本工程效果。

| 来源 | 可确认机制 | 本工程取舍 |
| --- | --- | --- |
| [Spring Framework：AOP Concepts](https://docs.spring.io/spring-framework/reference/core/aop/introduction-defn.html) | 横切关注点、切入点、advice；建议选用满足目标的最小能力 advice | 借鉴职责隔离与最小拦截，使用现有 typed Port 显式组合；不引入 Java 代理和自动织入 |
| [Spring Framework：Advice Ordering](https://docs.spring.io/spring-framework/reference/core/aop/ataspectj/advice.html#advice-ordering) | 多个 advice 的执行次序需要明确约束 | 本工程顺序由工厂代码显式表达，不依赖隐含优先级 |
| [Python 3.11：contextvars](https://docs.python.org/3.11/library/contextvars.html) | 上下文局部变量、token 恢复及 `asyncio` 支持 | 解释现有用量收集；不据此推定任意跨线程传播或业务授权成立 |
