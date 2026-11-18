# ADR 0020：把来源支持纳入 Conversation 核验标准

## 背景与决定

旧 Verifier 将“应用端执行代码”当作“开发者负责权限验证”的依据。固定输入证明独立的来源支持标准能拦住该推断。用户授权先接入这项已成立的优化，再沿正式入口定位其他问题。[初次接入依据](../optimization/verification-source-support.md#56-将独立来源支持检查接入正式-verifier)

核验工具在适用任务中装配版本化的来源支持标准。Runtime 保留原用户要求的来源和绑定，系统标准在核验中独立体现。Verifier 判断每条语义状态，工具检查报告完整性、聚合并将反馈交回原循环。来源支持不足按适用标准拒稿。

2026-10-02，逐项文字交回改为 `criterion_id`。工具核对本次身份集合并从原输入恢复判据。现行核验输入、触发条件和版本按[核验专题](../topics/verification-and-completion.md)及 [ADR 0047](0047-user-goal-verification-context.md)维护。

## 依据、验证与退出

初版复用原内部工具、回执和修订循环，移除旧英文拼接提示。外部依据采用 RAGAS 对论断是否可从资料推出的判断，以及 OpenEvals 对额外前提的区分。[RAGAS Faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/) · [OpenEvals groundedness](https://github.com/langchain-ai/openevals/blob/cf22d62f030cdf607f8c02bd604cb6374511642f/python/openevals/prompts/rag/groundedness.py)

原有边界检查覆盖遗漏、重复、拒稿与重验；正式结果按原记录保留。验收项转录修复另有实际阶段证据。权限、判据绑定或反馈消费出现回归时，从受影响入口定位。[验收项转录问题](../optimization/completed/final-criterion-transcription.md)
