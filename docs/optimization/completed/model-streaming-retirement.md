# 退役无消费者的模型 token 流链路

问题编号：`MODEL-STREAMING-RETIREMENT-001`。2026-10-16 完成限定范围的内部重构。本文固化先行规格与工程证据，[实现前规格](../../../.tmp/model-streaming-retirement-20261016/preregistered-spec.md)保持原内容及 SHA-256；现行组合由[横切机制](../../architecture/cross-cutting.md)拥有。

## 目标、范围与依据

正式 SSE 入口 `adapters/web/routes/entry_stream.py` 调用 `AgentService.converse()`，在 Conversation 完成验收后将答案分块返回。整理前它也没有消费 `LlmClient.generate_answer_stream()`。搜索 `src/`、`evals/`、`scripts/` 发现，旧 token 流 Port、两个包装器和工厂只在其内部互相引用；组合根构造客户端后，只将其交给没有调用方的旧方法。上轮 Runtime 清理已删除同样没有调用方的转发方法，见[完成记录](runtime-composition-boundary.md)。

这是一项保持现有产品行为的内部删除，不以代码差异推定用户失败或质量收益。实现前保存实际源码、工作树身份、全部引用及工程基线；发现正式消费者、构造时独有校验或合法外部契约即停止对应删除并重新界定影响。

## 需求、方案与验收

| 需求 | 实施与删除项 | 可执行验收 |
| --- | --- | --- |
| `MSR-1` | 删除 `StreamChunk`、`StreamingModelClient`、`GovernedStreamingModelClient`、`ObservedStreamingModelClient`、`OpenAIModelClient.stream()`、`build_streaming_model_client()` 和 `LlmClient.generate_answer_stream()`；同步内部导入、导出及注入参数 | AST 和全库引用核对，确认保留源码中没有消费者；所有保留模型方法、请求与响应契约的 AST 保持，导入绑定按删除清单比较 |
| `MSR-2` | 组合根继续用现有 `StructuredModelClient.generate()` 承接结构化、工具调用和普通文本；只删除旧客户端的构造和传递 | Runtime 构造 AST 只允许删除对应 import、赋值与关键字；保留方法及其余生产源码的哈希保持；模型工厂、准入、重试与计量顺序保持 |
| `MSR-3` | 正式 SSE 继续返回 canonical Conversation 的已验收答案；普通模型调用内部的 SDK 流式 transport 保持 | SSE 路由、Conversation/AgentService、`_create_chat_completion()`、`_chat_kwargs()` 与子 Agent event stream 保持原源码或 AST；不删除普通调用的 `client.chat.completions.stream(...).get_final_completion()` |
| `MSR-4` | 当前架构准确说明唯一生产模型 Port 及 SSE 边界，旧路径全部清理 | 包依赖、Ruff 名称／导入、正式 CLI/Web 装配导入、文档链接／锚点与 `git diff --check` 通过 |

