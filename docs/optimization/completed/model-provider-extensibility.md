# 模型 Provider 策略的独立扩展

`MODEL-PROVIDER-EXTENSIBILITY-001`；2026-10-26；内部重构。三家参数规则已独立，既定行为保持与扩展验收通过。当前职责和接入方式由[架构组合](../../architecture/cross-cutting.md#2-模型调用的实际组合)拥有，配置由[环境说明](../../env.md#provider-选择与参数绑定)拥有。

## 问题与结论

此前[参数集中重构](model-provider-configuration.md)解决了重复判断和配置绑定问题，但 `ModelProviderProfile.project_chat_parameters()` 仍在一个函数内按品牌分支，封闭 Literal 也阻止新 ID 接入。四个 SDK 入口还分别解析 provider。该结构没有独立替换服务方规则的入口。

现已改成“配置选策略、公共编码器用能力数据、SDK 消费注入策略”。MiniMax、MiMo、DeepSeek 各有模块；新增服务可通过新实现及一处注册接入，公共请求器与已有策略保持。只有静态能力差异时复用公共策略及能力数据即可。

## 采用方案与责任

`kernel/model_provider.py` 只拥有开放但校验格式的 provider ID、既有官方端点识别、`ChatModelCapabilities` 和 `ModelProviderPolicy` Protocol。`infra/model_providers/` 拥有公共编码、三个策略及不可变默认注册表。未知 ID 在装配时拒绝，不静默降为通用服务。

公共编码器合并默认参数、校验受管字段和 effort、调用策略取得能力、投影输出 token/采样字段，再处理工具传输并写回外部参数。三家分别拥有 thinking/effort 与工具规则。策略按实际请求模型处理，默认值是否继承仍由原 endpoint/model 绑定规则负责；Port/Journal、消息、Schema、原始历史、预算、重试及 SDK 生命周期保持。

主模型工厂和直接 Adapter 构造都可显式注入策略；缺省时由唯一工厂在构造时选一次。AgentService 向 GraphitiStore 注入策略，Runtime 向 ArtifactService 注入；LangExtract 的实验构造链显式传入。memory/application 只依赖 kernel Protocol，保持原包依赖方向。旧集中 `ModelProviderProfile` 路径已删除，实际 source、eval 和两个脚本构造者已迁移。

### 2026-10-27 活动实验迁移复核

Context 实验预检发现 `kernel/model_provider.py` 被旧版文件覆盖，导入与当前消费者不符；现存字节先备份，再恢复已验证的 `replay-v2/provider-source.py`（SHA-256 `83c405a37626e2af1e786076235a60b402678e3311bf34fc651c983e98ab4092`），未新增兼容别名。LongDS Judge 与两个直用 LangExtract ModelConfig 的探针现已接入公共策略，活动批次显式准入新评分资格。513文件扫描、74符号导入及当前26/26回放通过；真实task2前三轮沿新接口交付并评分，语义仍有失败。修改边界、资格与执行结果由[验证记录](../to_verify/verify_results/longds-analysis.md#11-context-首批实施与接口迁移)拥有，原已完成证据保持原身份。

### 外部依据与取舍

2026-10-26 核对两个独立 A 级开源实现的固定源码及真实调用链：

- Pydantic AI `715651ef7fd3994395e85070ba3d6096c5b211c9`：[DeepSeekProvider.model_profile](https://github.com/pydantic/pydantic-ai/blob/715651ef7fd3994395e85070ba3d6096c5b211c9/pydantic_ai_slim/pydantic_ai/providers/deepseek.py#L47) → `Model.profile` → [公共 OpenAI 请求器](https://github.com/pydantic/pydantic-ai/blob/715651ef7fd3994395e85070ba3d6096c5b211c9/pydantic_ai_slim/pydantic_ai/models/openai.py#L1592)。采用能力数据与 provider 对象注入。
- Vercel AI SDK `20c4031d1fc59aab54b67c16679e3981374690ab`：[显式 registry](https://github.com/vercel/ai/blob/20c4031d1fc59aab54b67c16679e3981374690ab/packages/ai/src/registry/provider-registry.ts#L181) → `provider.languageModel()` → 公共兼容模型；[Vertex MaaS 工厂](https://github.com/vercel/ai/blob/20c4031d1fc59aab54b67c16679e3981374690ab/packages/google-vertex/src/maas/google-vertex-maas-provider.ts#L123)实际注入请求转换。采用显式选择和转换注入。

保留本工程 OpenAI SDK、同步/异步所有者及治理链，没有引入完整外部框架或全局可变插件容器。此次仅移动现有技术适配责任，无新主链协议、信任边界或持久化事实，不新增 ADR。

## 接入与决定性证据

实现前规格及原判据保存于[规格归档](../../../.tmp/model-provider-policy-20261026/spec-implemented.md)。本轮基线是已完成参数集中的源码快照 `.tmp/model-provider-policy-20261026/before-src`，不是旧 HEAD，避免把上一轮参数修正重复计入收益。两个完整真实阶段沿用[来源清单](../../../.tmp/model-provider-configuration-20261026/sources.json)的请求/响应及 SHA-256；命令由[运行入口](../../evals/04-running-and-release.md#provider-配置与参数封装回放)拥有。

| 预声明目的 | 实际证据与边界 |
| --- | --- |
| 原主链行为保持 | 2/2 完整历史真实阶段，HTTP 正文分别 307,691 与 60,421 字节，基线/候选逐字节相同，响应投影相同 |
| 适配边界保持 | 7/7：Graphiti、LangExtract、图片默认/独立模型、DeepSeek top_p/none、MiMo 完整工具流式出站；图片为代表性 1×1 PNG 的配置检查 |
| 配置及拒绝保持 | 15/15：三家选择、独立绑定、显式空对象、实际模型覆写、max 默认与 Journal 往返、必要拒绝 |
| 独立扩展成立 | 2/2：新模块及注册项由真实配置选中，经原 SDK 发送完整历史工具请求，仅新增声明的外部字段；公共 SDK、kernel 契约及所有内置策略哈希不变。未知 ID 在发送前拒绝 |
| 身份与成本 | [最终报告](../../../.tmp/model-provider-policy-20261026/replay-final-v2/report.json) 26/26，19 次本机 HTTP，付费模型及工具执行 0；验证前后全部生产 Python 与回放脚本哈希一致，当前文件与该身份再次核对 |

本轮生产源码相对快照为 16 文件 +276/−126，净增 150 行。新增 typed 策略接口、能力数据、独立实现与显式装配，删除原集中品牌分支和逐请求解析。收益是新增规则的修改范围可隔离，不以总行数下降为依据。分层仍为 14 包/43 边，无新允许边、反向依赖、循环或生产调用层；工程与文档检查由评测盘点登记。

普通兼容策略保留此前按模型前缀识别 reasoning 模型的缺省规则；新服务应通过显式注册和能力数据接入，无须向该缺省判断补品牌。既有配置切换无需修改消费者。三家全部真实服务接受性、图片语义、完整产品成功率和发布矩阵不由本轮离线工程证据证明。

## 失败尝试与审查处理

共享工作区曾把新 kernel 契约写回旧版，候选在导入前失败，原日志保留，未产生模型请求。停止重复整组运行后，确认基线隔离进程不改写源码；用户已暂停其他写入，恢复新契约，并新增验证前后源码身份门禁。此前通过身份未冒称为被写回工作树通过。

独立评审确认两个 LangExtract 诊断脚本漏传新必填策略，已按配置工厂补齐。新增身份门禁首次因报告局部变量同名而停止，已改为独立初始身份变量；最终 26/26 在修正后的完整同组重新执行。未放宽原请求相等或拒绝判据，未维护或运行停用单元测试。

## 重新打开条件

后续实际完整请求出现策略参数漂移、独立模型错误继承、未知 ID 静默降级，或新增策略必须修改公共 SDK/已有策略时，封存输入、代码与配置身份，按该最早责任重新打开。新的服务协议或模型模式按实际契约单独准入，不从本轮样本外推。
