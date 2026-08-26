# 调查项目收敛消融

本目录只保存 `INVESTIGATION-CONSOLIDATION-001` 的独立消融 patch，不提供生产 feature flag。两份 patch 都以当前候选为基准，并且只能在干净、可还原的独立 worktree 中应用。

`capacity_admission.patch` 只关闭 `AgentGateway.submit()` 对 `max_concurrent_runs` 的生产消费。配置、canonical `AgentRun`、Postgres 事务、调查项目逻辑、输入和评测器保持不变。

`project_lifecycle_consumers.patch` 同时撤去同一个已准入机制的三个生产消费点：预算不足时不再执行可容纳子集；`pending` 不再让出当前工作进程周期；`EvidenceRef.content_digest` 不再读取产物正文摘要。容量准入、连接池、模型、服务提供方、输入和评测器保持不变。

执行前先校验 patch 与目标代码状态：

```powershell
git apply --check evals/ablations/investigation_consolidation_001/capacity_admission.patch
git apply --check evals/ablations/investigation_consolidation_001/project_lifecycle_consumers.patch
```

`SHA256SUMS` 冻结两份 patch 的内容身份。patch 发生任何变化时，必须重新评审唯一消融变量并更新校验和，不能沿用旧 target 或旧消融归档。

每次只应用一份 patch，执行同一正式产品用例并归档；完成后使用 `git apply -R` 撤回。容量消融必须重新出现超过上限的执行中提交或资源失败。生命周期消费点消融必须重新出现第三组 baseline 中的预算整批拒绝、轮询风暴或正文摘要不一致。若反事实没有复现，候选不能取得因果归因。

2026-08-25 的 Conformance 预检已经证明 patch 命中预期变量。容量 patch 使 `test_agent_gateway_admits_new_async_runs_only_when_provider_slot_exists` 由通过变为失败；生命周期 patch 使预算子集、`pending` 让出和正文摘要三条 owner 测试全部由通过变为失败。两份 patch 随后均已反向应用，当前候选代码恢复。该预检不包含真实模型和用户结果，不能计为产品消融。
