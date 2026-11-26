"""Project visible interaction inputs without changing the underlying execution receipts."""

from collections.abc import Iterable, Mapping
import json

from pydantic import BaseModel, ConfigDict

from personal_agent.application.capture.web_source import WebSearchArgs, WebSearchOutput
from personal_agent.capabilities.contracts.verification_prompt import verification_judgment_text
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from .context_materialization import (
    FILE_READ_CAPABILITIES,
    GREP_FILE_CAPABILITY,
)
from .goal_models import GOAL_PENDING_ACTION_REJECTED
from .mcp_result_projection import project_mcp_result
from .models import ActionObservation, ArtifactSourceInput, DecisionFeedback, InteractionInput
from .skills import LOAD_SKILL_CAPABILITY, LoadedSkill
from .verification_admission import INTERACTION_VERIFICATION_CAPABILITY, observed_receipts
from personal_agent.application.artifacts.models import artifact_file_path, supports_text_snapshot
from personal_agent.application.bash_execution.models import BashToolResult
from .file_search import GrepFileArguments
class ProjectedInteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation: InteractionInput
    executed_query: WebSearchArgs | GrepFileArguments | None = None


def _separate_executed_query(
    item: InteractionInput,
) -> tuple[InteractionInput, WebSearchArgs | GrepFileArguments | None]:
    """Keep the executed search query beside the results."""
    if not isinstance(item, ActionObservation) or item.status != "succeeded":
        return item, None
    if item.capability_id == "web_search":
        output = WebSearchOutput.model_validate(item.payload["data"])
        query = WebSearchArgs(query=output.query, limit=output.limit)
        payload = {
            **item.payload,
            "data": output.model_dump(mode="json", exclude={"query", "limit"}),
        }
    elif item.capability_id == GREP_FILE_CAPABILITY:
        query = GrepFileArguments.model_validate(
            {key: item.payload[key] for key in GrepFileArguments.model_fields if key in item.payload}
        )
        payload = {
            key: value
            for key, value in item.payload.items()
            if key not in {"keyword", "regex", "result_offset"}
        }
    else:
        return item, None
    return item.model_copy(update={"payload": payload}), query


def project_interaction_inputs(inputs: Iterable[InteractionInput]) -> tuple[ProjectedInteractionInput, ...]:
    result = []
    for item in inputs:
        observation, query = _separate_executed_query(item)
        result.append(ProjectedInteractionInput(observation=observation, executed_query=query))
    return tuple(result)


_DIAGNOSTIC_LABELS = frozenset({"schema_enum", "schema_type", "schema_required", "schema_additionalProperties"})


def render_decision_feedback(
    feedback: DecisionFeedback, *, prompts: PromptCatalog, submitted_arguments: Mapping[str, object] | None = None,
) -> str:
    if feedback.reason_code == GOAL_PENDING_ACTION_REJECTED:
        return f"{feedback.message}\n{feedback.required_repair}"
    message = (prompts.render("conversation.context.feedback.action", action_name=feedback.action_name, message=feedback.message)
               if feedback.action_name else feedback.message)
    details = []
    for diagnostic in feedback.action_diagnostics:
        error_type = diagnostic.error_type
        key = diagnostic.field_path.removeprefix("$.")
        if error_type == "schema_enum" and submitted_arguments is not None and key in submitted_arguments:
            value = json.dumps(submitted_arguments[key], ensure_ascii=False)
            if len(value) <= 512:
                details.append(prompts.render("conversation.context.feedback.schema_enum_value",
                    path=diagnostic.field_path, value=value))
                continue
        problem = (prompts.get(f"conversation.context.feedback.{error_type}").template
                   if error_type in _DIAGNOSTIC_LABELS
                   else prompts.render("conversation.context.feedback.other", error_type=error_type))
        details.append(prompts.render("conversation.context.feedback.field", path=diagnostic.field_path, problem=problem))
    calls = [prompts.render("conversation.context.feedback.unpaired", action_name=call.name, call_id=call.call_id,
                            arguments=json.dumps(call.arguments, ensure_ascii=False))
             for call in feedback.rejected_action_invocations]
    repair = feedback.required_repair.strip()
    if (len(details) == len(feedback.action_diagnostics) == 1
            and feedback.action_diagnostics[0].error_type == "schema_enum"
            and repair == prompts.get("conversation.action_protocol_repair").template.strip()):
        repair = ""
    return "\n".join(part for part in (message, *details, *calls, repair) if part)


