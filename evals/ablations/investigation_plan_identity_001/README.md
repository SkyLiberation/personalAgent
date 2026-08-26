# INVESTIGATION-PLAN-IDENTITY-001 消融

`consumer.patch` 只移除三个结构化 Plan 输出类型对 canonical 唯一性函数的消费，保留
`plan_identity_uniqueness_error` 与 `PlanAdmission` 最终防线。它不改变 Prompt、Provider、业务
replan、Plan materialize、预算或状态机。

```powershell
git apply --check evals/ablations/investigation_plan_identity_001/consumer.patch
git apply evals/ablations/investigation_plan_identity_001/consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py -k "duplicate_identity_fields or revision_drafts_reject_duplicate"
git apply -R evals/ablations/investigation_plan_identity_001/consumer.patch
```

预期消融后四项输出边界断言失败；独立 Admission 断言仍通过。恢复 patch 后全部通过。该消融
证明 typed parse 消费点不可省略，不替代真实 Provider 产品 target。
