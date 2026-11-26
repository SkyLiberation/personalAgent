---
name: manage-feature-flags
description: 用于本仓库按 feature flag 切换功能或消融实验臂，以及新增、更新、重命名或移除已登记功能时同步维护实验组。
---

# Feature flag 控制与实验组维护

从[实验组记录](../../../docs/ablation/experiment.md)查找开关语义、接入状态和实验臂。从本次入口的配置与覆盖读取生效值。

## 配置实验

1. 核对 `config/feature_flags.toml`、`PERSONAL_AGENT_FEATURE_FLAGS_CONFIG` 和运行器覆盖，确认本次入口加载哪份配置、由谁消费。用[配置加载器](../../../src/personal_agent/kernel/feature_flags.py)校验完整键集和布尔值。
2. 按已登记的实验臂设置对应值，固定其余比较条件。每臂用独立进程和新会话，保存实际生效配置及源码身份。
3. 仅在任务包含实验运行时执行，记录结果与成本。临时切换完成后恢复约定配置。报告修改的开关与实验组、实际生效范围及证据坐标。

## Feature 变更必须同步实验组

按开关键查找加载、装配、消费者和实验定义，再依[实验组维护规则](../../../docs/ablation/experiment.md#3-feature-生命周期同步要求)同步配置、比较条件与组状态。上下文契约变化时使用 `manage-model-context`。
