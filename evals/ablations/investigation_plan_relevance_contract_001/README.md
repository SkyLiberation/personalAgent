# INVESTIGATION-PLAN-RELEVANCE-CONTRACT-001 消融

`consumer.patch` 只把结构化计划输出边界从 canonical `RequirementRelevance` 恢复为旧的重复
`required|informational` 词表，不改变 Prompt、Provider、Plan materialize、Admission 或领域模型。

在候选代码上执行：

```powershell
git apply --check evals/ablations/investigation_plan_relevance_contract_001/consumer.patch
git apply evals/ablations/investigation_plan_relevance_contract_001/consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py::test_plan_draft_reuses_canonical_requirement_relevance_contract
git apply -R evals/ablations/investigation_plan_relevance_contract_001/consumer.patch
```

预期消融后测试因 `_PlanDraft` 拒绝 `supporting` 而失败；反向应用后恢复通过。该消融只证明
Provider Schema 必须消费 canonical 相关性类型，不替代真实 Provider 产品 target。