保留 Port 和业务 owner；没有新增模块、状态、配置、持久化或 AOP 引擎。删除无消费者的平行实现减少维护职责，也避免将现有流式观测差异误认为正式产品的计量缺口。此处沿用[已有外部机制取舍](runtime-composition-boundary.md#外部机制与本工程取舍)，不提出新 SDK 或中间件选型。

## 证据、预算与停止条件

原始证据写入 `.tmp/model-streaming-retirement-20261016/`，不覆盖上轮封存。工程核对脚本只分析当前源码及真实历史归档，不构造模型替身、输入输出样例或逐函数测试。保存实现前规格、源码、Git patch 身份；实现后比较保留定义、导入和全库引用，记录实际删除量。

历史复用限定为上轮已核实的个人知识召回归档 `data/e2e_traces/20260828T122504.790664Z-16248-f5733c42/`（原结果 `1/1`）与真实研究装配身份 `.tmp/research-unified-production-e2e-20261016/product-plan.json`（原结果 `0/1`）。召回归档的 3 个 checksum 有效；研究归档的 4 个模型相关文件中，Port、准入与 `runtime_llm.py` 与本轮基线一致，`structured_model.py` 不同。历史结果只提供原有链路背景，当前删除的行为保持由实际源码前后对照证明，不声称整条历史轨迹可直接复用。无法证明受影响模型请求、入口、权限或外部依赖语义保持时，停止内部重构准入，升级定向真实 E2E。

实现前审计扫描 409 个生产、评测与工程 Python 文件，旧符号的 37 处引用全部位于 5 个待改文件，没有外部消费者。旧工厂只构造配置持有者及包装器；其模型 Adapter 构造方法只保存配置，不产生 SDK 调用或独有配置校验。上轮 19 份工程证据 checksum 复核通过，原封存保持。

本轮预算为一次实现前源码／契约审计及修改后的对应工程检查，不启动模型或产品 E2E。Web 导入使用现有健康容器的本机 `16432` 端口，在独立随机数据库中执行实际装配与 Procedure 同步；保留 `.env`、容器与现有数据库。导入成功与完整产品交付分别解释。若工程检查失败，先定位本次删除与既有环境问题，不能通过保留无人消费的兼容链或扩大依赖白名单消除错误。

## 已执行证据与复杂度

- [基线](../../../.tmp/model-streaming-retirement-20261016/baseline.json)保存修改前源码、工作树 patch、先行规格 SHA-256、409 个文件的引用范围、37 处引用及历史归档身份。上轮 19 份工程证据及召回归档 3 份文件校验和有效；原始 `1/1` 与 `0/1` 结果保持。
- [源码对照](../../../.tmp/model-streaming-retirement-20261016/verification.json)确认 5 个文件只删除已声明定义和装配绑定，148 个保留定义及其余 AST 一致，导入与导出只减少相应符号。其余 404 个生产、评测与工程 Python 文件保持字节一致，其中生产源码 257 个；包含正式 SSE、Conversation、子 Agent 事件流、Prompt 与模型响应解析。
- 生产 Python 净减少 240 行，模型 Port 从两种收敛为一种；没有新增依赖、模块、配置、状态、持久化或模型调用。普通调用内的 SDK 流式 transport、deadline、协议修复、准入、重试和计量 AST 保持，未改变模型请求与业务结果契约。
- [装配检查](../../../.tmp/model-streaming-retirement-20261016/composition.json)中，真实 CLI/Web 导入及两个正式路由注册通过，4 个 Procedure 定义同步到独立临时数据库；没有 `PoolTimeout`、同步错误或模型／HTTP 请求日志标记。该检查耗时约 9 秒，临时库已删除，现有业务库没有参与写入。它证明装配与同步边界，不是 Product E2E 或模型服务可用性证明。
- [最终工程检查](../../../.tmp/model-streaming-retirement-20261016/final-checks.json)记录 5 条实际命令及日志，源码对照、分层、全量 `ruff check --select F401,F811,F821 src scripts`、`check_dev_spec.py` 与 `git diff --check` 均返回 0。分层仍为 14 包、43 边，无未知包、缺失包、循环或禁止边；规范路由为 `65/65`，目录路由为 `9/9`。7 份相关文档的本地链接与锚点已核对，实际数量及正文哈希保存在同一记录；正式 CLI/Web 装配另有上述独立数据库检查。

未运行停用的单元测试，也未新增产品 E2E 样本；没有回答质量、延迟、tokens 或恢复收益主张。保持职责和正式协议的死代码清理按 [REL](../../devSpec/migration-release.md#2-adr-准入)无需单独 ADR。架构入口、代码地图和上轮风险描述已同步。

## 脚手架修正与重新打开

基线审计最初使用了历史 JSON 的错误字段名，修正后又发现实际模型 Adapter 与历史身份不同。保留实际差异并收窄复用结论，没有更改历史归档或生产语义。

装配检查前两次失败来自新脚手架：先将 libpq DSN 误作生产 URL、误写 SSE 路由，随后错误地对 `ProcedureCatalog` 调用 `len()`。分别保存为 `composition-attempt1.*`、`composition-attempt2.*`，改为正式 URL、实际路由及 `all_specs()` 后通过；未据此修改生产代码或放宽判据。每次创建的独立数据库均已删除。

真实入口后续复现与本次删除相关的回归时，封存反例并重新打开本问题。独立的 Policy sink 归属问题随后已正式复现并接入实例绑定修复，见[审计隔离规格](../to_verify/runtime-policy-audit-isolation.md)；当前保证由[横切机制](../../architecture/cross-cutting.md#4-横切实现的强制边界)拥有，本次 token 流清理不替代该问题的验收。
