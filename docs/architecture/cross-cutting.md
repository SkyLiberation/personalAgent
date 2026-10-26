# 横切机制与 AOP

横切关注点是多个调用边界共同需要的技术职责，例如追踪、用量、限流和协议内重试。本工程优先通过 typed Port 包装器、中间件和上下文管理器显式组合这些职责，使业务代码围绕目标、事实与合法迁移组织。

本文拥有现有组合与横切设计约束，由 [COD](../devSpec/code-structure.md#51-横切关注点与显式组合)接入开发流程。当前组合复用既有包装器；新机制仍须满足 [ARC 框架准入](../devSpec/architecture-ownership.md#4-framework-capability-准入与边界)和 [EVD 复杂度准入](../devSpec/change-evidence.md#5-复杂度说明complexity-justification)。

## 1. 现有实现与责任

| 关注点 | 当前实现与装配 | 责任边界 |
| --- | --- | --- |
| HTTP 认证与入口限流 | [AuthMiddleware](../../src/personal_agent/adapters/web/auth.py)，由 Web 应用装配 | 认证身份与传输限流；不替代业务资源和工具授权 |
| 模型调用准入 | [GovernedModelClient](../../src/personal_agent/capabilities/model_resolution.py)，由模型工厂装配 | 根据当前请求与 Context 引用建立单次调用 grant；语义结果仍由调用方消费和核验 |
| 模型重试 | [RetryingStructuredModelClient](../../src/personal_agent/infra/structured_model.py) | typed 调用边界的暂时失败重试，汇总已知耗用；SDK transport 重试由 Adapter 禁用 |
| 模型计量与观测 | 同文件的 `UsageRecordingStructuredModelClient`、`ObservedStructuredModelClient` | 记录实际响应、耗用、失败和追踪；不决定业务成功 |
| 模型 HTTP 诊断 | [model_transport.py](../../src/personal_agent/infra/model_transport.py)，由 `OpenAIModelClient._client()` 为 SDK 默认 HTTPX Client 显式装配 hook | 请求内 recorder 记录响应头、原始正文块进度和实际连接对端；typed 快照随原异常传至 retry／Conversation 日志，不改变模型载荷、传输策略或用量 |
| 请求内用量收集 | [collect_llm_usage](../../src/personal_agent/kernel/llm_telemetry.py) | `ContextVar` 与上下文管理器限定收集范围，退出时恢复；不作为身份或授权来源 |
| 工具治理 | [ToolExecutor](../../src/personal_agent/governance/gateway.py) | 显式处理 grant、Policy、限流、幂等、执行和审计，不通过方法名匹配插入 |
| 策略观测归属 | [PolicyDecisionRecorder](../../src/personal_agent/kernel/observability.py) 与 [PolicyDecisionEvent](../../src/personal_agent/kernel/contracts/policy.py)，由 `AgentRuntime` 注入三个调用点 | Runtime 实例绑定本实例存储；事件不决定授权，可选 sink 失败语义保持，见 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md) |
| 业务确认与迁移 | [KnowledgeLifecycleService](../../src/personal_agent/application/knowledge_lifecycle/service.py) 等业务用例 | 业务 owner 拥有 Command、确认绑定、合法迁移和恢复，通用切面不接管这些判断 |

这些实现共享横切分离的设计思路，尚未形成统一 AOP 引擎。工具网关包含其协议内的执行策略，不能与模型重试合并成自动重跑任意操作的全局切面。

## 2. 模型调用的实际组合

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

HTTPX 观测状态附着在单次 Request 的 extensions，随 deadline 工作线程中的实际请求建立，不从调用线程的 `ContextVar` 或共享“最后一次请求”取值。response hook 在正文读取前记录状态和白名单头；透明正文包装计数并转发原字节及关闭，失败快照保持原状态码与独立的 SDK 失败分类。`llm.http.headers`、`llm.http.failed`、`llm.http.body_closed` 通过请求内 `attempt_id` 关联；首末时间指 HTTPX 正文块交付，不能用来推算 tokens 或证明 SDK／任务完成。详细字段由[Runtime](../topics/runtime.md)拥有。

原生工具续接通过原 Model Port 的 typed envelope／exchange 传递完整 assistant 字段及按原 ID 配对的 tool 结果。Adapter 绑定实际请求端点与请求模型，保留服务方回执的模型名及思考字段；非法原生消息不能执行，但完整回执的费用仍通过原 typed failure 交接。Conversation Journal 保存不可变决策响应，业务结果、拒绝及控制接纳仍由各自 owner 产生；派生消息不成为新执行事实。恢复与完整组压缩见 [ADR 0042](../adr/0042-native-model-tool-continuation.md)，局部验证不替代参数或用户结果验收。

