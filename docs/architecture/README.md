# 工程架构入口

本目录是 personalAgent 现行工程架构的唯一入口。后续设计、开发、重构和评审以此定位职责与正式链路；框架随真实需求和证据演进，维护流程由 [ARC：架构基线与演进](../devSpec/architecture-ownership.md#8-架构基线与持续演进)拥有。

## 按任务阅读

| 任务 | 阅读入口 | 正文责任 |
| --- | --- | --- |
| 定义、设计或维护架构并判断业务适配 | [架构设计与维护 skill](../../.agents/skills/design-project-architecture/SKILL.md)、[ARC](../devSpec/architecture-ownership.md) | skill 提供业务驱动的设计与维护方法，ARC 拥有事实、分层及准入门禁 |
| 理解系统与用户目标的执行链 | [当前核心架构](core-architecture-current-state.md) | 全局职责、决策与执行交接、产品边界 |
| 区分当前主循环与待整理边界 | [现状混合点](core-architecture-current-state.md#31-当前主循环的职责混合)、[主循环边界 Spec](../optimization/to_verify/conversation-loop-boundaries.md) | 现状与候选分开；候选说明研究、交付及核验适用性，不代表已实现 |
| 定位修改位置、Port 和装配点 | [代码地图与依赖](code-map.md) | 实际包职责、功能入口、物理布局与架构约束的差异 |
| 隔离日志、计量、重试等横切关注点 | [横切机制与 AOP](cross-cutting.md)、[编码质量 skill](../../.agents/skills/write-quality-code/SKILL.md#2-隔离切面保持业务主流程清楚)、[COD 横切约束](../devSpec/code-structure.md#51-横切关注点与显式组合) | 架构正文维护现有实现与装配，skill 拥有机制选择方法，COD 拥有强制边界 |
| 切换或扩展模型 Provider | [模型调用组合](cross-cutting.md#2-模型调用的实际组合)、[配置绑定](../env.md#provider-选择与参数绑定) | 独立 provider 策略、显式工厂注入及实际模型绑定 |
| 设计插件、middleware 与 hook 的扩展位置 | [主循环扩展设计](../optimization/to_verify/conversation-loop-boundaries.md#35-扩展架构能力模块middleware-与-hook) | 待验证的能力装配、调用包装和生命周期通知；实际组合仍以横切机制正文为准 |
| 确定某个能力的详细行为 | [权威专题索引](../README.md#按主题找权威文档)、[业务链路](../workflow/README.md) | 专题拥有契约，workflow 解释具体用例；本目录只链接详细正文 |

新增需求的事实归属、依赖方向与框架准入遵守 [ARC](../devSpec/architecture-ownership.md)。本目录说明现行实现，候选方案按表中入口单独阅读。

## 架构、规范与证据的分工

| 内容 | 唯一归属 |
| --- | --- |
| 当前实现、正式入口与代码坐标 | 本目录及其链接的专题正文 |
| 必须遵守的事实归属、依赖与演进规则 | [ARC](../devSpec/architecture-ownership.md)；横切实现的强制边界由 [COD](../devSpec/code-structure.md#51-横切关注点与显式组合)拥有 |
| 设计规格、实现前依据和验证顺序 | [Spec 结构](../chinese-writing-spec.md#62-spec-结构与需求追溯)、[EVD](../devSpec/change-evidence.md#7-强制开发与设计流程)；在对应问题的唯一设计中记录架构影响 |
| 实质架构决定、兼容及实施例外 | [ADR 准入](../devSpec/migration-release.md#2-adr-准入)与对应 ADR |
| 尚未闭环的方案和实际产品结果 | [设计优化队列](../future/design-optimization-backlog.md)、[评测盘点](../evals/02-current-case-inventory.md) |

代码地图标明物理布局与架构约束的差异。历史审计保留在 `summary/`；架构变更的同步要求由 [ARC](../devSpec/architecture-ownership.md#8-架构基线与持续演进)拥有。

既有取舍与证据分别见 [Runtime 装配整理](../optimization/completed/runtime-composition-boundary.md)、[旧模型流退役](../optimization/completed/model-streaming-retirement.md)和[策略审计隔离](../optimization/to_verify/runtime-policy-audit-isolation.md)。本入口不重复维护这些问题的验收状态。

## 维护验收

沿代码地图核对正式入口、Port、实现和装配，区分约束、当前实现与已验证结果。文档归属和引用按 [DOC](../AGENTS.md#5-提交前检查)检查，本目录包含在规范检查范围内：

从仓库根执行：

```powershell
.\.venv\Scripts\python.exe scripts/check_dev_spec.py
git diff --check
```

代码依赖变化另运行 `scripts/check_layers.py`；其范围见[代码地图](code-map.md#4-依赖检查的权威来源与覆盖)，CI 配置见 [architecture.yml](../../.github/workflows/architecture.yml)。产品变更按 [REL 完成门禁](../devSpec/migration-release.md#3-完成检查表)验收，文档检查不证明用户结果。
