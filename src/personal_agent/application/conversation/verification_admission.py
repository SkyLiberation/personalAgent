"""Reading semantic verification receipts out of committed interaction facts.

One concern remains here. The runtime owns when verification happens and what
criteria it uses (see :mod:`review_admission`), so there is nothing left to admit
about a model's verification behavior -- the model can no longer see the verifier,
let alone call it, skip it, or choose its criteria. What is still needed is a
typed read of what verification actually produced.

The function is pure, so a receipt-shaped payload can be tested without a service
instance.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from personal_agent.capabilities.contracts.verification import (
    SemanticVerificationReceipt,
)

from .models import ActionObservation, InteractionInput


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


__all__ = ["observed_receipts"]
