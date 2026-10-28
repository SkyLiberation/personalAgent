"""Validate the submitted answer against actual experiment and Python execution facts."""

from __future__ import annotations

from collections.abc import Sequence

from personal_agent.application.python_execution.models import PythonInputManifest
from personal_agent.application.retrieval_experiment.delivery import (
    DeliveryGap, DeliveryIncomplete, RetrievalExperimentCompletionService,
)
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .citations import CitationBindingError, materialize_cited_draft
from .models import (
    ActionObservation, DecisionFeedback, InteractionInput, InteractionTrace,
    SubmittedFinal,
)
from .ports import InteractionArtifactPort

def pending_experiment_submission(inputs: Sequence[InteractionInput]) -> SubmittedFinal | None:
    """A new observation or repair feedback returns control to the model."""
    for item in reversed(inputs):
        if isinstance(item, SubmittedFinal):
            return item if item.final.disposition == "answer" else None
        if isinstance(item, (ActionObservation, DecisionFeedback)):
            return None
    return None


def experiment_submission(
    trace: InteractionTrace, *, prompts: PromptCatalog = DEFAULT_PROMPTS
) -> SubmittedFinal:
    submission = pending_experiment_submission(trace.inputs)
    if submission is None or not submission.final.message.strip():
        raise DeliveryIncomplete(DeliveryGap(code="fact_missing", message=prompts.render("conversation.experiment.submission_missing")))
    ref = submission.resource_ref
    if (ref.owner != trace.principal or ref.resource_type != "conversation_final"
            or ref.resource_id != f"{trace.interaction_run_ref}:final"):
        raise DeliveryIncomplete(DeliveryGap(code="identity_mismatch", message=prompts.render("conversation.experiment.submission_identity_mismatch")))
    try:
        materialize_cited_draft(submission.final.segments, trace.inputs, prompts=prompts)
    except CitationBindingError as exc:
        raise DeliveryIncomplete(DeliveryGap(
            code="identity_mismatch", message=prompts.render(
                "conversation.experiment.citations_unbound", error=str(exc)[:1500]
            ),
        )) from exc
    return submission


class ResearchExperimentCompletionUseCase:
    def __init__(self, *, experiments: RetrievalExperimentCompletionService,
                 artifacts: InteractionArtifactPort,
                 prompts: PromptCatalog = DEFAULT_PROMPTS) -> None:
        self.experiments = experiments
        self.artifacts = artifacts
        self.prompts = prompts

    @staticmethod
    def scope(trace: InteractionTrace) -> ExecutionScope:
        return ExecutionScope(principal=trace.principal, execution_id=trace.interaction_run_ref,
                              thread_id=trace.conversation_id, task_id="research_delivery")

    def validate(self, trace: InteractionTrace) -> None:
        submission = experiment_submission(trace, prompts=self.prompts)
        if trace.final_message is not None and trace.final_message != submission.final:
            raise DeliveryIncomplete(DeliveryGap(code="identity_mismatch", message=self.prompts.render("conversation.experiment.final_mismatch")))
        self._validate_python_results(trace)
        self.experiments.validate(execution_scope=self.scope(trace), records=trace.experiment_records)

    def _validate_python_results(self, trace: InteractionTrace) -> None:
        """核对原 Journal 的实际执行、输入身份与终态，不创建文件交付集合。"""
        for request in trace.accepted_tool_requests:
            if request.tool_name != "execute_python":
                continue
            scope = request.execution_scope
            if (
                scope.principal != trace.principal
                or scope.execution_id != trace.interaction_run_ref
                or scope.thread_id != trace.conversation_id
            ):
                raise PermissionError("Python接受请求不属于当前run及主体")
            command, execution, receipt = request.command, request.execution, request.receipt
            if command is None:
                if execution is not None or receipt is not None:
                    raise ValueError("Python实际执行缺少原冻结Command")
                continue
            if (
                command.execution_scope != scope
                or command.action_id != request.action_id
                or command.request_digest != request.request_digest
                or command.deployment_digest != trace.deployment_digest
            ):
                raise PermissionError("Python实际Command与原接受身份不同")
            if (
                execution is None
                or execution.status in {"dispatching", "unknown"}
                or receipt is None
                or receipt.status == "unknown"
            ):
                raise DeliveryIncomplete(DeliveryGap(
                    code="execution_unsettled", message=self.prompts.render("conversation.experiment.execution_unsettled"),
                ))
            if (
                receipt.action_id != command.action_id
                or receipt.command_digest != command.command_digest
                or receipt.program_ref != command.program.resource_ref
                or receipt.limits != command.limits
                or receipt.process_exit_code != execution.process_exit_code
                or receipt.elapsed_seconds != execution.elapsed_seconds
            ):
                raise ValueError("Python回执与冻结Command或实际进程事实不同")
            if (
                not execution.output_available
                or receipt.stdout_ref is None
                or receipt.stderr_ref is None
            ):
                raise DeliveryIncomplete(DeliveryGap(
                    code="artifact_missing", message=self.prompts.render("conversation.experiment.output_originals_missing"),
                ))
            if (
                receipt.status != execution.status
                and not (execution.status == "succeeded" and receipt.status == "invalid_output")
            ):
                raise ValueError("Python回执状态与实际进程终态不同")
            manifest = PythonInputManifest(
                command_digest=command.command_digest, program=command.program,
                inputs=command.inputs, image_id=command.image_id, limits=command.limits,
            )
            try:
                for identity in (command.program, *command.inputs):
                    item = self.artifacts.resource_item(
                        identity.resource_ref, principal=trace.principal, owner=trace.principal,
                    )
                    if (
                        item.resource_ref != identity.resource_ref
                        or item.content_digest != identity.content_digest
                        or item.size_bytes != identity.size_bytes
                    ):
                        raise ValueError("Python分析输入与实际冻结原件不同")
                snapshot = self.artifacts.read_snapshot(
                    receipt.input_manifest_ref, principal=trace.principal, owner=trace.principal,
                )
                for ref in (receipt.stdout_ref, receipt.stderr_ref):
                    self.artifacts.resource_item(ref, principal=trace.principal, owner=trace.principal)
            except FileNotFoundError as error:
                raise DeliveryIncomplete(DeliveryGap(
                    code="artifact_missing", message=self.prompts.render("conversation.experiment.input_originals_missing"),
                )) from error
            if PythonInputManifest.model_validate_json(snapshot.content) != manifest:
                raise ValueError("Python输入清单与实际冻结Command不同")
