"""Current readable references projected only from named committed facts."""

from collections.abc import Iterable
from personal_agent.kernel.contracts.resource import ResourceRef
from .models import (
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


def trace_resource_refs(trace: InteractionTrace) -> tuple[ResourceRef, ...]:
    refs = list(input_resource_refs(trace.inputs))
    refs.extend(trace.input_artifact_refs)
    if trace.history_compaction is not None:
        refs.append(trace.history_compaction.snapshot_ref)
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
    return tuple(dict.fromkeys(refs))
