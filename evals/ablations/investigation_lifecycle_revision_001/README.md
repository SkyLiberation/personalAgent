# INVESTIGATION-LIFECYCLE-REVISION-001 消融

`consumer.patch` 只移除 `derive_interaction_intent()` 对未通过 grounding 的生命周期 Proposal 的一次修订消费，保留 Proposal Schema、Admission、typed feedback、Conversation 与 Project 两条生产路径。

应用后，`test_ungrounded_durable_lifecycle_is_revised_before_conversation_fallback` 必须从 `background_started` 退化为普通 Conversation 结果；反向应用后必须恢复通过。该检查属于 Runtime Conformance，只证明修订消费点命中预声明变量，不能替代真实 Provider 产品 target。

执行方式：

```powershell
git apply --check evals/ablations/investigation_lifecycle_revision_001/consumer.patch
git apply evals/ablations/investigation_lifecycle_revision_001/consumer.patch
uv run pytest -q tests/test_conversation_interaction.py::test_ungrounded_durable_lifecycle_is_revised_before_conversation_fallback
git apply --reverse evals/ablations/investigation_lifecycle_revision_001/consumer.patch
```
