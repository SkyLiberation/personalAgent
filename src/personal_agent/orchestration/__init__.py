"""Public agent API with lazy imports to keep module boundaries acyclic."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "AgentRuntime": (".runtime", "AgentRuntime"),
    "AgentService": (".service", "AgentService"),
    "AnswerVerifier": ("personal_agent.application.verifier", "AnswerVerifier"),
    "AskResult": ("personal_agent.application.runtime_results", "AskResult"),
    "CaptureResult": ("personal_agent.application.runtime_results", "CaptureResult"),
    "DefaultTaskAnalyzer": ("personal_agent.planning.task_analyzer", "DefaultTaskAnalyzer"),
    "DigestResult": ("personal_agent.application.runtime_results", "DigestResult"),
    "EntryResult": ("personal_agent.application.runtime_results", "EntryResult"),
    "ExecutableInvocation": ("personal_agent.kernel.contracts.execution", "ExecutableInvocation"),
    "Goal": ("personal_agent.planning.task_analyzer", "Goal"),
    "TaskAnalyzer": ("personal_agent.planning.task_analyzer", "TaskAnalyzer"),
    "ResetResult": ("personal_agent.application.runtime_results", "ResetResult"),
    "TaskAnalysis": ("personal_agent.planning.task_analyzer", "TaskAnalysis"),
    "TaskAnalysisOutput": ("personal_agent.planning.task_analyzer", "TaskAnalysisOutput"),
    "VerificationResult": ("personal_agent.application.verifier", "VerificationResult"),
    "PROCEDURE_CATALOG": ("personal_agent.planning.procedures", "PROCEDURE_CATALOG"),
    "ProcedureApplicabilityResolver": (
        "personal_agent.planning.procedures", "ProcedureApplicabilityResolver",
    ),
    "ProcedureRuntime": ("personal_agent.planning.procedures", "ProcedureRuntime"),
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
