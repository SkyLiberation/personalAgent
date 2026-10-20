# Runtime 策略审计隔离规格

问题编号：`RUNTIME-POLICY-AUDIT-ISOLATION-001`。2026-10-16 最小修复已接入，完整真实读取阶段回放 `1/1`；原定 Product E2E target 因未交付用户答案仍为 `0/1`，完整验收未完成，保留 `A2`。准入由[队列](../../future/design-optimization-backlog.md)拥有。本文唯一拥有方案、预声明和推进记录，当前实现见[横切机制](../../architecture/cross-cutting.md#4-横切实现的强制边界)。

## 问题、范围与责任

修复前 `kernel/observability.py` 使用进程全局 `_policy_decision_sink`，`AgentRuntime` 每次构造均重新注册。工具网关、MemoryFacade 和 Conversation 的 scope 拒绝调用同一全局函数；存储及管理员查询则绑定各 Runtime 自己的 PostgreSQL。正式 baseline 已证明第二个应用覆盖 sink，使第一个应用的拒绝记录进入另一数据库。失败身份及最早责任见下文。

这是恢复审计归属不变量的产品修复。事件由产生决定的用例拥有，组合根只绑定存储；模型拥有对话语义，认证、Policy 与权限拒绝仍由当前 owner 判断。可选观测的异常隔离保持，本次不调整必要审计的原子提交协议。

## 需求与可执行验收

| 需求 | 正式入口与结果 | 通过判据及反事实 |
| --- | --- | --- |
| `PAI-1` | 同进程两个 `create_app()` 应用分别使用独立库和数据目录。用户在第一个应用 POST `/api/conversation/turn`：“请帮我计算 17 加 25，直接告诉我结果。” | 经过真实模型及 canonical Conversation，HTTP 200、disposition 为 answer、最终文本给出 42 或四十二；保存完整真实 run 与用量。用户结果与审计检查点分别计分 |
| `PAI-2` | owner 读取同次 run 成功，另一认证用户读取被拒绝；普通用户没有审计管理权限 | owner GET 200，其他用户 GET 404，普通用户查策略审计 403；owner 读取不产生 scope 拒绝记录 |
| `PAI-3` | 管理员在第一个应用查到同次 run 的拒绝，第二个应用不得返回该记录 | 正式管理员 API 比对 run、resource、action、effect、rule 和认证 principal；所属应用恰一次对应拒绝，另一个为零；日志不替代查询结果 |
| `PAI-4` | baseline 若证明全局绑定是最早责任，则移除全局槽与 setter，向三个调用点显式绑定所属 Runtime 的 recorder | typed 事件、全部生产消费者迁移、旧入口删除；保持字段、日志、指标、allow 的 audit_required 跳过和可选 sink 异常隔离；同一 E2E target 及静态门禁通过 |

正式用例 `AUD-001` 登记 canonical catalog。新进程只用环境配置构造两个真实 FastAPI 应用并挂载路径，执行各自生产 lifecycle、认证、模型和存储；不替换方法、决策、结果、Verifier 或 Completion。用例自行创建独立数据库，不清理共享库，不新增停用 `tests/` 依赖。若自然对话未完成，保留原始失败并定位，不手工创建 run 或注入 Journal。

## 当前最小方案

现有 policy 契约增加 immutable `PolicyDecisionEvent`；现有 observability 模块用实例 `PolicyDecisionRecorder` 封装原记录逻辑；组合根向三个实际消费者注入同一 Runtime 的实例；现有 PostgreSQL 写入口消费 typed 事件。读取 API 保持外部字典边界，无 Schema 迁移。

删除全局注册、全局记录入口及其导入，保留唯一实例写链。新增结构均有当前消费者；局部阅读范围是事件契约、recorder、三个调用点、存储写入口及装配。不引入 ContextVar 路由、服务定位器、事件总线、自动 AOP 或新生产配置。沿用[已复核的显式 DI 取舍](../completed/runtime-composition-boundary.md#外部机制与本工程取舍)，外部机制不代替本地失败证据。

## 身份、预算与停止条件

归档根 `.tmp/runtime-policy-audit-isolation-20261016/`，baseline 与 target 独立封存：代码、dirty digest、配置／Prompt 身份、正式请求响应、完整 run、用量、原始 pytest 结果、日志及 checksum。使用现有健康 PostgreSQL `16432` 端口，每次只创建和删除本轮随机命名的两个数据库；数据目录位于本次归档，进程退出后才清库，保留 `.env`、容器和现有数据库。

预声明 baseline 1、准入后 target 1，不做稳定性扩样。使用默认 Interaction Mode，最多 8 个模型决策回合、80,000 任务 tokens，模型超时沿既有配置，HTTP 请求上限 360 秒、启动上限 45 秒。简单计算仍经过真实意图、核验和完成；60 秒是成本复核信号，原子请求安全结束后核对成本再决定是否开始下一样本，不强杀未归档模型调用。独立阻塞和重复阻塞按 [EVD](../../devSpec/change-evidence.md#71-独立阻塞优先解决并保持方案一致性)处理，不用生产补丁迎合脚手架。

首次启动因挂载后的 health 路径包含前缀，现有认证中间件未将其视为公开路径，新脚手架缺少认证头而收到 401。原始 setup error 保存在 `.tmp/runtime-policy-audit-isolation-20261016/startup-failure/`；自然请求和真实模型均未执行，不计产品失败 baseline。只为 readiness 补充已配置认证头，保持生产认证行为，随后执行预声明 baseline。

## baseline 与实施准入

原始归档为 `.tmp/runtime-policy-audit-isolation-20261016/baseline/e2e/20261016T070754.042879Z-22936-3da76fb9/`。完整用例 `0/1`：自然计算用户结果成立，答案为 `17 + 25 = **42**`；owner 读取 200，其他用户 404，普通用户查审计 403。所属应用拒绝数为 0，第二应用为 1，且 run、resource、主体和拒绝规则匹配。这是实际审计归属失败，不是权限漏放。HTTP 旅程 26.094 秒，pytest 35.09 秒，命令总计 38.399 秒；未触发 60 秒成本复核线。

日志有 4 个实际模型 HTTP 成功响应；Conversation 用量提交为 3 次、14,858 tokens，前置 InteractionIntent 调用不在该总账中，本轮未另取得其 tokens，记一次未知，不填零。保留完整 run 及服务器日志，两个随机数据库均已删除，没有现有业务库写入。

第二应用构造时执行同一 setter，第一应用 scope 拒绝随后读取被覆盖的全局槽，是最早责任。只改变 recorder 绑定即可切断因果链；target 仍需同一自然请求与完整鉴权、审计反事实，不能仅看对象分离。生产方案及跨模块决定见 [ADR 0034](../../adr/0034-runtime-policy-audit-isolation.md)。若 target 仍跨库、缺事件，或拒绝及现有日志／字段行为改变，停止接入并按实际责任撤回；不追加全局路由、配置开关或自动重试。

最小修复复用当前模块，迁移三个调用点及 ToolExecutor 转交、存储写入、Runtime 装配。独立构造的调用方使用本实例的仅日志 recorder 或显式传入持久化 recorder；生产根统一绑定本实例存储。原 target 和阶段回放分别按下文保存，不把后者提升为整例通过。

## target 原始失败与责任边界回放

target 原始归档为 `.tmp/runtime-policy-audit-isolation-20261016/target/e2e/20261016T071135.459089Z-21256-57d23072/`，结果仍为 `0/1`：模型自主把计算转入核验、Web 检索和研究，8 回合后返回 budget limitation，没有交付答案。总账记录 11 次、90,370 tokens，日志有 13 个实际模型 HTTP 响应；总账外用量未完整取得，保持未知。命令 315.003 秒、pytest 311.73 秒。原子请求正常结束，两个数据库已删除；没有强杀在途模型。

原规格中的在途续接诊断只执行到脚手架 URL 发现失败，未发送 HTTP、未触发模型；随后目标已结束，不重启 live 模型。记录这次未到达，不将其充当审计通过。205 个保留方法、模型／Prompt／协议保持的源码对照已通过，未在本问题中修补这条研究轨迹。

[同轨迹只读诊断](../../../.tmp/runtime-policy-audit-isolation-20261016/blocking-feedback.json)定位到第一个可见拒绝：模型最初已提交正确的 `17 加 25 的结果是 **42**`，`runtime-verify-0` 对直接交付标准判 satisfied，但追加的通用来源标准因 execution_evidence 为空判 insufficient_evidence，并要求补执行证据和引用；之后才出现 Web 搜索与研究。这只证明实际拒稿及其反馈链，尚未完成实际模型请求与构造链审计，不把推断的根因写成已修复。

阶段回放执行前另行预声明 `AUD-001-REPLAY` Offline Eval：从 checksum 有效的 baseline 归档恢复完整实际 `primary-data/interaction_runs`，保留原始 run、principal、conversation、messages、最终答案及全部修订字节；其他数据库初始为空。使用同一正式双应用进程和当前生产装配，仅 GET owner、GET 其他主体、普通用户查审计、两应用管理员查询。通过条件与 `PAI-2`、`PAI-3` 完全相同；baseline 的相同真实 run 曾得到所属库零、另一库一，回放必须为一、零。先行规格保存在 `.tmp/runtime-policy-audit-isolation-20261016/replay/preregistered-spec.md`。

回放实际为 `1/1`，归档 `.tmp/runtime-policy-audit-isolation-20261016/replay/e2e/20261016T072004.573854Z-19800-f945f278/`：源 Journal 与密封 HTTP owner Trace 相等，恢复文件字节一致；owner 200，其他主体 404，普通用户查审计 403，所属应用一条正确拒绝、另一应用零条。零模型调用，命令 11.147 秒、阶段检查 7.984 秒，两个新隔离数据库已删除。该反事实直接证明既有读取阶段的审计归属修复，不提升 Product E2E 分子。

## 工程证据、剩余门禁与停止条件

[源码对照](../../../.tmp/runtime-policy-audit-isolation-20261016/source-audit.json)核对 8 个修改文件：205 个保留方法不变，三个策略生产点的判断和事件值在剥除 typed 绑定后 AST 相同；15 个字段及 SQL／写入顺序保持，三个生产依赖绑定同一 Runtime 实例。其余 254 个生产 Python 文件字节保持，未改模型、Prompt、工具协议、认证、Schema 或依赖。新增一个 immutable 事件和一个 recorder，替代无 schema 字典、全局槽、setter 和函数；生产净增行数由实际对照保存，没有新增模块或持久化字段。

原 `v1` E2E 在用户结果失败时提前退出，未执行的审计字段默认 false，不能把这些值解释为审计机制失败。新 `v2` 改为未执行值 null，合法 run 返回后继续采集 scope 检查点，最终仍要求用户结果与审计结果均成立；原两个 `v1` 归档和失败保持，不重标。`v2` 只做静态及收集检查，未新增 live 样本。

新脚手架收尾也移除 30 秒后强制终止进程的分支：若 HTTP 已超时而真实调用仍在完成，保留原失败，等待生产请求与 lifecycle 安全结束后再删隔离数据库。既有两次实际 E2E 均在正常响应后完成收尾，没有触发旧终止分支；不为这次脚手架防护追加模型样本。

[最终工程记录](../../../.tmp/runtime-policy-audit-isolation-20261016/final-checks.json)保存 8 条命令及日志：源码对照、分层、Ruff 名称／导入、三个新评测文件格式、规范、单个新 E2E collect-only、catalog／重叠审计和 `git diff --check` 均通过。分层为 14 包、43 边且无违反，规范路由 `65/65`、目录 `9/9`；14 份相关文档的链接、锚点及正文哈希保存在同一记录。三份实际运行归档 checksum 有效，baseline／target 输入和配置身份可比较，原失败不覆盖。当前 262 个生产模块的 AST 与实际回放代码一致；回放后唯一生产字节变化是空行。

本次生产净增 13 行；新增评测源码共 3 个文件、629 行，用于同进程双真实应用、独立数据库 lifecycle、正式用户旅程和完整真实阶段回放，catalog 为唯一分类入口。没有新生产模块、依赖、持久化字段、自动织入或停用单元测试；评测基础设施的规模计入本次维护成本，不能只报告生产行数。

策略归属机制已取得真实失败与完整阶段反事实，但本项原定完整 Product target 未过，故不迁 completed、不声明完整产品或发布通过。下一步只能基于已封存 target 的实际决策／核验输入分析其计算任务转研究的独立原因；本轮已达到停止新增模型样本的成本信号，不继续同配置重跑，也不在审计 recorder 中补 Prompt、预算或任务特判。剩余状态和正式结果分别由队列及[评测盘点](../../evals/02-current-case-inventory.md#2026-10-16-runtime-策略审计隔离)拥有。
