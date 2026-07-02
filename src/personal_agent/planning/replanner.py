from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_schemas import strict_json_schema_response
from personal_agent.kernel.models import MemoryItem
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.infra.structured_parse import parse_structured
from personal_agent.kernel.contracts.execution import ExecutionStep

if TYPE_CHECKING:
    from personal_agent.infra.structured_model import StructuredModelClient


class _RevisedStep(BaseModel):
    """Lenient view of one model-proposed revised step (coerced, then mapped)."""

    step_id: str = ""
    action_type: str = ""
    description: str = ""
    tool_name: str | None = None
    tool_input: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    expected_output: str = ""
    success_criteria: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    on_failure: str = "skip"

    @field_validator("tool_input", mode="before")
    @classmethod
    def _coerce_tool_input(cls, v: object) -> dict:
        return v if isinstance(v, dict) else {}

    @field_validator("depends_on", mode="before")
    @classmethod
    def _coerce_depends_on(cls, v: object) -> list:
        return v if isinstance(v, list) else []


class _RevisedPlan(BaseModel):
    steps: list[_RevisedStep] = Field(default_factory=list)

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
                        "enum": ["retrieve", "tool_call", "compose", "verify", "repair"],
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

    def __init__(
        self,
        settings: Settings,
        model_client: "StructuredModelClient | None" = None,
    ) -> None:
        self._settings = settings
        self._model_client = model_client

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
            from personal_agent.infra.structured_model import StructuredModelRequest

            response = self._model_client.generate(StructuredModelRequest(
                operation="replanner",
                version=system_prompt.version,
                messages=[
                    {"role": "system", "content": system_prompt.template},
                    {"role": "user", "content": prompt},
                ],
                output_type=BaseModel,
                temperature=0,
                max_tokens=500,
                kind="text",
                response_format=strict_json_schema_response(
                    "revise_steps",
                    _REPLANNER_RESPONSE_SCHEMA,
                ),
                metadata={"intent": intent, "failed_step_id": failed_step.step_id},
            ))
            content = response.content
            model = response.model
            latency_ms = response.latency_ms
            parsed = parse_structured(
                content,
                _RevisedPlan,
                operation="replanner",
                version=system_prompt.version,
                model_name=model,
                latency_ms=latency_ms,
            )
            if not parsed.ok:
                return None

            valid_actions = {"retrieve", "tool_call", "compose", "verify", "repair"}
            revised: list[ExecutionStep] = []
            for item in parsed.value.steps:
                if item.action_type not in valid_actions:
                    continue
                risk = item.risk_level if item.risk_level in ("low", "medium", "high") else "low"
                revised.append(ExecutionStep(
                    step_id=item.step_id or uuid4().hex[:8],
                    action_type=item.action_type,
                    description=item.description or f"重新执行: {failed_step.description}",
                    tool_name=item.tool_name or None,
                    tool_input=item.tool_input,
                    depends_on=item.depends_on,
                    expected_output=item.expected_output,
                    success_criteria=item.success_criteria,
                    risk_level=risk,
                    requires_confirmation=item.requires_confirmation,
                    on_failure=item.on_failure or "skip",
                ))
            return revised if revised else None
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
        return self._model_client is not None
