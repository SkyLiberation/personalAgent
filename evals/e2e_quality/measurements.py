"""Typed, non-production measurement facts for E2E archives."""

from __future__ import annotations

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
            self.profile_id,
            self.runtime_implementation,
            self.structured_provider,
            self.structured_model,
            self.prompt_revision,
            self.capability_catalog_revision,
            self.budget,
            self.fixture_revision,
        )


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
        total_tokens=(
            usage.total_tokens
            if usage.total_tokens > 0 or usage.model_turns == 0
            else None
        ),
        model_turns=usage.model_turns,
        tool_calls=usage.tool_calls,
        agent_calls=usage.agent_calls,
    )


__all__ = [
    "BudgetProfile",
    "CaseMeasurement",
    "MeasurementProfile",
    "measurement_from_interaction_trace",
]
