# ADR 0034：策略审计绑定所属 Runtime

## 背景与决定

同一进程的两个正式 Web 应用分别连接独立数据库；真实对话交付后，第一个应用拒绝其他主体读取 run，但管理员只在第二个应用查到该拒绝。全局 sink 被第二次 Runtime 装配覆盖。正式 baseline、先行规格、需求 `PAI-1` 至 `PAI-4` 及验收由[唯一设计](../optimization/to_verify/runtime-policy-audit-isolation.md)拥有。

将策略观测的绑定从进程单槽改为 Runtime 实例所有。现有 policy 契约提供 immutable `PolicyDecisionEvent`，`PolicyDecisionRecorder` 在原 observability 模块封装日志、可选持久化、指标与 trace ID 绑定。组合根构造一次 recorder 并注入 ToolExecutor/ToolGateway、MemoryFacade、ConversationService；存储写入口消费同一 typed 事件。全局 setter 和旧函数删除，不留兼容路径。

## 责任、契约与防护

业务调用点继续产生 action、effect、rule、主体和资源事实；recorder 不改决定、不补权限、不推定完成。每个 Runtime 显式注入自己已有的 PostgreSQL 写入口，其他 Runtime 的构造及生命周期不得替换它。普通独立构造场景使用本实例的仅日志 recorder；正式生产根有持久化绑定，不通过全局服务定位。

原记录字段及 trace ID 来源保持。allow 且 audit_required 为 false 时跳过；非 allow 始终记录。可选持久化错误继续记录异常且不替代权限处理；本决定不提升为必需审计原子提交保证。没有数据库 Schema、API 响应或认证／Policy 规则迁移。

## 取舍、验证与退出

显式注入沿用工程现有边界及[外部机制取舍](../optimization/completed/runtime-composition-boundary.md#外部机制与本工程取舍)。一个 immutable 内部事件替代自写自读 dict，一个实例 recorder 替代全局槽及函数；均有现存生产消费者。ContextVar 路由、全局 Registry、事件总线及自动 AOP 会增加隐式生命周期，因此不采用。

原定完整 target 为 `0/1`：计算转研究后预算耗尽，未到达最终审计读取；原始失败保持。随后恢复 baseline 的完整真实 Journal、经正式双应用 HTTP 回放 scope／审计阶段，反事实 `1/1`，零模型调用，所属应用一条拒绝、另一应用零条，owner 仍可读且普通用户不能查询审计。源码对照确认三个调用点值与判断、15 个事件字段及 SQL 顺序保持；全部生产绑定已迁移，旧全局入口删除。

上述证据支持审计归属机制修复，原 Product E2E target 仍未过，本项完整验收保持 A2，不作为产品或发布通过。实际身份、成本和剩余门禁由唯一设计及评测盘点拥有，不追加模型稳定性样本。

如新绑定导致缺审计、跨库、权限判断或字段回归，按真实证据撤回受影响修改并重审绑定；不得恢复无隔离的全局默认路由。长期责任决定不设虚构到期日。
