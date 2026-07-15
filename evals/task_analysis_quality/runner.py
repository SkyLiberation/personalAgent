"""Project task-analysis contracts into scoreable eval outputs."""

from __future__ import annotations

from .dataset import TaskAnalysisRunOutput


def run_output_from_analysis(analysis) -> TaskAnalysisRunOutput:
    return TaskAnalysisRunOutput(
        outcome=str(analysis.outcome),
        result_contracts=[goal.result_contract for goal in analysis.goals],
        raised_clarification=analysis.requires_clarification,
        missing_information=list(analysis.missing_information),
    )


def run_output_from_model_output(output) -> TaskAnalysisRunOutput:
    clarification = output.clarification
    return TaskAnalysisRunOutput(
        outcome=str(output.outcome),
        result_contracts=[goal.result_contract for goal in output.goals],
        raised_clarification=output.outcome == "clarify",
        missing_information=(
            list(clarification.missing_information) if clarification else []
        ),
    )
