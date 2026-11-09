from personal_agent.kernel.prompt_registry import PromptSpec

PROMPTS = {
    "conversation.history.source_invalid": PromptSpec(name="conversation.history.source_invalid", version="2026-10-27.v1", template="历史摘要的原始来源或主体已失效。", owner="conversation"),
    "conversation.history.snapshot_digest_invalid": PromptSpec(name="conversation.history.snapshot_digest_invalid", version="2026-10-27.v1", template="历史原件快照摘要不一致。", owner="conversation"),
    "conversation.history.coverage_invalid": PromptSpec(name="conversation.history.coverage_invalid", version="2026-10-27.v1", template="历史摘要覆盖无效或重复条目。", owner="conversation"),
    "conversation.history.decision_missing": PromptSpec(name="conversation.history.decision_missing", version="2026-10-27.v1", template="历史摘要引用不存在的模型决策。", owner="conversation"),
    "conversation.history.no_closed_progress": PromptSpec(name="conversation.history.no_closed_progress", version="2026-10-27.v1", template="没有新的闭合旧历史可压缩，已停止无进展的重复压缩。", owner="conversation"),
    "conversation.history.export_incomplete": PromptSpec(name="conversation.history.export_incomplete", version="2026-10-27.v1", template="历史原件导出不完整，不能让原历史退出输入。", owner="conversation"),
    "conversation.history.summary_incomplete": PromptSpec(name="conversation.history.summary_incomplete", version="2026-10-27.v1", template="历史摘要为空或被截断，未激活。", owner="conversation"),
    "conversation.history.source_changed": PromptSpec(name="conversation.history.source_changed", version="2026-10-27.v1", template="摘要期间历史或检查点已变化，费用保留但不覆盖新状态。", owner="conversation"),
    "conversation.history.activation_conflict": PromptSpec(name="conversation.history.activation_conflict", version="2026-10-27.v1", template="历史摘要激活时 Journal revision 冲突。", owner="conversation"),
    "conversation.history.no_safe_range": PromptSpec(name="conversation.history.no_safe_range", version="2026-10-27.v1", template="历史摘要没有安全覆盖区间。", owner="conversation"),
    "conversation.intent.source_missing": PromptSpec(name="conversation.intent.source_missing", version="2026-10-27.v1", template="<缺少用户来源>", owner="conversation"),
    "conversation.intent.deadline_exceeded": PromptSpec(name="conversation.intent.deadline_exceeded", version="2026-10-27.v1", template="本次实验运行时限已到；已保留实际成果，本次研究未完成。", owner="conversation"),
    "conversation.intent.tokens_exhausted": PromptSpec(name="conversation.intent.tokens_exhausted", version="2026-10-27.v1", template="本次研究的已知模型消费达到额度，已停止新增付费调用。", owner="conversation"),
    "conversation.knowledge_save.awaiting_confirmation": PromptSpec(name="conversation.knowledge_save.awaiting_confirmation", version="2026-10-27.v1", template="请确认是否保存所选内容。确认前不会写入长期知识。", owner="conversation"),
    "conversation.knowledge_save.rejected": PromptSpec(name="conversation.knowledge_save.rejected", version="2026-10-27.v1", template="已取消保存，未写入长期知识。", owner="conversation"),
    "conversation.knowledge_save.executed": PromptSpec(name="conversation.knowledge_save.executed", version="2026-10-27.v1", template="已保存所选内容。", owner="conversation"),
}
