"""Conversation answer, research, plan, and experiment feedback."""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "conversation.test_mode": PromptSpec(
        name="conversation.test_mode",
        version="v1-conversation-test-mode",
        template="本次是无人值守测试。缺少可由当前工具取得的材料时，调用对应工具继续。确实无法继续时，按当前工具声明提交限制或失败，并说明具体缺口。",
        owner="conversation",
    ),
    "conversation.clarification.description": PromptSpec(
        name="conversation.clarification.description",
        version="v1-clarification",
        template="向用户提出一个具体问题，等待其回复后继续。仅在现有信息和可用工具都无法取得关键输入，且必须由用户提供或决定时使用。question 是直接显示给用户的问题。单独调用本操作。",
        owner="conversation",
    ),
    "conversation.clarification.repair": PromptSpec(
        name="conversation.clarification.repair",
        version="v1-clarification",
        template="若确实需要用户补充信息，请单独调用 control_request_clarification，仅在 question 中填写一个非空问题。若现有工具能取得所需信息，请提交相应的工具调用。",
        owner="conversation",
    ),
    "conversation.answer.operation_unavailable": PromptSpec(
        name="conversation.answer.operation_unavailable",
        version="2026-10-27.v1",
        template="当前回答模块没有此操作。",
        owner="conversation",
    ),
    "conversation.answer.assistant_message_invalid": PromptSpec(
        name="conversation.answer.assistant_message_invalid",
        version="2026-10-27.v1",
        template="普通回答须来自没有工具调用的合法 assistant 消息。",
        owner="conversation",
    ),
    "conversation.answer.visible_body_missing": PromptSpec(
        name="conversation.answer.visible_body_missing",
        version="2026-10-27.v1",
        template="模型尚未返回非空可见正文；reasoning 不能作为回答。",
        owner="conversation",
    ),
    "conversation.answer.citation_repair": PromptSpec(
        name="conversation.answer.citation_repair",
        version="2026-11-15.v1",
        template="重新提交完整答复。需要引用时修正坐标或补读原文，可省略不必要且不可用的坐标。",
        owner="conversation",
    ),
    "conversation.plan.active_step_limit": PromptSpec(
        name="conversation.plan.active_step_limit",
        version="2026-10-27.v1",
        template="工作计划最多只能有一个 in_progress 工作项。",
        owner="conversation",
    ),
    "conversation.plan.active_step_repair": PromptSpec(
        name="conversation.plan.active_step_repair",
        version="2026-10-27.v1",
        template="只保留当前正在推进的一个活动项，其余待办项设为 pending。",
        owner="conversation",
    ),
    "conversation.plan.step_binding_repair": PromptSpec(
        name="conversation.plan.step_binding_repair",
        version="v2-list-control",
        template="用当前清单中的 step_id 更新已有项。新项省略 step_id。保持已绑定步骤的描述，或另加新步骤。",
        owner="conversation",
    ),
    "conversation.experiment.submission_missing": PromptSpec(
        name="conversation.experiment.submission_missing",
        version="2026-10-27.v1",
        template="完整报告尚未提交，或提交后仍有待处理反馈。",
        owner="conversation",
    ),
    "conversation.experiment.submission_identity_mismatch": PromptSpec(
        name="conversation.experiment.submission_identity_mismatch",
        version="2026-10-27.v1",
        template="报告提交不属于当前任务及主体。",
        owner="conversation",
    ),
    "conversation.experiment.final_mismatch": PromptSpec(
        name="conversation.experiment.final_mismatch",
        version="2026-10-27.v1",
        template="最终回答不是当前报告提交。",
        owner="conversation",
    ),
    "conversation.experiment.execution_unsettled": PromptSpec(
        name="conversation.experiment.execution_unsettled",
        version="2026-10-27.v1",
        template="Bash分析仍有尚未确认的执行，不能完整交付。",
        owner="conversation",
    ),
    "conversation.experiment.output_originals_missing": PromptSpec(
        name="conversation.experiment.output_originals_missing",
        version="2026-10-27.v1",
        template="Bash分析输出原件不可恢复，不能完整交付。",
        owner="conversation",
    ),
    "conversation.experiment.input_originals_missing": PromptSpec(
        name="conversation.experiment.input_originals_missing",
        version="2026-10-27.v1",
        template="Bash程序、输入或执行清单原件不存在。",
        owner="conversation",
    ),
    "conversation.answer.citation_feedback": PromptSpec(
        name="conversation.answer.citation_feedback",
        version="2026-10-27.v1",
        template="{error}\n完整提交及逐段引用见最新 submitted_final。",
        owner="conversation",
    ),
    "conversation.plan.step_binding_invalid": PromptSpec(
        name="conversation.plan.step_binding_invalid",
        version="v2-list-control",
        template="清单未更新。未知步骤 ID 为 {unknown}，改动了已绑定执行的步骤为 {changed_bound}。",
        owner="conversation",
    ),
    "conversation.plan.goal_binding_invalid": PromptSpec(
        name="conversation.plan.goal_binding_invalid", version="v1", owner="conversation",
        template="每个未完成的计划步骤须填写其服务的当前有效目标条目 ID。请按最新目标修订步骤。",
    ),
    "conversation.experiment.citations_unbound": PromptSpec(
        name="conversation.experiment.citations_unbound",
        version="2026-10-27.v1",
        template="报告引用未绑定实际来源：{error}",
        owner="conversation",
    ),
}
