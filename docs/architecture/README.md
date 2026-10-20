# 工程架构入口

本目录是 personalAgent 现行工程架构的唯一入口。后续设计、开发、重构和评审以此定位职责与正式链路；框架随真实需求和证据演进，维护流程由 [ARC：架构基线与演进](../devSpec/architecture-ownership.md#8-架构基线与持续演进)拥有。

## 按任务阅读

| 任务 | 阅读入口 | 正文责任 |
| --- | --- | --- |
| 理解系统与用户目标的执行链 | [当前核心架构](core-architecture-current-state.md) | 全局职责、决策与执行交接、产品边界 |
| 区分当前主循环与待整理边界 | [现状混合点](core-architecture-current-state.md#31-当前主循环的职责混合)、[主循环边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md) | 现状与候选分开；候选说明研究、交付及核验适用性，不代表已实现 |
| 定位修改位置、Port 和装配点 | [代码地图与依赖](code-map.md) | 实际包职责、功能入口、物理布局与架构约束的差异 |
| 隔离日志、计量、重试等横切关注点 | [横切机制与 AOP](cross-cutting.md) | 现有实现、显式组合方式、机制选择与防护 |
| 设计插件、middleware 与 hook 的扩展位置 | [主循环扩展设计](../optimization/to_verify/conversation-loop-boundaries.md#35-扩展架构能力模块middleware-与-hook) | 待验证的能力装配、调用包装和生命周期通知；实际组合仍以横切机制正文为准 |
| 确定某个能力的详细行为 | [权威专题索引](../README.md#按主题找权威文档)、[业务链路](../workflow/README.md) | 专题拥有契约，workflow 解释具体用例；本目录只链接详细正文 |

新增需求先确定 Application 或业务事实的责任主体，再沿 typed Port 接入现有执行与治理边界。具体业务规则留在能力内，跨业务机制按 [ARC 框架准入](../devSpec/architecture-ownership.md#4-framework-capability-准入与边界)抽取；设计模式用于隔离真实变化和信任边界。

## 架构、规范与证据的分工

| 内容 | 唯一归属 |
| --- | --- |
| 当前实现、正式入口与代码坐标 | 本目录及其链接的专题正文 |
| 必须遵守的事实归属、依赖与演进规则 | [ARC](../devSpec/architecture-ownership.md)；横切实现约束由 [COD](../devSpec/code-structure.md#51-横切关注点与显式组合)接入 |
| 设计规格、实现前依据和验证顺序 | [Spec 结构](../chinese-writing-spec.md#62-spec-结构与需求追溯)、[EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)；在对应问题的唯一设计中记录架构影响 |
| 实质架构决定、兼容及实施例外 | [ADR 准入](../devSpec/migration-release.md#2-adr-准入)与对应 ADR |
| 尚未闭环的方案和实际产品结果 | [设计优化队列](../future/design-optimization-backlog.md)、[评测盘点](../evals/02-current-case-inventory.md) |

当前说明不得把设计约束写成已经全面实现的事实。代码地图标明已核实差异；改变责任或契约时，在同一变更更新设计、实现、架构正文、受影响专题和引用，删除被替代路径。历史审计保留在 `summary/`，不再拥有现行架构正文。

外部 Agent 架构的比较、当前约束与装配边界取舍见[Runtime 整理记录](../optimization/completed/runtime-composition-boundary.md)。该记录拥有本次设计与工程证据，本目录维护整理后的当前路径。

无消费者的旧模型 token 流链路已按[退役记录](../optimization/completed/model-streaming-retirement.md)删除；正式 SSE 继续消费 Conversation 的已验收答案，模型调用沿用现有统一 Port 和显式包装器。

策略审计已由进程全局 sink 改为 Runtime 实例绑定，见 [ADR 0034](../adr/0034-runtime-policy-audit-isolation.md)。真实读取阶段的隔离反事实通过；原完整对话 target 仍失败，验收范围及剩余条件由[唯一规格](../optimization/to_verify/runtime-policy-audit-isolation.md)拥有。

## 维护验收

架构事实依据生产代码、装配工厂和适用执行证据核对。文档与包依赖使用现有检查入口，CI 执行相同命令；文档迁移检查正文归属和引用，产品行为变化另按其证据类别验收。

| 要求 | 可执行验收与通过条件 |
| --- | --- |
| 架构事实可定位 | 沿代码地图走读正式入口、Port、实现及装配，区分约束、实际实现和未验证结果 |
| 文档只有一份现行正文 | 被替代正文删除，受影响引用指向对应权威文档；本地链接与标题锚点有效 |
| 后续规范可发现 | 根 `AGENTS.md` 与 `CLAUDE.md` 字节一致；任务及目录导航样本全部命中，指令链符合尺寸门禁 |
| 依赖与文档门禁持续执行 | `check_layers.py` 无未知包、缺失包、循环或禁止边；`check_dev_spec.py` 覆盖本目录；CI 执行这两个命令 |

从仓库根执行：

```powershell
.\.venv\Scripts\python.exe scripts/check_layers.py
.\.venv\Scripts\python.exe scripts/check_dev_spec.py
git diff --check
```

这些检查分别验证静态包依赖和文档结构，不能证明业务归属、权限或用户结果。文档整理不运行产品 E2E、真实模型或停用的单元测试；后续生产变更仍按 [REL 完成门禁](../devSpec/migration-release.md#3-完成检查表)选择适用验证。
