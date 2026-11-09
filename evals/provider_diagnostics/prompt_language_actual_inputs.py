"""Audit language resources against sealed task2 SDK inputs; no model invocation.

This is an actual-input materialization diagnostic, not a product outcome test.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from personal_agent.kernel.prompts import create_prompt_catalog
from evals.product_baselines.longds_materials import json_bytes, seal, verify_seal


def _business_schema(value):
    if isinstance(value, dict):
        return {key: (deepcopy(item) if key in {"const", "enum", "default", "examples"}
                      else _business_schema(item)) for key, item in value.items()
                if key not in {"description", "title"} or not isinstance(item, str)}
    if isinstance(value, list):
        return [_business_schema(item) for item in value]
    return value


def _current_construction(capture: Path, en) -> dict:
    """Consume a current real formal-entry SDK stage through the current builder."""
    from personal_agent.application.conversation.model_actions import build_model_action_definitions
    from personal_agent.application.conversation.models import EffectiveCapabilities, EffectiveToolCapability
    from personal_agent.application.conversation.research import research_operation_schema
    from personal_agent.application.conversation.answer_results import _CLAIM_SUBMISSION_TYPES, DirectAnswerResult
    from personal_agent.application.conversation.interaction_intent import InteractionIntentProposal
    from personal_agent.application.conversation.history_models import HistorySummary
    from personal_agent.application.conversation.models import InitialResearchEvidenceSelection, ResearchEvidenceSelection
    from personal_agent.capabilities.contracts.verification import SemanticVerificationReport, OverreachReport, VerificationCriterion
    from personal_agent.tools.interaction_verifier import _bound_report_type

    verify_seal(capture)
    paths = sorted((capture / "sdk").glob("*.candidate.request.json"))
    wire = next((json.loads(path.read_bytes()) for path in paths
                 if json.loads(path.read_bytes()).get("tools")), None)
    if wire is None:
        raise ValueError("Current formal-entry SDK action stage missing")
    zh = create_prompt_catalog("zh")
    suffix = zh.get("conversation.model_action.tool_description").template.split("{description}")[1]
    tools = []
    for item in wire["tools"]:
        function = item["function"]
        if not function["name"].startswith("tool_"):
            continue
        if not function["description"].endswith(suffix):
            raise ValueError("Actual owned action wrapper cannot be uniquely restored")
        tools.append(EffectiveToolCapability(name=function["name"][5:],
            description=function["description"][:-len(suffix)], input_schema=function["parameters"],
            strict=function.get("strict", False), read_only=True, planning_safe=True, safely_retryable=True))
    actions = build_model_action_definitions(EffectiveCapabilities(tools=tuple(tools)), prompts=en)
    for action in actions:
        en.localize_metadata(action.description)
        en.localize_schema(action.input_schema)
    trace = json.loads((capture / "trace.json").read_bytes())
    criteria = tuple(VerificationCriterion(criterion_id=f"r{index}", criterion=criterion)
                     for index, criterion in enumerate(trace["review_criteria"]["criteria"], start=1))
    bound = _bound_report_type(SemanticVerificationReport, criteria)
    schemas = {t.__name__: t.model_json_schema() for t in (
        InteractionIntentProposal, HistorySummary, InitialResearchEvidenceSelection,
        ResearchEvidenceSelection, OverreachReport, bound)}
    for operation in _CLAIM_SUBMISSION_TYPES:
        schema = research_operation_schema(operation, None, [], prompts=en)
        schemas[operation.__name__] = DirectAnswerResult._action(operation.__name__, schema, "").input_schema
    for schema in schemas.values():
        projected = en.localize_schema(schema)
        if _business_schema(projected) != _business_schema(schema):
            raise ValueError("Current stage schema validation structure changed")
    # Add the review's valid constant-value counterfactual to the same actual tool schema.
    literal = {"title": "知识归属用户 ID。", "description": "原始用户资料，不是Schema说明。"}
    schema = deepcopy(tools[0].input_schema)
    schema["const"] = literal
    schema["examples"] = [literal]
    projected = en.localize_schema(schema)
    if projected["const"] != literal or projected["examples"] != [literal]:
        raise ValueError("Schema localization modified literal user values")
    return {"source": str(capture), "source_checksums_sha256": sha256((capture / "checksums.json").read_bytes()).hexdigest(),
            "actual_tools_reconstructed": len(tools), "current_actions_materialized": len(actions),
            "current_stage_schemas": list(schemas), "literal_constraint_counterfactual_preserved": True,
            "limitations": "Current real SDK definitions reconstructed at the input boundary; no tool or model execution."}


def run(output: Path, *, captures: list[Path], inventory: Path, current_capture: Path) -> None:
    zh = create_prompt_catalog("zh")
    en = create_prompt_catalog("en")
    baseline = json.loads(inventory.read_bytes())
    # The inventory records exact pre-change production resources, not expected answers.
    prompts = baseline.get("prompts", baseline)
    if isinstance(prompts, list):
        prompts = {row["name"]: row for row in prompts}
    preserved = 0
    for name, original in prompts.items():
        if not isinstance(original, dict) or "template" not in original:
            continue
        actual = zh.get(name)
        if actual.template != original["template"] or actual.version != original["version"]:
            raise ValueError(f"Chinese production resource changed: {name}")
        preserved += 1
    if preserved != 45:
        raise ValueError("The pre-change 45-resource inventory is incomplete")
    inputs = []
    sdk_count = schema_count = 0
    for capture in captures:
        verify_seal(capture)
        for path in sorted((capture / "sdk").glob("*.http.request.json")):
            wire = json.loads(path.read_bytes())
            projected = deepcopy(wire)
            for tool in projected.get("tools", []):
                function = tool["function"]
                original = deepcopy(function["parameters"])
                function["description"] = en.localize_metadata(function.get("description", ""))
                function["parameters"] = en.localize_schema(original)
                if _business_schema(original) != _business_schema(function["parameters"]):
                    raise ValueError("Schema localization changed validation structure")
                if zh.localize_schema(original) != original:
                    raise ValueError("Chinese schema projection changed")
                schema_count += 1
            response_format = wire.get("response_format")
            if response_format is not None:
                if response_format.get("type") == "json_schema":
                    projected["response_format"]["json_schema"]["schema"] = en.localize_schema(response_format["json_schema"]["schema"])
                if _business_schema(response_format) != _business_schema(projected["response_format"]):
                    raise ValueError("Response schema localization changed validation structure")
                schema_count += 1
            if projected["messages"] != wire["messages"]:
                raise ValueError("Schema projection modified original messages or model history")
            inputs.append({"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                           "projected_sha256": sha256(json_bytes(projected)).hexdigest()})
            sdk_count += 1
    if not sdk_count or not schema_count:
        raise ValueError("No actual SDK schema inputs reached")
    # Independent immutable catalogs remain selected after alternating all actual inputs.
    if zh.language != "zh" or en.language != "en" or create_prompt_catalog("zh").prompts != zh.prompts:
        raise ValueError("Language catalog isolation failed")
    try:
        create_prompt_catalog("invalid-language")
    except ValueError:
        rejected = True
    else:
        raise ValueError("Unknown language was not rejected")
    current = _current_construction(current_capture, en)
    output.mkdir(parents=True, exist_ok=False)
    (output / "runner-source.py").write_bytes(Path(__file__).read_bytes())
    (output / "inputs.json").write_bytes(json_bytes(inputs))
    report = {"evidence_class": "offline_actual_sdk_materialization", "model_calls": 0,
              "actual_sdk_requests": sdk_count, "schema_projections": schema_count,
              "preserved_original_prompts": preserved, "registered_prompts": len(zh.prompts),
              "english_prompts": len(en.prompts), "metadata_translations": len(en.metadata_translations),
              "unknown_language_rejected": rejected, "original_messages_preserved": True,
              "schema_business_structure_preserved": True,
              "current_construction": current,
              "limitations": "Historical messages stay raw; this projection audit does not prove English task outcomes."}
    (output / "report.json").write_bytes(json_bytes(report))
    seal(output)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--capture", type=Path, action="append", required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--current-capture", type=Path, required=True)
    args = parser.parse_args()
    run(args.output, captures=args.capture, inventory=args.inventory, current_capture=args.current_capture)
