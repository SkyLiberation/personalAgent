# Runtime 装配边界整理

问题编号：`RUNTIME-COMPOSITION-BOUNDARY-001`。2026-10-16 完成限定范围的内部重构。实现前在原唯一设计中固定范围、验收及历史证据边界；实现后固化于本文。[实现前规格](../../../.tmp/runtime-composition-boundary-20261016/preregistered-spec.md)保留原内容与 SHA-256。

## 目标、范围与事实依据

整理前，`AgentRuntime` 同时包含个人知识读取的筛选与结果投影，以及未被正式入口消费的旧知识适配器、简报组装和回答辅助函数。`runtime_helpers.py` 的 12 个函数只被 Runtime 导入及列入 `__all__`，没有当前生产、工程脚本或正式评测消费者；同名的 Capture 与 Evidence 函数有独立消费者，继续保留。

基线搜索命令为 `rg -n` 核对上述符号在 `src/`、`evals/`、`scripts/` 的引用，并结合 AST 区分定义、内部互调、导入与实际消费；不以文件长度或导出名单证明生产可达。补充包检查与 Ruff，记录当前静态门禁为何没有识别这些遗留路径。证据保存在 `.tmp/runtime-composition-boundary-20261016/`，修改前保存源码、工作树差异、代码与实际归档身份。

已执行 `audit_composition.py baseline`：扫描 407 个其他生产、评测与工程脚本文件，确认上述删除路径外部静态消费者为 0；Runtime 为 1298 行，辅助文件为 197 行，行数只界定范围。`check_layers.py` 为 14 包、43 边且无违反，Ruff 通过；静态依赖与导入检查不证明被导出的内部函数有生产消费者。

历史复用绑定两份真实正式入口资料：`data/e2e_traces/20260828T122504.790664Z-16248-f5733c42/` 的个人知识召回原结果为 `1/1`，3 个归档文件的 checksum 有效；`.tmp/research-unified-production-e2e-20261016/product-plan.json` 中 Runtime 与辅助文件的 SHA-256 均与实现前工作树一致，该次研究 E2E 的原结果仍为 `0/1`。前者只支持既有知识召回边界，后者只核对正式装配身份，均不记作本轮新版本通过。模型构造链与实际消费者由本轮源码／契约对照证明保持。

现有知识读取适配器已迁至 [`application/conversation/knowledge_reading.py`](../../../src/personal_agent/application/conversation/knowledge_reading.py)，名称为 `ConversationKnowledgeReadAdapter`，仍由组合根注入 `ConversationService` 的 `ConversationKnowledgeReadPort`。原定义、旧别名和无消费者路径均已删除；知识 owner、过滤规则、typed 输入输出、模型可见内容、权限、状态、副作用和恢复契约保持。

## 外部机制与本工程取舍

2026-10-16 复核以下 A 级官方文档，动态页面按访问日期解释，不代表本工程采用相应 SDK 或最新依赖版本。