主循环允许完整可见assistant正文形成候选，工具与正文并存时优先处理工具；回答模块和原Completion仍决定能否交付。内部结果由typed Port声明请求级策略：意图判断的prompted_json在Infra映射为无工具／无API格式的文本请求，直接严格解析原content；其他native_tool的parameters仍用公共转换从原Pydantic类导出，canonical类型不变，修复声明由原逻辑request显式保留，不从已替换的chat_request猜承载，JSON消费者不切到另一传输。流式角色按结构元数据聚合，不能和正文一样累加；其sticky协议失败事实随原ModelResponseRecord／Journal保存，完整响应先记录再校验，恢复读取同一事实。SDK内部载体与观察器不另建响应库或收费账本，详见[统一契约](../optimization/to_verify/conversation-loop-schema.md#13-流式结构角色按元数据聚合)。

Loop 已将逐响应记录和续接接入同一 Port：response_sink 在 typed 解码前交原 Journal 保存一次原件；before_send 只对新增物理发送执行原预算准入；continuation 先解码已付费原件。它们是具名记录／准入接口，不是通用业务 hook；包装器透明传递，不保存进程全局当前 run。主循环修复由 Application 唯一负责，内层原有限输出修复仍按请求计量；中性错误由 REST／SSE 统一安全投影。实现与未验收边界见 [ADR 0045](../adr/0045-native-intent-loop-and-recorded-model-output.md)。

正式 [SSE 入口](../../src/personal_agent/adapters/web/routes/entry_stream.py)调用 `AgentService.converse()`，将 Conversation 已验收答案分块返回，协议见 [API](../api.md)。子 Agent 的事件流由 [AgentGateway](../../src/personal_agent/agents/gateway.py)承接。旧模型 token 流 Port 与包装器没有当前消费者，已退役，删除及行为保持证据见[完成记录](../optimization/completed/model-streaming-retirement.md)。

生成式服务方附加参数由 `STRUCTURED_EXTRA_BODY` 唯一配置。配置加载器把同源参数投影到 `StructuredConfig`、`OpenAIConfig` 和 `LangExtractConfig`；Graphiti 工厂直接传递同一来源，现有图片附件描述消费 `OpenAIConfig.extra_body`。各 SDK Adapter 负责协议投影，应用层摘要不再自行关闭思考；调用方显式深度与输出额度仍由原 typed 请求拥有。LangExtract 包装沿 SDK 子类的参数构造点补入依赖白名单会过滤的扩展。当前 MiniMax 部署采用 `thinking.type=adaptive`、`reasoning_effort=medium`，详细契约和验证边界见[环境说明](../env.md#统一思考参数2026-10-23)。这不增加模型路由或新的横切服务。

## 3. 选择最小隔离机制

| 当前需要 | 优先方式 | 准入条件 |
| --- | --- | --- |
| 单个用例的确定性处理 | 内聚函数或显式顺序调用 | 有清楚输入输出，不为形式复用新增 Port |
| 可替换的模型、存储或外部执行依赖 | 现行 typed Port + Adapter | 信任或外部边界明确，在既有装配入口注入 |
| 同一 Port 的追踪、计量或既定重试 | 实现相同 Port 的 Decorator，承担调用 middleware 的语义 | 输入输出与失败契约明确，顺序可见；跨业务抽取满足 ARC 准入 |
| 传输入口通用处理 | Middleware | 只处理对应传输边界，各正式入口仍执行适用业务校验 |
| 资源与请求内观测范围 | Context Manager，必要时使用 `ContextVar` | 异常、取消和退出释放或恢复上下文；跨线程、任务传播须按实际调度核验 |
| 授权、幂等和受治理执行 | 现有 Policy / Admission / Gateway | 在实际执行与读取边界显式调用并检查，拒绝时零越权执行 |
| 业务原子写入 | Application 确定事务范围，由存储实现原子操作 | 不把外部副作用和多存储写入包装成虚假的单一数据库事务 |
| 读取成本需要缓存 | owner 声明的派生缓存 | 来源、失效、权限和失败语义按 [ARC 缓存规则](../devSpec/architecture-ownership.md#61-派生缓存与投影)验证 |

AOP 用于分离跨模块技术职责。Python 中优先选择可定位的显式组合，不通过扫描包、方法名通配、运行时替换或全局事件监听暗中改变生产调用链。业务状态迁移仍在其 owner 内；Strategy、Registry 或事件机制也须有真实变化、消费者和独立必要性，不能成套引入。

能力模块的可装配性与调用 middleware、生命周期 hook 是三个扩展维度：前者组织业务协作者，中者包装明确调用，后者通知事实消费者。当前已有模型包装器和工具注册，尚未实现统一能力插件协议或通用 HookBus。目标装配、切入点、顺序及失败语义由[主循环扩展设计](../optimization/to_verify/conversation-loop-boundaries.md#35-扩展架构能力模块middleware-与-hook)拥有；它是候选，不改变本页现行组合和强制边界。

## 4. 横切实现的强制边界

1. **切入点可定位**：设计写明被包装的 typed Port 或入口、真实消费者、装配工厂和调用顺序。调用方只依赖该契约，不从容器或全局可变对象反查业务服务；禁止 monkey patch 生产对象制造隐式依赖。
2. **业务结果不被偷换**：记录型包装器保持输入、输出、异常和取消语义。改变准入、重试、缓存或失败行为的机制按其实际影响验收，不能以“技术切面”免除产品和安全门禁；不得补 Proposal payload、改变 Goal 或伪造 Receipt。
3. **每个重试边界有一个 owner**：声明失败类别、幂等条件、次数、累计成本和停止条件。语义拒绝、权限拒绝和内部不变量破坏不由通用重试吞没；外部写入结果未知时按执行恢复协议处理，不能盲目重放。
4. **授权与完成保持显式**：认证、资源 Visibility、工具 Admission 和最终 Completion 分别执行各自契约。跨入口复用相同业务 owner；不得仅靠可跳过的装饰器、日志回调或模型 Prompt 保证关键不变量。
5. **区分旁路观测与必要证据**：可选遥测失败按其契约隔离，必需的授权、执行或恢复证据由对应协议保证。当前 [`PolicyDecisionRecorder`](../../src/personal_agent/kernel/observability.py) 由 `AgentRuntime` 按实例构造，并经 ToolExecutor 转交 ToolGateway，以及直接注入 MemoryFacade、ConversationService；不再注册进程全局 sink。内部事件 typed 且 immutable，保留原字段。可选 sink 仍捕获持久化异常，不能把它当作必需审计原子提交的保证；实施与正式验收见 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)。
6. **保留完整生命周期**：包装异步或流式调用时覆盖迭代、结束、异常和取消，保持关闭及资源释放责任。观测上下文不携带业务写权限；identity、scope、grant 和资源引用继续经 typed 参数传递。

## 5. 变更时如何验收

在唯一设计中声明职责、切入点、顺序、错误与副作用边界、删除的重复实现及更简单方案，按 [EVD](../devSpec/change-evidence.md#12-按实际影响选择证据)选择验证。

严格保持行为的包装器整理对照实际输入、输出、异常、装配和适用回放；模型请求、工具协议、授权、重试或恢复行为改变时升级对应真实验证。静态依赖通过仅证明包关系；真实消费者、拒绝路径和用户结果仍按各自契约验收。通过后同步本页的现有实现与顺序，撤回时删除包装器及其装配，不保留无人消费的框架入口。

## 6. 外部机制依据

以下为 A 级官方文档，复核日期为 2026-10-16；动态页面不绑定本工程依赖版本，外部机制不能证明本工程效果。

| 来源 | 可确认机制 | 本工程取舍 |
| --- | --- | --- |
| [Spring Framework：AOP Concepts](https://docs.spring.io/spring-framework/reference/core/aop/introduction-defn.html) | 横切关注点、切入点、advice；建议选用满足目标的最小能力 advice | 借鉴职责隔离与最小拦截，使用现有 typed Port 显式组合；不引入 Java 代理和自动织入 |
| [Spring Framework：Advice Ordering](https://docs.spring.io/spring-framework/reference/core/aop/ataspectj/advice.html#advice-ordering) | 多个 advice 的执行次序需要明确约束 | 本工程顺序由工厂代码显式表达，不依赖隐含优先级 |
| [Python 3.11：contextvars](https://docs.python.org/3.11/library/contextvars.html) | 上下文局部变量、token 恢复及 `asyncio` 支持 | 解释现有用量收集；不据此推定任意跨线程传播或业务授权成立 |
