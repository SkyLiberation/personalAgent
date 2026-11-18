# ADR 0018：将语义验证绑定到可见执行证据

2026-09-01 决定。核验输入由 Runtime 从本次允许的材料确定性物化。现行目标与答复核验按各自职责选择证据。[核验专题](../topics/verification-and-completion.md) · [核验上下文决定](0047-user-goal-verification-context.md)

## 背景与决定

clean `HARNESS-003` 的主模型收到执行输入，Verifier 只收到草稿、判据和 URL，未能核对用于交付的精确事实。两次 `needs_revision` 后旧循环耗尽预算。`e8ab48f` 的密封失败归档为 `C:/pae/harness003-adr16-clean-target-e8ab48f-20260901/harness-003/target/20260901T080629.144958Z-33432-31cdf9b1/`。

当时决定从可见的已提交执行事实重建有界 `execution_evidence`，只消费成功且非 Verifier 的观察。Application 拥有可见性和物化，Verifier 判断语义，执行记录仍由原 Journal 拥有。复用已有物化与 workflow 入口，避免新持久状态和基于关键词的判定。

## 历史验证与退出

定向反事实覆盖作用域、成功状态过滤、有界投影和判据聚合。正常预算的 Product target 通过，先前独立轨迹证明 Verifier 实际消费了该投影，并暴露了汇总反馈缺省问题。两者按原运行身份解释。[历史评测盘点](../evals/02-current-case-inventory.md)

现行核验按具体任务消费有权限且可定位的证据。若再次发现关键事实遗漏或错误混入，先核对该次实际输入及可见性，按原责任边界验证。
