"""Public agent API with lazy imports to keep module boundaries acyclic."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AgentRuntime": (".runtime", "AgentRuntime"),
    "AgentService": (".service", "AgentService"),
    "AnswerVerifier": (".verifier", "AnswerVerifier"),
    "AskResult": (".runtime_results", "AskResult"),
    "CaptureResult": (".runtime_results", "CaptureResult"),
    "DefaultIntentRouter": (".router", "DefaultIntentRouter"),
    "DigestResult": (".runtime_results", "DigestResult"),
    "EntryResult": (".runtime_results", "EntryResult"),
    "ExecutionPlan": (".execution_models", "ExecutionPlan"),
    "ExecutionStep": (".execution_models", "ExecutionStep"),
    "Goal": (".router", "Goal"),
    "IntentRouter": (".router", "IntentRouter"),
    "ResetResult": (".runtime_results", "ResetResult"),
    "RouterDecision": (".router", "RouterDecision"),
    "RouterOutput": (".router", "RouterOutput"),
    "VerificationResult": (".verifier", "VerificationResult"),
    "WorkflowPlanner": (".workflow_planner", "WorkflowPlanner"),
    "WorkflowTask": (".execution_models", "WorkflowTask"),
    "WORKFLOW_REGISTRY": (".workflow", "WORKFLOW_REGISTRY"),
    "WorkflowConditionalEdge": (".workflow", "WorkflowConditionalEdge"),
    "WorkflowRegistry": (".workflow", "WorkflowRegistry"),
    "WorkflowSpec": (".workflow", "WorkflowSpec"),
    "WorkflowStepSpec": (".workflow", "WorkflowStepSpec"),
    "WorkflowSpecValidationResult": (".workflow_validator", "WorkflowSpecValidationResult"),
    "WorkflowSpecValidator": (".workflow_validator", "WorkflowSpecValidator"),
    "validate_registry_against_capabilities": (
        ".workflow_validator",
        "validate_registry_against_capabilities",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
