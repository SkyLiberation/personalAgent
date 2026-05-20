from __future__ import annotations

import logging

from ..core.logging_utils import log_event
from ..core.models import EntryInput
from .entry_nodes import entry_target_node_for_intent
from .nodes import digest_node
from .planner import PlanStep
from .router import RouterDecision
from .runtime_results import DigestResult

logger = logging.getLogger(__name__)


class RuntimeEntryMixin:
    def execute_digest(self, user_id: str | None = None) -> DigestResult:
        normalized_user = user_id or self.settings.default_user
        logger.info("Generating digest user=%s", normalized_user)
        return DigestResult(
            message=digest_node(self.store, normalized_user),
            recent_notes=self.store.list_notes(normalized_user)[-5:],
            due_reviews=self.store.due_reviews(normalized_user),
        )

    def classify_intent(self, entry_input: EntryInput) -> RouterDecision:
        """Public wrapper for intent classification."""
        return self._intent_router.classify(entry_input)

    def plan_for_entry(
        self, entry_input: EntryInput
    ) -> tuple[RouterDecision, list[PlanStep], list[dict[str, object]]]:
        """Run session setup, intent routing, planning, and validation for an entry.

        Populates working memory with plan_steps dicts and returns the raw
        PlanStep objects for execution.  Returns ``(decision, validated_steps,
        plan_steps_dicts)``.
        """
        normalized_user = entry_input.user_id or self.settings.default_user
        normalized_session = entry_input.session_id or "default"
        self.memory.bind_session(normalized_user, normalized_session)
        self.memory.refresh_conversation_summary(normalized_user, normalized_session)
        decision = self._intent_router.classify(entry_input)
        self.memory.working.set_goal(
            f"入口任务[{decision.route}]: {entry_input.text[:60]}"
        )
        execution_path = (
            "orchestration_plan" if decision.requires_planning else "orchestration_branch"
        )
        log_event(
            logger,
            logging.INFO,
            "entry.route.decision",
            user_id=normalized_user,
            session_id=normalized_session,
            route=decision.route,
            confidence=decision.confidence,
            risk_level=decision.risk_level,
            requires_tools=decision.requires_tools,
            requires_retrieval=decision.requires_retrieval,
            requires_planning=decision.requires_planning,
            requires_confirmation=decision.requires_confirmation,
            candidate_tools=decision.candidate_tools,
            missing_information=decision.missing_information,
            execution_path=execution_path,
            target_node=(
                "plan_task"
                if decision.requires_planning
                else entry_target_node_for_intent(decision.route)
            ),
            reason=decision.user_visible_message,
        )

        if not decision.requires_planning:
            self.memory.working.plan_steps = []
            self.memory.working.execution_trace = []
            log_event(
                logger,
                logging.INFO,
                "entry.planned",
                user_id=normalized_user,
                session_id=normalized_session,
                route=decision.route,
                confidence=decision.confidence,
                risk_level=decision.risk_level,
                requires_confirmation=decision.requires_confirmation,
                plan_step_count=0,
                plan_steps=[],
            )
            return decision, [], []

        steps = self._planner.plan(decision.route, entry_input.text)
        validation = self._plan_validator.validate(steps, decision)
        if validation.blocking:
            logger.warning(
                "Plan validation blocked: %d issues, %d warnings. Issues: %s",
                len(validation.issues),
                len(validation.warnings),
                validation.issues,
            )
            if validation.corrected_steps:
                validated_steps = validation.corrected_steps
            else:
                logger.info(
                    "Replanning with heuristic due to validation blocking issues"
                )
                validated_steps = self._planner.fallback_plan(decision.route)
                revalidation = self._plan_validator.validate(validated_steps, decision)
                if revalidation.blocking:
                    logger.error(
                        "Heuristic plan also blocked: %s. Falling back to direct_answer.",
                        revalidation.issues,
                    )
                    decision = RouterDecision(
                        route="unknown",
                        confidence=0.1,
                        risk_level="low",
                        user_visible_message=f"计划校验失败: {'; '.join(revalidation.issues[:3])}",
                    )
                    validated_steps = self._planner.fallback_plan("unknown")
        else:
            validated_steps = validation.corrected_steps or steps
            if not validation.ok:
                logger.warning(
                    "Plan validation found %d non-blocking issues: %s",
                    len(validation.issues),
                    validation.warnings,
                )
        plan_steps = [
            {
                "step_id": s.step_id,
                "action_type": s.action_type,
                "description": s.description,
                "tool_name": s.tool_name,
                "tool_input": s.tool_input,
                "depends_on": s.depends_on,
                "expected_output": s.expected_output,
                "success_criteria": s.success_criteria,
                "risk_level": s.risk_level,
                "requires_confirmation": s.requires_confirmation,
                "on_failure": s.on_failure,
                "status": s.status,
                "retry_count": s.retry_count,
            }
            for s in validated_steps
        ]
        self.memory.working.plan_steps = plan_steps
        log_event(
            logger,
            logging.INFO,
            "entry.planned",
            user_id=normalized_user,
            session_id=normalized_session,
            route=decision.route,
            confidence=decision.confidence,
            risk_level=decision.risk_level,
            requires_confirmation=decision.requires_confirmation,
            plan_step_count=len(plan_steps),
            plan_steps=plan_steps,
        )
        return decision, validated_steps, plan_steps

    def _summarize_thread(self, messages_text: str, _user_id: str) -> str:
        if not messages_text.strip():
            return "没有可总结的消息内容。"
        prompt = (
            "你是个人知识库助手。请用自然中文总结以下群聊对话的核心要点。"
            "按主题分点列出讨论的关键事项、达成的结论和待办事项。"
            "保持简洁，每个要点一句话。如果对话内容较少或主题分散，直接概括即可。\n\n"
            f"群聊消息：\n{messages_text}"
        )
        generated = self._generate_answer(prompt)
        if generated:
            return generated
        return "暂时无法生成群聊总结，请稍后重试。"
