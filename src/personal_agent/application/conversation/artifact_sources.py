"""Current readable references projected only from named committed facts."""

from collections.abc import Iterable
from personal_agent.application.bash_execution.models import BashExecutionReceipt
from personal_agent.kernel.contracts.resource import ResourceRef
from .goal_models import AnalysisGoalRef
from .models import (
    AcceptedArtifactToolRequest,
    AcceptedBashToolRequest,
    ActionObservation,
    ArtifactSourceInput,
    InteractionInput,
    InteractionTrace,
)
from .source_reading import OffloadedSource


def input_resource_refs(inputs: Iterable[InteractionInput]) -> tuple[ResourceRef, ...]:
    refs: list[ResourceRef] = []
    for item in inputs:
        if isinstance(item, ArtifactSourceInput):
            refs.append(item.resource.resource_ref)
        elif isinstance(item, ActionObservation) and item.status == "succeeded":
            retrieval = item.payload.get("retrieval")
            if isinstance(retrieval, dict) and "resource_ref" in retrieval:
                refs.append(OffloadedSource.model_validate(retrieval).resource_ref)
    return tuple(dict.fromkeys(refs))


def trace_goal_draft_refs(trace: InteractionTrace, *, base: AnalysisGoalRef | None = None) -> tuple[ResourceRef, ...]:
    refs = {op.draft_ref for op in trace.goal_operations
            if op.operation == "read" and op.draft_ref is not None and (base is None or op.base_goal_ref == base)}
    pending = [item.receipt for item in trace.accepted_tool_requests
               if isinstance(item, AcceptedArtifactToolRequest) and item.receipt is not None]
    while pending:
        added = [receipt for receipt in pending
                 if receipt.source_artifact_refs and all(ref in refs for ref in receipt.source_artifact_refs)]
        if not added:
            break
        refs.update(receipt.resource_ref for receipt in added)
        pending = [receipt for receipt in pending if receipt not in added]
    return tuple(sorted(refs, key=lambda ref: ref.resource_id))


def _bash_receipt_refs(receipt: BashExecutionReceipt) -> tuple[ResourceRef, ...]:
    return tuple(ref for ref in (
        receipt.program_ref, receipt.input_manifest_ref, receipt.stdout_ref, receipt.stderr_ref,
    ) if ref is not None)


def bash_audit_artifact_refs(sources: Iterable[InteractionTrace]) -> set[ResourceRef]:
    """Identify Bash bookkeeping even when the same file has an ArtifactSourceInput."""
    refs: set[ResourceRef] = set()
    for trace in sources:
        for accepted in trace.accepted_tool_requests:
            if isinstance(accepted, AcceptedBashToolRequest):
                if accepted.command is not None:
                    refs.add(accepted.command.program.resource_ref)
                if accepted.receipt is not None:
                    refs.update(_bash_receipt_refs(accepted.receipt))
    return refs


def tool_result_artifact_refs(trace: InteractionTrace) -> dict[str, tuple[ResourceRef, ...]]:
    """Files published by each tool's committed receipt."""
    refs = {}
    for accepted in trace.accepted_tool_requests:
        if accepted.tool_name == "write_artifact" and accepted.receipt is not None:
            refs[accepted.action_id] = (accepted.receipt.resource_ref,)
        elif accepted.tool_name == "bash" and accepted.receipt is not None:
            refs[accepted.action_id] = _bash_receipt_refs(accepted.receipt)
    for record in trace.experiment_records:
        receipt = record.receipt
        if receipt is not None:
            frozen_refs = (receipt.frozen_ref,) if receipt.frozen_ref is not None else ()
            refs[record.action_id] = (*receipt.result_refs, *receipt.diagnostic_refs, *frozen_refs)
    return refs


def trace_resource_refs(trace: InteractionTrace, *, include_goal_drafts: bool = True) -> tuple[ResourceRef, ...]:
    refs = list(input_resource_refs(trace.inputs))
    refs.extend(operation.draft_ref for operation in trace.goal_operations if operation.draft_ref is not None)
    refs.extend(trace.input_artifact_refs)
    if trace.history_compaction is not None:
        refs.extend((*trace.history_compaction.prior_snapshot_refs, trace.history_compaction.snapshot_ref))
    published = tool_result_artifact_refs(trace)
    for accepted in trace.accepted_tool_requests:
        if accepted.tool_name == "bash" and accepted.command is not None:
            refs.append(accepted.command.program.resource_ref)
        if accepted.tool_name != "retrieval_experiment":
            refs.extend(published.get(accepted.action_id, ()))
    for record in trace.experiment_records:
        refs.extend(published.get(record.action_id, ()))
    if not include_goal_drafts:
        drafts = set(trace_goal_draft_refs(trace))
        return tuple(dict.fromkeys(ref for ref in refs if ref not in drafts))
    return tuple(dict.fromkeys(refs))
