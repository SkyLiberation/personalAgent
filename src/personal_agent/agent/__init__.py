"""Public agent API with lazy imports to keep module boundaries acyclic."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AgentRuntime": (".runtime", "AgentRuntime"),
    "AgentService": (".service", "AgentService"),
    "AnswerVerifier": ("personal_agent.application.verifier", "AnswerVerifier"),
    "AskResult": ("personal_agent.application.runtime_results", "AskResult"),
    "CaptureResult": ("personal_agent.application.runtime_results", "CaptureResult"),
    "DefaultIntentRouter": ("personal_agent.planning.router", "DefaultIntentRouter"),
    "DigestResult": ("personal_agent.application.runtime_results", "DigestResult"),
    "EntryResult": ("personal_agent.application.runtime_results", "EntryResult"),
    "ExecutionPlan": (".execution_models", "ExecutionPlan"),
    "ExecutionStep": (".execution_models", "ExecutionStep"),
    "Goal": ("personal_agent.planning.router", "Goal"),
    "IntentRouter": ("personal_agent.planning.router", "IntentRouter"),
    "ResetResult": ("personal_agent.application.runtime_results", "ResetResult"),
    "RouterDecision": ("personal_agent.planning.router", "RouterDecision"),
    "RouterOutput": ("personal_agent.planning.router", "RouterOutput"),
    "VerificationResult": ("personal_agent.application.verifier", "VerificationResult"),
    "WorkflowPlanner": ("personal_agent.planning.workflow_planner", "WorkflowPlanner"),
    "WorkflowTask": (".execution_models", "WorkflowTask"),
    "WORKFLOW_REGISTRY": ("personal_agent.planning.workflow", "WORKFLOW_REGISTRY"),
    "WorkflowConditionalEdge": ("personal_agent.planning.workflow", "WorkflowConditionalEdge"),
    "WorkflowRegistry": ("personal_agent.planning.workflow", "WorkflowRegistry"),
    "WorkflowSpec": ("personal_agent.planning.workflow", "WorkflowSpec"),
    "WorkflowStepSpec": ("personal_agent.planning.workflow", "WorkflowStepSpec"),
    "WorkflowSpecValidationResult": ("personal_agent.planning.workflow_validator", "WorkflowSpecValidationResult"),
    "WorkflowSpecValidator": ("personal_agent.planning.workflow_validator", "WorkflowSpecValidator"),
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