| 对象与来源 | 可确认机制 | 对本工程的取舍 |
| --- | --- | --- |
| [OpenHands 架构](https://docs.openhands.dev/sdk/arch/overview)、[设计原则](https://docs.openhands.dev/sdk/arch/design) | Agent、Conversation、LLM、Tool、Workspace 与应用职责分离，组件 typed 且可组合 | 采用清楚的核心与应用边界；不照搬四包部署，也不把多个业务 Aggregate 合并为一个状态 owner |
| [LangChain Runtime](https://docs.langchain.com/oss/python/langchain/runtime)、[Middleware](https://docs.langchain.com/oss/python/langchain/middleware/overview) | 通过运行上下文向工具和中间件提供依赖，显式扩展模型与工具调用边界 | 保留既有 Port 注入及显式包装；本轮迁移现有适配器，不创建新容器或通用中间件引擎 |
| [Google ADK Callback 设计](https://adk.dev/callbacks/design-patterns-and-best-practices/) | 生命周期回调可承接日志、状态及请求处理，并要求职责清楚、可靠且可说明 | 技术横切继续遵守[现有约束](../../architecture/cross-cutting.md)；不把业务事实写入和完成判断隐藏到可替换回调中 |

这些资料解释机制，当前重构必要性仍由本地调用关系和工程对照证明。没有依据将改用 SDK、多智能体、事件总线或自动 AOP 织入作为本轮方案。

## 需求、契约与验收规格

| 需求 | 必须达到的结果 | 预声明验收 |
| --- | --- | --- |
| `RCB-1` | 删除确认为无消费者的旧知识适配器、私有简报分支、回答转发方法及 `runtime_helpers.py`，清理相应导入、导出和打包清单 | 前后 AST 与全库生产引用对照；删除项不出现在任何保留的活跃函数中；保留函数实现 AST 一致 |
| `RCB-2` | 现有知识读取适配器迁至 `application/conversation/knowledge_reading.py`，组合根只负责构造与注入 | 迁移类除名称外的 AST 一致；装配表达式仅替换类名；同一 KnowledgeService 与现行 Port 的消费者保持 |
| `RCB-3` | 模型请求、工具定义、权限及知识结果不因文件移动和删除死代码改变 | 受影响调用链的源码／契约哈希与 AST 对照；绑定已有真实正式入口归档，按当前差异限定历史复用范围；不把历史通过记为新版本 E2E |
| `RCB-4` | 当前架构、引用与工程门禁反映整理后的正式路径 | 分层检查、生产导入、Ruff、相关文档链接和 `git diff --check` 通过；无新增依赖、状态、模型调用或替代契约 |

工程对照脚本保存基线与修改后的结构、源码 SHA-256 和真实归档校验结果。只执行真实源码与契约的工程对照，复用已声明的真实归档身份，没有注入模型或工具结果，也没有建立单元测试替代套件。

## 决定性工程证据与复杂度

- [基线](../../../.tmp/runtime-composition-boundary-20261016/baseline.json)保存原代码身份、工作树 patch 哈希、407 个文件的引用核对范围及两个真实归档的复用边界。
- [前后对照](../../../.tmp/runtime-composition-boundary-20261016/verification.json)确认保留的 58 个 Runtime 方法实现 AST 一致，构造方法只替换读取适配器名称；迁移类的 3 个方法 AST 一致，两个读取操作的实际签名与解析后的类型均符合原 Port。其余 260 个生产源码文件字节保持。
- 删除 6 个旧类、4 个私有方法、12 个辅助函数及旧导出。Runtime 从 1298 行降为 1054 行；删除 197 行辅助模块，迁移类所在新模块为 71 行，生产 Python 源码净减少 370 行。模块总数保持，不新增状态、抽象接口、持久化、依赖或模型调用；打包清单同步替换模块条目。
- 生产装配与 Conversation 导入、包依赖检查及全量 `src scripts` 的 Ruff 导入／名称检查已通过。模型请求构造、Prompt、Schema、实际消费者与外部依赖代码均未改变，权限和恢复协议未迁移；本轮没有新增产品 E2E 样本或模型调用，不把历史 `1/1` 或研究失败改记为当前产品结果。
- [工程检查记录](../../../.tmp/runtime-composition-boundary-20261016/final-checks.json)保留 7 条实际命令、返回码、耗时与原始日志：AST／Port 对照、分层、`ruff check --select F401,F811,F821 src scripts`、新模块格式、CLI/Web 导入、`check_dev_spec.py`、`git diff --check` 全部返回 0。规范导航为 `65/65`，目录路由为 `9/9`；6 份架构与优化文档的 218 个本地链接、51 个锚点通过检查。

CLI/Web 导入同时触发了既有 Procedure 定义同步，在该进程环境中记录 PostgreSQL 连接池 `PoolTimeout`，异常被原有装配代码捕获。导入成功只证明模块及构造路径可加载，不证明数据库同步、服务健康或产品交付。相关同步方法与存储实现均保持原字节或 AST，本轮未将这条环境诊断作为产品修复依据，也没有启动服务器或真实 E2E。

新增一次从装配入口到 Application 实现的明确跳转，换取业务读取投影回到其消费能力内。职责与契约保持的文件归位按 [REL](../../devSpec/migration-release.md#2-adr-准入)不单独触发 ADR；验收限于工程行为保持和已声明范围，不主张回答质量、时延或成本改善。

## 其余已观察边界

- `domain/` 仅有包声明，是物理布局现状，不能仅凭空目录推断产品缺陷或准入全库领域模型迁移。
- 上轮记录的全局 Policy sink 风险随后由正式双应用 baseline 证实为串库，实例绑定修复及真实阶段反事实已成立；原完整 target 仍失败，见[审计隔离规格](../to_verify/runtime-policy-audit-isolation.md)。本记录不拥有后续状态。
- 上轮观察到旧模型 token 流的观测／计量组合与普通模型不同；后续已核实其没有当前消费者并退役，见[删除与行为保持证据](model-streaming-retirement.md)。正式 SSE 和 SDK 内部 transport 的当前边界由[横切机制](../../architecture/cross-cutting.md#2-模型调用的实际组合)拥有。
- 当前 `_verifier` 虽未找到业务读取者，其构造工厂会校验 `ask.verifier` 配置。删除实例会改变非法配置的拒绝行为，不能混入严格保持行为的死代码清理；现有语义保留。

上述事实或风险不冒充已复现的用户失败，也不据此准入新的运行机制。当前工程收益仅主张责任归位和无消费者代码减少，不主张回答质量、延迟、tokens 或恢复能力提升。

## 修正记录与重新打开条件

首次 Ruff 检查发现清理时误删了活跃捕获流程仍使用的 `ReviewCard` 导入，已恢复；这说明方法 AST 对照仍须结合导入检查。后续对照加入保留导入绑定检查，与原行为保持判据一起通过。未改变方案或放宽验收。

收尾证据脚本首次启动因未将仓库根目录加入 Python 搜索路径而失败，补齐脚手架路径后执行全部既定工程命令；这次修正未修改生产规则。

后续实际入口或真实 E2E 出现与本次迁移、删除相关的输出、权限、装配或恢复回归时，封存新证据后重新打开本问题。其他框架差异与独立产品失败按各自责任处理，不将本次限定工程整理外推为框架已全面纯化。
