from __future__ import annotations

import json
import logging
from uuid import uuid4

from openai import OpenAI

from ..core.config import Settings
from .planner import PlanStep

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 0.5


class Replanner:
    """Generate revised plan steps when a step fails and retries are exhausted.

    Two-tier approach:
      Tier 1: Simple retry (handled by PlanExecutor, this class is Tier 2).
      Tier 2: LLM replanning — prompt the LLM with the current plan state,
              the error, and intermediate results; parse a revised list of steps.
              Falls back to heuristic if LLM is unavailable or fails.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def replan(
        self,
        original_steps: list[PlanStep],
        failed_step: PlanStep,
        error: str,
        observations: dict[str, object],
        intent: str,
    ) -> list[PlanStep] | None:
        """Generate revised steps to replace remaining incomplete steps.

        Only replaces steps that are still in 'planned' or 'failed' status.
        Completed steps are preserved and prepended to the revised list.
        Returns None if replanning is not possible.
        """
        remaining = [s for s in original_steps if s.status in ("planned", "failed")]
        if not remaining:
            logger.info("Replanner: no remaining steps to replan")
            return None

        llm_result = self._replan_with_llm(original_steps, failed_step, error, observations, intent)
        if llm_result is not None:
            return llm_result
        return self._replan_heuristic(original_steps, failed_step, error, intent)

    def _replan_with_llm(
        self,
        original_steps: list[PlanStep],
        failed_step: PlanStep,
        error: str,
        observations: dict[str, object],
        intent: str,
    ) -> list[PlanStep] | None:
        if not self._llm_configured:
            return None

        steps_summary = "\n".join(
            f"- {s.step_id}: {s.action_type} {s.description} [{s.status}]"
            for s in original_steps
        )
        obs_summary = ""
        if observations:
            obs_summary = "\n".join(
                f"- {k}: {str(v)[:200]}" for k, v in observations.items()
            )

        prompt = (
            "你是一个任务重新规划器。当前计划中的某个步骤执行失败了，"
            "请根据失败信息和中间结果，生成替换剩余未完成步骤的新计划。"
            "已经完成的步骤不要重新执行。\n\n"
            f"原始意图: {intent}\n\n"
            f"原始计划步骤:\n{steps_summary}\n\n"
            f"失败步骤: {failed_step.step_id} ({failed_step.action_type})\n"
            f"失败原因: {error}\n\n"
            f"已完成的中间结果:\n{obs_summary or '无'}\n\n"
            "请返回一个 JSON 对象，包含 'steps' 数组。每个步骤包含：\n"
            "  step_id(新的短标识), action_type, description,\n"
            "  tool_name(nullable), tool_input(对象, nullable),\n"
            "  depends_on(前置步骤 step_id 数组),\n"
            "  expected_output, success_criteria,\n"
            "  risk_level(low/medium/high), requires_confirmation(bool),\n"
            "  on_failure(skip/abort)。\n"
            "不要包含已经完成的步骤。如果无法重新规划，返回 {\"steps\": []}。"
        )
        try:
            client = OpenAI(api_key=self._settings.openai_api_key, base_url=self._settings.openai_base_url)
            response = client.chat.completions.create(
                model=self._settings.openai_small_model,
                messages=[
                    {"role": "system", "content": "你是一个严谨的任务重新规划器，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            content = (response.choices[0].message.content or "").strip()
            payload = json.loads(content)
            steps_data = payload.get("steps", [])
            if not isinstance(steps_data, list) or not steps_data:
                return None

            valid_actions = {"retrieve", "tool_call", "compose", "verify"}
            revised: list[PlanStep] = []
            for item in steps_data:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action_type") or "")
                if action not in valid_actions:
                    continue
                tool = item.get("tool_name") or item.get("tool")
                tool_input = item.get("tool_input") or item.get("params") or {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                depends_on = item.get("depends_on", [])
                if not isinstance(depends_on, list):
                    depends_on = []
                risk = str(item.get("risk_level", "low"))
                revised.append(PlanStep(
                    step_id=str(item.get("step_id") or uuid4().hex[:8]),
                    action_type=action,
                    description=str(item.get("description") or f"重新执行: {failed_step.description}"),
                    tool_name=str(tool) if tool else None,
                    tool_input=tool_input,
                    depends_on=depends_on,
                    expected_output=str(item.get("expected_output") or ""),
                    success_criteria=str(item.get("success_criteria") or ""),
                    risk_level=risk if risk in ("low", "medium", "high") else "low",
                    requires_confirmation=bool(item.get("requires_confirmation", False)),
                    on_failure=str(item.get("on_failure") or "skip"),
                ))
            return revised if revised else None
        except Exception:
            logger.exception("Replanner LLM call failed, falling back to heuristic")
            return None

    def _replan_heuristic(
        self,
        original_steps: list[PlanStep],
        failed_step: PlanStep,
        error: str,
        intent: str = "",
    ) -> list[PlanStep] | None:
        """Intent-aware heuristic fallback for replanning.

        Produces appropriate recovery steps based on the original intent
        rather than a generic salvage compose.
        """
        remaining = [s for s in original_steps if s.status == "planned"]

        # Intent-specific recovery strategies
        if intent == "delete_knowledge":
            filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
            salvage = PlanStep(
                step_id=f"re-{uuid4().hex[:6]}",
                action_type="compose",
                description="删除未完成：汇总已检索到的候选笔记和失败原因",
                expected_output="说明哪些笔记可以删除，以及为何删除未能完成",
                on_failure="skip",
            )
            return filtered + [salvage]

        if intent == "solidify_conversation":
            filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
            has_tool = any(s.action_type == "tool_call" for s in filtered)
            if not has_tool:
                salvage_compose = PlanStep(
                    step_id=f"re-{uuid4().hex[:6]}",
                    action_type="compose",
                    description="固化未完成：基于已提取的候选结论生成部分摘要",
                    expected_output="总结本次固化尝试中已提取的内容",
                    on_failure="skip",
                )
                return filtered + [salvage_compose]
            return filtered or None

        if intent == "ask":
            filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
            if not any(s.action_type == "compose" for s in filtered):
                salvage = PlanStep(
                    step_id=f"re-{uuid4().hex[:6]}",
                    action_type="compose",
                    description="重新规划：基于可用检索结果生成部分回答",
                    expected_output="基于可用信息的部分回答",
                    on_failure="skip",
                )
                return filtered + [salvage]
            return filtered or None

        # Generic fallback for capture, summarize, and unknown intents
        filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
        needs_salvage = (
            failed_step.action_type in ("retrieve", "tool_call")
            and all(s.action_type != "compose" for s in filtered)
        )
        if needs_salvage and (filtered or failed_step.action_type == "retrieve"):
            salvage = PlanStep(
                step_id=f"re-{uuid4().hex[:6]}",
                action_type="compose",
                description="重新规划：根据已有信息生成回答",
                expected_output="基于可用信息的部分回答",
                on_failure="skip",
            )
            return filtered + [salvage]

        if filtered:
            return filtered
        return None

    @property
    def _llm_configured(self) -> bool:
        return bool(
            self._settings.openai_api_key
            and self._settings.openai_base_url
            and self._settings.openai_small_model
        )
