from __future__ import annotations

import json
import logging
from uuid import uuid4

from ..core.config import Settings
from ..core.llm_schemas import strict_json_schema_response
from ..core.llm_trace import log_llm_parse, traced_chat_completion
from ..core.models import MemoryItem
from ..core.prompts import get_prompt, render_prompt
from .step_projector import ExecutionStep

logger = logging.getLogger(__name__)


def _clip_reflection(item: MemoryItem, limit: int = 200) -> str:
    text = " ".join(str(item.content or item.title or "").split())
    if len(text) > limit:
        text = text[: limit - 1] + "..."
    return f"[conf={item.confidence:.2f}] {text}"

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 0.5

_REPLANNER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "action_type": {
                        "type": "string",
                        "enum": ["retrieve", "tool_call", "compose", "verify"],
                    },
                    "description": {"type": "string"},
                    "tool_name": {"type": ["string", "null"]},
                    "tool_input": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "expected_output": {"type": "string"},
                    "success_criteria": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "requires_confirmation": {"type": "boolean"},
                    "on_failure": {"type": "string", "enum": ["skip", "abort"]},
                },
                "required": [
                    "step_id",
                    "action_type",
                    "description",
                    "tool_name",
                    "tool_input",
                    "depends_on",
                    "expected_output",
                    "success_criteria",
                    "risk_level",
                    "requires_confirmation",
                    "on_failure",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": False,
}


class Replanner:
    """Generate revised execution steps when a step fails and retries are exhausted.

    Two-tier approach:
      Tier 1: Simple retry (handled by the graph step loop, this class is Tier 2).
      Tier 2: LLM replanning — prompt the LLM with the current plan state,
              the error, and intermediate results; parse a revised list of steps.
              Falls back to heuristic if LLM is unavailable or fails.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def replan(
        self,
        original_steps: list[ExecutionStep],
        failed_step: ExecutionStep,
        error: str,
        observations: dict[str, object],
        intent: str,
        reflections: list[MemoryItem] | None = None,
    ) -> list[ExecutionStep] | None:
        """Generate revised steps to replace remaining incomplete steps.

        Only replaces steps that are still in 'planned' or 'failed' status.
        Completed steps are preserved and prepended to the revised list.
        ``reflections`` are past-failure lessons for the same intent, injected
        into the LLM prompt as advisory context. Returns None if replanning is
        not possible.
        """
        remaining = [s for s in original_steps if s.status in ("planned", "failed")]
        if not remaining:
            logger.info("Replanner: no remaining steps to replan")
            return None

        llm_result = self._replan_with_llm(
            original_steps, failed_step, error, observations, intent, reflections
        )
        if llm_result is not None:
            return llm_result
        return self._replan_heuristic(original_steps, failed_step, error, intent)

    def _replan_with_llm(
        self,
        original_steps: list[ExecutionStep],
        failed_step: ExecutionStep,
        error: str,
        observations: dict[str, object],
        intent: str,
        reflections: list[MemoryItem] | None = None,
    ) -> list[ExecutionStep] | None:
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
        reflections_summary = "无"
        if reflections:
            reflections_summary = "\n".join(
                f"- {_clip_reflection(item)}" for item in reflections
            )

        system_prompt = get_prompt("replanner.system")
        prompt = render_prompt(
            "replanner.user",
            intent=intent,
            steps_summary=steps_summary,
            failed_step_id=failed_step.step_id,
            failed_action_type=failed_step.action_type,
            error=error,
            reflections=reflections_summary,
            obs_summary=obs_summary or "无",
        )
        model = self._settings.openai.small_model
        latency_ms = None
        try:
            llm_result = traced_chat_completion(
                self._settings.openai,
                prompt_name="replanner",
                prompt_version=system_prompt.version,
                messages=[
                    {"role": "system", "content": system_prompt.template},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=500,
                response_format=strict_json_schema_response(
                    "revise_steps",
                    _REPLANNER_RESPONSE_SCHEMA,
                ),
                metadata={"intent": intent, "failed_step_id": failed_step.step_id},
                upload_inputs_outputs=self._settings.langsmith.upload_inputs,
            )
            content = llm_result.content
            model = llm_result.model
            latency_ms = llm_result.latency_ms
            payload = json.loads(content)
            steps_data = payload.get("steps", [])
            if not isinstance(steps_data, list) or not steps_data:
                log_llm_parse(
                    prompt_name="replanner",
                    prompt_version=system_prompt.version,
                    model=model,
                    parse_ok=False,
                    parse_schema="ExecutionStep[]",
                    parse_error="steps missing or empty",
                    latency_ms=latency_ms,
                )
                return None

            valid_actions = {"retrieve", "tool_call", "compose", "verify"}
            revised: list[ExecutionStep] = []
            for item in steps_data:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action_type") or "")
                if action not in valid_actions:
                    continue
                tool = item.get("tool_name")
                tool_input = item.get("tool_input") or {}
                if not isinstance(tool_input, dict):
                    tool_input = {}
                depends_on = item.get("depends_on", [])
                if not isinstance(depends_on, list):
                    depends_on = []
                risk = str(item.get("risk_level", "low"))
                revised.append(ExecutionStep(
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
            log_llm_parse(
                prompt_name="replanner",
                prompt_version=system_prompt.version,
                model=model,
                parse_ok=bool(revised),
                parse_schema="ExecutionStep[]",
                parse_error="" if revised else "no valid revised steps",
                latency_ms=latency_ms,
            )
            return revised if revised else None
        except json.JSONDecodeError as exc:
            log_llm_parse(
                prompt_name="replanner",
                prompt_version=system_prompt.version,
                model=model,
                parse_ok=False,
                parse_schema="ExecutionStep[]",
                parse_error=str(exc),
                latency_ms=latency_ms,
            )
            logger.exception("Replanner LLM JSON decode failed, falling back to heuristic")
            return None
        except Exception:
            logger.exception("Replanner LLM call failed, falling back to heuristic")
            return None

    def _replan_heuristic(
        self,
        original_steps: list[ExecutionStep],
        failed_step: ExecutionStep,
        error: str,
        intent: str = "",
    ) -> list[ExecutionStep] | None:
        """Intent-aware heuristic fallback for replanning.

        Produces appropriate recovery steps based on the original intent
        rather than a generic salvage compose.
        """
        remaining = [s for s in original_steps if s.status == "planned"]

        # Intent-specific recovery strategies
        if intent == "delete_knowledge":
            filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
            salvage = ExecutionStep(
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
                salvage_compose = ExecutionStep(
                    step_id=f"re-{uuid4().hex[:6]}",
                    action_type="compose",
                    description="固化未完成：基于已提取的草稿内容生成部分摘要",
                    expected_output="总结本次固化尝试中已提取的内容",
                    on_failure="skip",
                )
                return filtered + [salvage_compose]
            return filtered or None

        if intent == "ask":
            filtered = [s for s in remaining if failed_step.step_id not in s.depends_on]
            if not any(s.action_type == "compose" for s in filtered):
                salvage = ExecutionStep(
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
            salvage = ExecutionStep(
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
            self._settings.openai.api_key
            and self._settings.openai.base_url
            and self._settings.openai.small_model
        )
