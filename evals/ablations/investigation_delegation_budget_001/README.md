# 调查项目委托时间预算消融

本目录只保存 `INVESTIGATION-DELEGATION-BUDGET-001` 的独立消融 patch，不提供生产 feature flag。

`admission_consumer.patch` 只撤去 `ExecutionProposalAdmission` 对 Agent Profile 最大运行时间投影的最终消费。Profile、Capability inventory、模型输出 Schema、Proposal、digest、Project 状态和 Gateway 均保持不变。使用直接构造的已签名 Proposal 运行 Conformance 时，越界 Proposal 应从 typed rejection 退化为被接受。

`gateway_consumer.patch` 只撤去 `AgentGateway` 在 Provider submission 前对 `DelegationGrant` 与同一 Profile 上限的比较。Project Admission、Profile、Capability inventory、Schema 和 Grant 内容均保持不变。使用直接构造的越界 Grant 运行 Conformance 时，Provider Adapter 应重新被调用。两份 patch 分别证明语义准入和执行信任边界不可省略，都不替代正式 Provider 产品 target。

`project_budget_schema_consumer.patch` 只撤去动态 Agent 输出 Schema 对 Project 剩余 token 与 cost 的上界，保留 canonical Project budget、Ledger、Admission 和运行时间上界。应用后，模型输出类型会重新接受超过 Project 剩余额度的预算。

`project_budget_admission_consumer.patch` 只撤去 `ExecutionProposalAdmission` 对同一 Project 剩余额度的最终消费，保留 Schema、Ledger、Proposal 和后续执行预留。使用绕过 Schema 直接构造的 Proposal 时，越界 token/cost 授权会重新被接受。两份 Project budget patch 证明 Schema 负责降低错误生成率，而 Admission 仍是不可绕过的最终信任边界。

`project_budget_prompt_consumer.patch` 只撤去执行 Proposal 模型请求中的只读 `remaining_agent_budget` 投影，保留 Project Ledger、动态 Schema、Admission 和执行预留。产品消融必须同时应用三份 Project budget patch；否则模型仍能从 Context 读取目标上界，不能证明完整机制已被移除。

执行方式：

```powershell
git apply --check evals/ablations/investigation_delegation_budget_001/admission_consumer.patch
git apply evals/ablations/investigation_delegation_budget_001/admission_consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py::test_execution_admission_rejects_agent_time_budget_above_profile_limit
git apply -R evals/ablations/investigation_delegation_budget_001/admission_consumer.patch

git apply --check evals/ablations/investigation_delegation_budget_001/gateway_consumer.patch
git apply evals/ablations/investigation_delegation_budget_001/gateway_consumer.patch
uv run pytest -q tests/test_agent_gateway.py::test_agent_gateway_rejects_grant_above_registered_runtime_limit
git apply -R evals/ablations/investigation_delegation_budget_001/gateway_consumer.patch

git apply --check evals/ablations/investigation_delegation_budget_001/project_budget_schema_consumer.patch
git apply evals/ablations/investigation_delegation_budget_001/project_budget_schema_consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py::test_execution_output_schema_uses_registered_agent_runtime_limit
git apply -R evals/ablations/investigation_delegation_budget_001/project_budget_schema_consumer.patch

git apply --check evals/ablations/investigation_delegation_budget_001/project_budget_admission_consumer.patch
git apply evals/ablations/investigation_delegation_budget_001/project_budget_admission_consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py -k remaining_project_budget
git apply -R evals/ablations/investigation_delegation_budget_001/project_budget_admission_consumer.patch
```

Conformance 每次只应用一份 patch；应用后对应目标测试必须失败，反向应用后必须恢复通过。产品消融在独立代码状态中同时应用三份 Project budget patch，并保持输入、身份、模型、Provider、预算和观察窗口不变。`SHA256SUMS` 冻结 patch 内容身份。
