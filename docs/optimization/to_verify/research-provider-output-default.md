# 研究请求采用服务方默认输出额度

问题编号：`RESEARCH-SELECTION-OUTPUT-TRUNCATION-001`。上位问题为研究反馈修订无法收敛；[失败与推进记录](../claim-revision-nonconvergence.md#2026-10-02-选证输出截断阻断正式研究)保存正式入口失败，[设计队列](../../future/design-optimization-backlog.md)拥有准入状态。

## 问题与目标

正式研究选证及其一次结构修复均在 8,192-token 输出上限处截断，完整必填 `reason` 未能解析，入口返回 503，研究稿尚未创建。实发额度包含思考与正文，原始请求及响应见[封存审计](../../../.tmp/source-attribution-product-target-20261002/selection-failure-audit.json)。用户于 2026-10-02 要求采用服务方默认限制，并暂不运行测试。

目标是让服务方为研究请求提供模型默认输出空间，使完整 typed 结果能够生成并进入原研究链。MiMo [官方 Chat Completions 契约](https://mimo.mi.com/docs/en-US/api/chat/openai-api)允许省略 `max_completion_tokens`，标注 `mimo-v2.6-flash` 默认上限为 131,072 tokens，包含思考与正文。

## 解决机制与防护设计

1. `StructuredModelRequest.max_tokens` 使用 `int | None`，默认 `None`。该空值唯一表示采用服务方默认输出额度；研究构造器移除固定的 8,192。选证、来源支持和覆盖核验沿同一正式构造器消费此契约。
2. `ModelCallIntent` 与 `ModelInvocationGrant` 原样携带额度选择。准入对显式整数继续执行正值及既有上限校验；空值交给服务方默认额度契约。身份、Context 引用和敏感内容出站检查继续在同一准入边界执行，审计记录空值而不推测实际服务方额度。
3. 真实 `OpenAIModelClient` 在额度为空时省略 `max_completion_tokens` 和 `max_tokens`；显式额度按当前模型对应的参数传递。结构化、文本、工具与流式请求共用该参数构造边界；结构修复沿原请求保留额度选择。
4. Prompt、输出 Schema、thinking、重试次数、单请求超时和累计运行预算沿现行责任主体执行。累计 token 预算继续按已提交用量在调用边界检查；本轮仅替换研究阶段的单次固定额度。

正式可达路径为 `ConversationService -> research_request -> GovernedModelClient -> OpenAIModelClient`。生产修改涉及研究构造器、模型请求及授权类型、准入和 Adapter 四个既有文件，无新增生产模块、配置开关或备用路径；其他生产调用方显式指定的额度继续按其请求传递。现行使用说明由[LLM 配置](../../env.md#llm-配置)拥有。

## 接入与验证状态

候选已进入目标代码。历史 baseline 保持原身份和失败结果；本轮按用户要求暂不运行测试，真实模型调用、Offline Eval 与 E2E 均为 0。已执行 `ruff check` 与 `compileall -q`，四个生产修改文件均通过；本次八个已跟踪修改文件的 `git diff --check` 通过，新增候选文档另检查空白与代码围栏。五份受影响文档共检查 200 个本地链接及锚点，错误为 0。工程静态检查只核对代码与文档，不计作恢复效果证据。

用户恢复验证后，先沿封存失败请求核对实际参数省略、完整必填输出和一次修复的额度继承，再以原中文任务及空资料进入同一正式 E2E，连续消费实际选证结果及后续研究输出。原 Prompt、模型、thinking 和评分身份固定，只有单次额度选择改变；运行前另行预声明调用量、累计成本和停止条件。本轮模型调用预算为 0。

参数被其他构造层重新填入、默认额度导致输出契约继续失败或出现准入及出站回归时，停止追加相同方向修正并保存原始结果，重新审查该责任边界。撤回通过恢复本候选的代码差异执行，比较身份独立归档。
