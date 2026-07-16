"""Policy-clamped capability acquisition manager."""

from personal_agent.capabilities.contracts.acquisition import (
    CapabilityAcquisitionOutcome,
    CapabilityAcquisitionProjection,
    CapabilityAcquisitionRequest,
)


class CapabilityAcquisitionManager:
    def submit(
        self,
        projection: CapabilityAcquisitionProjection,
        request: CapabilityAcquisitionRequest,
    ) -> CapabilityAcquisitionProjection:
        if request.method != "suggest":
            raise PermissionError("automatic capability mutation is not enabled by the default policy")
        requests = dict(projection.requests)
        requests[request.request_id] = request
        outcomes = dict(projection.outcomes)
        outcomes[request.request_id] = CapabilityAcquisitionOutcome(
            request_id=request.request_id,
            status="suggested",
            reason_codes=("user_approval_required",),
        )
        return projection.model_copy(update={"requests": requests, "outcomes": outcomes})

    def decide(
        self,
        projection: CapabilityAcquisitionProjection,
        request_id: str,
        *,
        approved: bool,
    ) -> CapabilityAcquisitionProjection:
        if request_id not in projection.requests:
            raise KeyError("unknown capability acquisition request")
        outcomes = dict(projection.outcomes)
        outcomes[request_id] = CapabilityAcquisitionOutcome(
            request_id=request_id,
            status="approved" if approved else "denied",
            reason_codes=("awaiting_environment_change",) if approved else ("user_denied",),
        )
        return projection.model_copy(update={"outcomes": outcomes})


__all__ = ["CapabilityAcquisitionManager"]