def _render_observation(
    observation: ActionObservation, item: ProjectedInteractionInput, *, prompts: PromptCatalog, native_tool_result: bool,
) -> str:
    data = observation.payload.get("data")
    if observation.capability_id == "bash" and isinstance(data, dict) and "receipt" in data:
        return BashToolResult.model_validate(data).shell_output()
    if observation.capability_id == LOAD_SKILL_CAPABILITY and observation.status == "succeeded" and native_tool_result:
        skill = LoadedSkill.model_validate(data)
        content = prompts.render("skills.loaded", skill_name=skill.name, instructions=skill.instructions)
        if observation.skill_scripts is not None:
            resources = prompts.render("skills.resource_base", path=observation.skill_scripts.resource_base)
            return f"{resources}\n\n{content}"
        return content
    if observation.status == "unknown":
        parts = [prompts.render("conversation.context.tool.outcome_unknown", tool_name=observation.capability_id)]
    else:
        status = prompts.get(f"conversation.context.state.{observation.status}").template
        parts = [prompts.render("conversation.context.tool.status", tool_name=observation.capability_id, status=status)]
    if not native_tool_result:
        parts.append(prompts.render("conversation.context.tool.call", action_id=observation.action_id))
    if observation.plan_step_id is not None:
        parts.append(prompts.render("conversation.context.tool.plan_step", step_id=observation.plan_step_id))
    if observation.capability_id == INTERACTION_VERIFICATION_CAPABILITY:
        receipts = observed_receipts((observation,), capability_names=frozenset({INTERACTION_VERIFICATION_CAPABILITY}))
        if receipts:
            parts.append(verification_judgment_text(receipts[0], prompts=prompts))
            return "\n".join(parts)

    payload = dict(project_mcp_result(observation.payload))
    payload.pop("ok", None)
    error = payload.pop("error", None)
    error_kind = payload.pop("error_kind", None)
    if error or error_kind:
        parts.append(prompts.render("conversation.context.tool.error", error=error or error_kind))
    preview = payload.pop("observation_excerpt", None)
    omitted = payload.pop("observation_excerpt_omitted_chars", None)
    payload.pop("observation_excerpt_removed", None)
    retrieval = payload.pop("retrieval", None)
    if isinstance(retrieval, dict):
        ref = retrieval.get("resource_ref")
        if isinstance(ref, dict) and ref.get("resource_id"):
            parts.append(prompts.render("conversation.context.tool.resource",
                file_path=artifact_file_path(ResourceRef.model_validate(ref))))
        if retrieval.get("total_lines") is not None:
            parts.append(prompts.render("conversation.context.tool.lines", lines=retrieval["total_lines"]))
        if omitted is not None:
            parts.append(prompts.render("conversation.context.tool.omitted", count=omitted))
        elif retrieval.get("omitted_chars"):
            parts.append(prompts.render("conversation.context.tool.legacy_omitted", count=retrieval["omitted_chars"]))
        if retrieval.get("unavailable_reason"):
            parts.append(retrieval["unavailable_reason"])
        if retrieval.get("read_more"):
            parts.append(retrieval["read_more"])
    elif omitted is not None:
        parts.append(prompts.render("conversation.context.tool.omitted", count=omitted))
    if observation.capability_id in FILE_READ_CAPABILITIES:
        # Authorization and version checks use the original typed receipt.
        payload.pop("content_digest", None)
        ref = payload.pop("resource_ref", None)
        if isinstance(ref, dict) and ref.get("resource_id"):
            parts.append(prompts.render("conversation.context.tool.source",
                file_path=artifact_file_path(ResourceRef.model_validate(ref))))
        total_lines = payload.pop("total_lines", None)
        if total_lines is not None:
            parts.append(prompts.render("conversation.context.tool.lines", lines=total_lines))
        explanation = payload.pop("explanation", "")
        if explanation:
            parts.append(explanation)
    if observation.capability_id == "write_artifact" and isinstance(data, dict):
        if ref := data.get("resource_ref"):
            parts.append(prompts.render("conversation.context.tool.resource",
                file_path=artifact_file_path(ResourceRef.model_validate(ref))))
    if payload:
        parts.append(prompts.render("conversation.context.tool.data", data=json.dumps(payload, ensure_ascii=False)))
    if item.executed_query is not None:
        parts.append(prompts.render("conversation.context.tool.query",
            query=item.executed_query.model_dump_json(exclude_none=True)))
    if isinstance(preview, str) and preview:
        parts.append(prompts.render("conversation.tool_result.preview", preview=preview))
    return "\n\n".join(parts)


def render_interaction_input(
    item: ProjectedInteractionInput, *, prompts: PromptCatalog = DEFAULT_PROMPTS, native_tool_result: bool = False,
) -> str:
    """Present decision facts and keep actual source lines and call data verbatim."""
    observation = item.observation
    if isinstance(observation, DecisionFeedback):
        return render_decision_feedback(observation, prompts=prompts)
    if isinstance(observation, ActionObservation):
        return _render_observation(observation, item, prompts=prompts, native_tool_result=native_tool_result)
    if isinstance(observation, ArtifactSourceInput):
        resource = observation.resource
        if supports_text_snapshot(resource.content_type):
            return prompts.render(
                "conversation.context.attachment.text", filename=resource.filename,
                size=resource.size_bytes, file_path=artifact_file_path(resource.resource_ref),
            )
        return prompts.render(
            "conversation.context.attachment.metadata", filename=resource.filename,
            size=resource.size_bytes,
        )
    return prompts.render("conversation.context.execution_data", data=item.model_dump_json(exclude_none=True))
