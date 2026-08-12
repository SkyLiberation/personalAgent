"""Request-local materialization of committed Conversation execution inputs."""

from __future__ import annotations

from collections.abc import Iterable

from personal_agent.application.conversation.models import (
    ActionObservation,
    InteractionInput,
)

READ_ACTION_OUTPUT_CAPABILITY = "read_action_output"


def materialize_interaction_inputs(
    inputs: Iterable[InteractionInput],
) -> tuple[InteractionInput, ...]:
    """Replace artifact-backed excerpts with their exact re-read projection.

    The journal remains canonical and unchanged. Once an oversized observation
    has an application-owned resource reference, repeatedly sending its lossy
    head/tail excerpt adds input cost but cannot prove the omitted fact. The
    model needs the reference and omission metadata so it can choose an exact
    window through ``read_action_output``. Windows returned by that action are
    already bounded evidence and remain visible verbatim.
    """

    materialized: list[InteractionInput] = []
    for item in inputs:
        if not isinstance(item, ActionObservation):
            materialized.append(item)
            continue
        retrieval = item.payload.get("retrieval")
        if (
            item.capability_id == READ_ACTION_OUTPUT_CAPABILITY
            or not isinstance(retrieval, dict)
            or not isinstance(retrieval.get("resource_ref"), dict)
        ):
            materialized.append(item)
            continue
        compact_payload = {
            key: value
            for key, value in item.payload.items()
            if key in {"ok", "error", "error_kind", "status"}
        }
        compact_payload.update({
            "observation_excerpt_removed": True,
            "retrieval": retrieval,
        })
        materialized.append(item.model_copy(update={"payload": compact_payload}))
    return tuple(materialized)


__all__ = ["READ_ACTION_OUTPUT_CAPABILITY", "materialize_interaction_inputs"]
