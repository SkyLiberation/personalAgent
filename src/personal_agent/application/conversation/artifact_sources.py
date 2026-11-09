"""Current readable references projected only from named committed facts."""

from collections.abc import Iterable
from personal_agent.kernel.contracts.resource import ResourceRef
from .goal_models import AnalysisGoalRef
from .models import (
    AcceptedArtifactToolRequest,
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


def trace_resource_refs(trace: InteractionTrace, *, include_goal_drafts: bool = True) -> tuple[ResourceRef, ...]:
    refs = list(input_resource_refs(trace.inputs))
    refs.extend(operation.draft_ref for operation in trace.goal_operations if operation.draft_ref is not None)
    refs.extend(trace.input_artifact_refs)
    if trace.history_compaction is not None:
        refs.extend((*trace.history_compaction.prior_snapshot_refs, trace.history_compaction.snapshot_ref))
    for accepted in trace.accepted_tool_requests:
        if accepted.tool_name == "write_artifact" and accepted.receipt is not None:
            refs.append(accepted.receipt.resource_ref)
        elif accepted.tool_name == "execute_python":
            if accepted.command is not None:
                refs.append(accepted.command.program.resource_ref)
            if accepted.receipt is not None:
                refs.extend((accepted.receipt.program_ref, accepted.receipt.input_manifest_ref))
                if accepted.receipt.stdout_ref is not None:
                    refs.append(accepted.receipt.stdout_ref)
                if accepted.receipt.stderr_ref is not None:
                    refs.append(accepted.receipt.stderr_ref)
    for record in trace.experiment_records:
        if record.receipt is None:
            continue
        refs.extend(record.receipt.result_refs)
        refs.extend(record.receipt.diagnostic_refs)
        if record.receipt.frozen_ref is not None:
            refs.append(record.receipt.frozen_ref)
    if not include_goal_drafts:
        drafts = set(trace_goal_draft_refs(trace))
        return tuple(dict.fromkeys(ref for ref in refs if ref not in drafts))
    return tuple(dict.fromkeys(refs))
