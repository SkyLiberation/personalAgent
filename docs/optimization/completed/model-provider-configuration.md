# 配置驱动的模型 Provider 适配

`MODEL-PROVIDER-CONFIGURATION-001`；2026-10-26；源码基线 `5e0963e`。本轮配置封装与既定离线验收已完成。下文的集中 profile 是该轮实现身份，后续由[独立策略重构](model-provider-extensibility.md)替代，原证据不改写。当前架构由[横切机制](../../architecture/cross-cutting.md#2-模型调用的实际组合)拥有，配置契约由[环境说明](../../env.md#provider-选择与参数绑定)拥有。

## 问题与结论

主 Adapter 按模型前缀和域名选择参数，Graphiti 重复另一组判断，LangExtract 与图片描述另有参数路径。配置还把同一份附加参数无条件传给可独立覆盖 endpoint/model 的消费者，导致参数规则重复及配置绑定错配。

现已集中到无 I/O 的 `ModelProviderProfile`，四个现有生成适配入口复用。显式 provider 与官方域名冲突时拒绝；未声明时识别已知官方 hostname，代理域名可明确指定 provider。同一实际 provider/endpoint/model 才继承默认参数，未设置、显式 `{}` 与非法 JSON 分别表示继承、清空和拒绝。图片模型及 Client 的模型覆写不自动继承另一模型的参数。

## 采用方案与责任

`kernel/model_provider.py` 拥有 typed provider identity、外部参数校验和 SDK 字段投影；实际 SDK Client、deadline、流式聚合及原始响应仍归原 Adapter。现行 memory/application 不允许反向导入 infra，因此共享投影作为现有配置边界的技术协作者，不新增包依赖、Registry 或 middleware 容器。

MiniMax/MiMo 使用 `max_completion_tokens`，DeepSeek 使用 `max_tokens`，额度数值与省略语义保持。thinking、effort 和采样支持在该边界分别处理；DeepSeek `top_p` 保留，`reasoning_effort=none` 按关闭思考处理，其与显式 thinking 冲突时拒绝。MiMo 原工具流式及 wire `auto` 规则、原 required 本地校验和有界修复保持。配置中的 max 可投影到 SDK，不扩大原 Port/Journal 请求类型。JSON 输出 Adapter 不自动切换协议，原始历史继续服从现有 host/model 绑定，不提供任务中途热切换。

### 外部依据与取舍

2026-10-26 核对两个独立 A 级开源实现的固定源码：

- Pydantic AI `715651ef7fd3994395e85070ba3d6096c5b211c9`：[Provider profile](https://github.com/pydantic/pydantic-ai/blob/715651ef7fd3994395e85070ba3d6096c5b211c9/pydantic_ai_slim/pydantic_ai/providers/deepseek.py#L46) → `Model.profile` → [OpenAIChatModel._completions_create](https://github.com/pydantic/pydantic-ai/blob/715651ef7fd3994395e85070ba3d6096c5b211c9/pydantic_ai_slim/pydantic_ai/models/openai.py#L1592) → SDK。
- LiteLLM `dddbaa803d6e9fcc862ea7a5412f771cb1ae040e`：[公共调用选择 provider config](https://github.com/BerriAI/litellm/blob/dddbaa803d6e9fcc862ea7a5412f771cb1ae040e/litellm/llms/openai/openai.py#L747) → `transform_request` → 公共 SDK；[MiniMax config](https://github.com/BerriAI/litellm/blob/dddbaa803d6e9fcc862ea7a5412f771cb1ae040e/litellm/llms/minimax/chat/transformation.py#L14) 与 DeepSeek config 隔离协议差异。

采用 profile 与公共协议实现组合，保留本工程原始消息、required 本地验收及治理链，不引入完整外部模型框架、跨 provider fallback 或 reasoning 占位补造。协议核对：[MiniMax](https://platform.minimax.cn/docs/api-reference/text-chat-openai)、[MiMo](https://mimo.mi.com/docs/zh-CN/api/chat/openai-api)、[DeepSeek 详细接口](https://api-docs.deepseek.com/api/create-chat-completion/)与[思考参数](https://api-docs.deepseek.com/guides/thinking_mode/)。

## 接入状态与证据

生产消费者为 `OpenAIModelClient`、`GraphitiOpenAIClient`、LangExtract 既有 SDK 子类及 `ArtifactService._describe_image`。各自 SDK 生命周期与业务解析留在原处；原治理、观测、计量、重试、容量及 before-send 准入保持。无生产消费者的旧 `kernel/llm_trace.py` 不计第五个生成入口，Graphiti 既有 `model_size` 行为也未在本轮扩展。

设计先于实现，归档见[实施规格](../../../.tmp/model-provider-configuration-20261026/spec-implemented.md)。两个真实完整来源来自原 MiniMax 长任务与摘要阶段；请求/响应路径及 SHA-256 由[来源清单](../../../.tmp/model-provider-configuration-20261026/sources.json)绑定。基线源码、候选源码校验和、patch、SDK 实发字节和原响应投影均保留于[回放归档](../../../.tmp/model-provider-configuration-20261026/replay-v3/report.json)。命令由[运行入口](../../evals/04-running-and-release.md#provider-配置与参数封装回放)拥有。

| 预声明范围 | 实际结果 |
| --- | --- |
| 两个完整真实主链阶段 | 2/2；HTTP 正文分别 307,691 与 60,421 字节，基线/候选逐字节相同，响应投影相同 |
| Graphiti、LangExtract、图片默认/独立模型、DeepSeek top_p/none 的配置 SDK 边界 | 6/6；等额 token 字段、忽略参数省略与独立模型默认隔离符合声明。图片使用代表性 1×1 PNG，仅验配置与 SDK 出站 |
| 配置、非法参数及 Journal 往返反事实 | 15/15；三家选择、独立绑定、显式空对象、max 默认、冲突与受管字段拒绝成立 |
| 成本与证据资格 | 总计 23/23；只用真实 SDK 与本机 HTTP，付费请求 0，无工具执行，不计产品 E2E |
| 工程与文档 | 包依赖仍为 14 包/43 边；分层、导入、诊断脚本 lint、文档及 diff 检查通过；最终命令及范围见评测登记 |

生产代码新增 248 行、删除 92 行，净增 156 行；新增的是唯一 profile、外部配置校验与绑定规则，删除各活跃 Adapter 的重复判断。没有复制三套 SDK Client 或增加调用层，验证脚本独立于生产装配。新增规则承担本次明确的配置隔离与拒绝契约，不主张通过减少总行数获得收益。

本轮没有出现非等价主链输入，未触发设计中的付费升级条件。三家全部真实接入、图片语义、取消/异常的运行时可靠性及完整产品成功率不由上述检查证明；已有真实结果保留原身份，不并入本轮发布分子。

## 失败尝试与审查处理

未发生付费候选失败。独立审查发现新增的 Port max 类型未同步 Journal；撤回该不必要扩展，配置 max 继续通过外部参数投影，并验证原 Journal 往返。另确认 DeepSeek 的 top_p 和 none 属于合法协议，修正过度过滤/拒绝后通过 SDK 出站检查。来源 manifest 同时消费请求与响应校验和；没有通过放宽原主链字节判据获得通过。

## 重新打开条件

后续真实 E2E 或其完整实际阶段复现 provider 参数拒绝、不同绑定错误继承或主链字段漂移时，封存输入、实际配置和最早责任边界，按原问题重新打开。新增 provider、模型模式或外部协议变化另按实际影响核对其契约，不由本轮样本外推。
