"""Read typed semantic verification receipts from committed interaction facts."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from personal_agent.capabilities.contracts.verification import (
    SemanticVerificationReceipt,
)

from .models import ActionObservation, InteractionInput


INTERACTION_VERIFICATION_CAPABILITY = "verify_interaction_draft"


def observed_receipts(
    inputs: Sequence[InteractionInput],
    *,
    capability_names: frozenset[str],
) -> tuple[SemanticVerificationReceipt, ...]:
    """Every receipt observed so far, in observation order.

    A payload that no longer satisfies the receipt contract is skipped rather
    than coerced: the tool owns receipt shape, and an unparseable observation is
    treated as no receipt at all so the turn keeps its ordinary paths.
    """
    receipts: list[SemanticVerificationReceipt] = []
    for item in inputs:
        if not isinstance(item, ActionObservation):
            continue
        if item.capability_id not in capability_names or item.status != "succeeded":
            continue
        payload = item.payload.get("data")
        if not isinstance(payload, dict):
            continue
        try:
            receipts.append(SemanticVerificationReceipt.model_validate(payload))
        except ValidationError:
            continue
    return tuple(receipts)


__all__ = ["INTERACTION_VERIFICATION_CAPABILITY", "observed_receipts"]
