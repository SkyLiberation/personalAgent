"""Conversation execution facts and their durable snapshot projection."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .errors import ConversationOperationNotFound
from .models import (
    ActionObservation,
    ConversationWorkingPlan,
    InteractionTrace,
    ProjectReference,
)


logger = logging.getLogger(__name__)


class InMemoryInteractionJournal:
    """Append-only execution facts used to rebuild transient interaction context."""

    def __init__(self) -> None:
        self._traces: dict[str, InteractionTrace] = {}
        self._lock = RLock()

    def put(self, trace: InteractionTrace) -> None:
        with self._lock:
            self._traces[trace.interaction_run_ref] = trace

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        with self._lock:
            return self._traces.get(interaction_run_ref)

    def project_references(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> tuple[ProjectReference, ...]:
        with self._lock:
            traces = tuple(self._traces.values())
        by_id = {
            trace.project_reference.project_id: trace.project_reference
            for trace in traces
            if trace.conversation_id == conversation_id
            and trace.principal == principal
            and trace.project_reference is not None
        }
        return tuple(by_id[key] for key in sorted(by_id))

    def working_plan(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> ConversationWorkingPlan | None:
        with self._lock:
            traces = tuple(self._traces.values())
        candidates = [
            trace
            for trace in traces
            if trace.conversation_id == conversation_id
            and trace.principal == principal
            and trace.working_plan is not None
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda trace: trace.working_plan.revision)
        return latest.working_plan

    def working_plan_observations(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> tuple[ActionObservation, ...]:
        """Project committed execution facts for the current foreground plan."""

        with self._lock:
            traces = tuple(self._traces.values())
        candidates = sorted(
            (
                trace
                for trace in traces
                if trace.conversation_id == conversation_id
                and trace.principal == principal
                and trace.working_plan is not None
                and trace.working_plan.plan_id == working_plan.plan_id
            ),
            key=lambda trace: (
                trace.working_plan.revision,
                trace.interaction_run_ref,
            ),
        )
        observations_by_step: dict[str, list[ActionObservation]] = {
            step.step_id: [] for step in working_plan.steps
        }
        seen: set[tuple[str, str]] = set()
        for trace in candidates:
            for item in trace.inputs:
                key = (item.capability_id, item.action_id) if isinstance(
                    item, ActionObservation
                ) else None
                if (
                    key is None
                    or key in seen
                    or item.status != "succeeded"
                    or item.plan_step_id not in observations_by_step
                ):
                    continue
                seen.add(key)
                observations_by_step[item.plan_step_id].append(item)
        return tuple(
            observation
            for step in working_plan.steps
            for observation in observations_by_step[step.step_id]
        )


class FileInteractionJournal(InMemoryInteractionJournal):
    """Durable append-only snapshots of committed interaction facts."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, trace: InteractionTrace) -> None:
        super().put(trace)
        run_dir = self._root / trace.interaction_run_ref
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / f"{trace.revision:04d}.json"
        if target.exists():
            return
        temporary = run_dir / f".{trace.revision:04d}.{uuid4().hex}.tmp"
        temporary.write_text(trace.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        cached = super().get(interaction_run_ref)
        if cached is not None:
            return cached
        run_dir = self._root / interaction_run_ref
        snapshots = sorted(run_dir.glob("*.json")) if run_dir.exists() else []
        if not snapshots:
            return None
        try:
            trace = InteractionTrace.model_validate_json(
                snapshots[-1].read_text(encoding="utf-8")
            )
        except ValidationError as error:
            missing_principal = any(
                tuple(item.get("loc", ())) == ("principal",)
                and item.get("type") == "missing"
                for item in error.errors()
            )
            if not missing_principal:
                raise
            logger.warning(
                "interaction.journal.unscoped | %s",
                json.dumps(
                    {"run_id": interaction_run_ref, "disposition": "quarantined"},
                    sort_keys=True,
                ),
            )
            raise ConversationOperationNotFound(
                "interaction run has no trustworthy owner scope"
            ) from error
        super().put(trace)
        return trace

    def project_references(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> tuple[ProjectReference, ...]:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().project_references(conversation_id, principal)

    def working_plan(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
    ) -> ConversationWorkingPlan | None:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().working_plan(conversation_id, principal)

    def working_plan_observations(
        self,
        conversation_id: str,
        principal: AuthenticatedPrincipal,
        working_plan: ConversationWorkingPlan,
    ) -> tuple[ActionObservation, ...]:
        for run_dir in sorted(path for path in self._root.iterdir() if path.is_dir()):
            self.get(run_dir.name)
        return super().working_plan_observations(
            conversation_id,
            principal,
            working_plan,
        )


__all__ = [
    "ConversationOperationNotFound",
    "FileInteractionJournal",
    "InMemoryInteractionJournal",
]
