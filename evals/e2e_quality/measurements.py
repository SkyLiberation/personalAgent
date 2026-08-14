"""Typed, non-production measurement facts for E2E archives."""

from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.application.conversation.models import InteractionTrace


class _MeasurementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BudgetProfile(_MeasurementModel):
    max_model_turns: int = Field(ge=1)
    max_tool_calls: int = Field(ge=0)
    max_agent_calls: int = Field(ge=0)
    max_total_tokens: int = Field(ge=1)
    max_concurrency: int = Field(ge=1)


class MeasurementProfile(_MeasurementModel):
    """The variables that must stay fixed within one measurement cohort."""

    profile_id: str = Field(min_length=1)
    runtime_implementation: str = Field(min_length=1)
    structured_provider: str = Field(min_length=1)
    structured_model: str = Field(min_length=1)
    prompt_revision: str = Field(min_length=1)
    capability_catalog_revision: str = Field(min_length=1)
    budget: BudgetProfile
    fixture_revision: str = Field(min_length=1)
    repetition: int = Field(ge=1)

    def cohort_key(self) -> tuple[object, ...]:
        return (
            self.runtime_implementation,
            self.structured_provider,
            self.structured_model,
            self.prompt_revision,
            self.capability_catalog_revision,
            self.budget,
            self.fixture_revision,
        )

    def cohort_digest(self) -> str:
        """Stable identity of comparable facts; labels and repetitions are excluded."""

        canonical = self.model_dump_json(
            exclude={"profile_id", "repetition"},
            exclude_none=False,
        )
        return sha256(canonical.encode("utf-8")).hexdigest()[:16]


class CaseMeasurement(_MeasurementModel):
    """Authoritative usage and recovery facts for one E2E case.

    Optional means unavailable, never zero. The reporter derives latency and
    outcome from pytest's summary rather than accepting duplicate facts here.
    """

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    model_calls: int | None = Field(default=None, ge=0)
    model_turns: int | None = Field(default=None, ge=0)
    tool_calls: int | None = Field(default=None, ge=0)
    agent_calls: int | None = Field(default=None, ge=0)
    recovery_duration_seconds: float | None = Field(default=None, ge=0)
    replay_new_side_effects: int | None = Field(default=None, ge=0)
    limited: bool | None = None

    @model_validator(mode="after")
    def validate_token_total(self) -> "CaseMeasurement":
        if (
            self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens is not None
            and self.input_tokens + self.output_tokens != self.total_tokens
        ):
            raise ValueError("input_tokens + output_tokens must equal total_tokens")
        return self


def measurement_from_interaction_trace(
    trace: InteractionTrace | dict[str, object],
) -> CaseMeasurement:
    """Copy only typed facts owned by the committed Conversation trace."""

    interaction = (
        trace
        if isinstance(trace, InteractionTrace)
        else InteractionTrace.model_validate(trace)
    )
    usage = interaction.usage
    return CaseMeasurement(
        input_tokens=usage.input_tokens if usage.provider_usage_complete else None,
        output_tokens=usage.output_tokens if usage.provider_usage_complete else None,
        total_tokens=(
            usage.total_tokens
            if usage.total_tokens > 0 or usage.model_turns == 0
            else None
        ),
        model_calls=usage.model_calls if usage.provider_usage_complete else None,
        model_turns=usage.model_turns,
        tool_calls=usage.tool_calls,
        agent_calls=usage.agent_calls,
        limited=(
            interaction.final_message.disposition == "limitation"
            if interaction.final_message is not None
            else None
        ),
    )


def measurement_from_trace_payload(
    payload: dict[str, object],
) -> CaseMeasurement | None:
    """Extract committed Conversation usage through typed boundary validation.

    A journey may archive setup/result/path evidence around the production trace.
    The extractor does not infer keys from a case id: it recursively finds only
    objects that validate as ``InteractionTrace``, keeps the latest revision of
    each run, and aggregates distinct interaction runs in the journey.
    """

    candidates: list[InteractionTrace] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if {
                "interaction_run_ref",
                "conversation_id",
                "principal",
                "messages",
                "usage",
            } <= value.keys():
                try:
                    candidates.append(InteractionTrace.model_validate(value))
                    return
                except ValueError:
                    pass
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(payload)
    if not candidates:
        return None
    latest: dict[str, InteractionTrace] = {}
    for trace in candidates:
        current = latest.get(trace.interaction_run_ref)
        if current is None or trace.revision > current.revision:
            latest[trace.interaction_run_ref] = trace
    measurements = [measurement_from_interaction_trace(trace) for trace in latest.values()]
    return CaseMeasurement(
        input_tokens=(
            sum(item.input_tokens or 0 for item in measurements)
            if all(item.input_tokens is not None for item in measurements)
            else None
        ),
        output_tokens=(
            sum(item.output_tokens or 0 for item in measurements)
            if all(item.output_tokens is not None for item in measurements)
            else None
        ),
        total_tokens=sum(item.total_tokens or 0 for item in measurements),
        model_calls=(
            sum(item.model_calls or 0 for item in measurements)
            if all(item.model_calls is not None for item in measurements)
            else None
        ),
        model_turns=sum(item.model_turns or 0 for item in measurements),
        tool_calls=sum(item.tool_calls or 0 for item in measurements),
        agent_calls=sum(item.agent_calls or 0 for item in measurements),
        limited=(
            any(item.limited is True for item in measurements)
            if any(item.limited is not None for item in measurements)
            else None
        ),
    )


__all__ = [
    "BudgetProfile",
    "CaseMeasurement",
    "MeasurementProfile",
    "measurement_from_interaction_trace",
    "measurement_from_trace_payload",
]
