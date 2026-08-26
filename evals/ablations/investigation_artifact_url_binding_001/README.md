# INVESTIGATION-ARTIFACT-URL-BINDING-001 消融

`consumer.patch` 只撤销 admitted EvidenceMaterial 正文 URL 的候选派生，并恢复
`capture_url` 在候选集合为空时跳过 Admission 的旧条件。它不改变 Artifact、Plan、
Verifier、Tool Schema、Provider、URL 正则、candidate ID 绑定或用户输入。

```powershell
git apply --check evals/ablations/investigation_artifact_url_binding_001/consumer.patch
git apply evals/ablations/investigation_artifact_url_binding_001/consumer.patch
uv run pytest -q tests/test_investigation_project_model_ports.py -k "agent_artifact_text_urls or capture_without_observed_url"
git apply -R evals/ablations/investigation_artifact_url_binding_001/consumer.patch
```

预期消融后两项断言失败：Agent report URL 不再成为候选，空参数再次通过 Admission。
恢复 patch 后两项通过。该消融证明 URL 候选绑定边界不可省略，不替代真实 Provider
Artifact、后续读取和 SubGoalOutcome target。
