# ADR 0017：分离动作选择与最终交付

2026-08-31 决定。两步提交协议于 2026-10-24 被原生循环替换。现行模型协议见 [ADR 0045](0045-native-intent-loop-and-recorded-model-output.md)，答复入口见 [ADR 0055](0055-unified-conversation-answer.md)。

## 背景与历史决定

旧协议把携带文本的 `control_final_message` 与普通工具一起投影。模型可返回混合调用，Application 只能整批拒绝。归档 `20260831T041305.551156Z-34520-c8bf7b1d` 中，三个档案事实已恢复，混合响应后仍未交付。

当时以无载荷的 `prepare_final` 进入独占成文阶段，原生动作阶段保留可并行的普通调用。模型决定何时请求成文，Runtime 负责相位、预算和提交，Verifier 负责语义判断。新增瞬时相位，移除可混批的 Final action。拒稿可交回取证与修订循环，预算耗尽后的强制成文宽限在 2026-09-04 退出。

## 4. 为什么保留 `prepare_final`

当时普通动作需要原生工具调用，Final 需要 strict typed Schema。同次 `auto` 请求同时开放两者的两次真实样本均未执行工具就提前交付，其中一次编造本地证据。该显式控制只承担协议切换。后续 LongDS 完成计算却因第二次 JSON 成文失败而未交付，促成原生正文与工具调用进入同一循环。[原生循环失败依据](0045-native-intent-loop-and-recorded-model-output.md)

## 历史证据

- `HARNESS-003` target `20260831T053359.624686Z-9232-a8b902dd` 为 1/1，11 个模型回合、14 次调用、97,363 tokens。第二轮未重复读取原始档案，最终稿在修订后核验通过。
- 工具协议横切归档 `20260831T054359.245940Z-19676-8b59b6c6` 为整例 3/4、协议检查 4/4。E16 的 GitHub 401 保持原失败身份。独立协议因果对照未完成。
- 2026-10-23 的 LongDS 首轮暴露旧自动切换会在没有 `prepare_final` 时提前关闭工具。该自动入口先行删除，后继原生协议另有验证。[LongDS 阶段记录](../optimization/to_verify/verify_results/longds-analysis.md#11-l1-结果与首个因果切片)
