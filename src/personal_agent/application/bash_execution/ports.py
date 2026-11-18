"""Artifact, canonical Conversation journal and isolated process boundaries."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from .models import (
    BashBackendOutcome,
    BashExecutionCommand,
    BashExecutionFact,
    BashExecutionReceipt,
    BashInputContent,
    BashJournalView,
)

if TYPE_CHECKING:
    from personal_agent.application.artifacts.service import StoredArtifact


class BashArtifactPort(Protocol):
    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[StoredArtifact, bytes]: ...
    def resource_item(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem: ...
    def publish_machine(
        self,
        *,
        execution_scope: ExecutionScope,
        producer_key: str,
        producer_ref: str,
        filename: str,
        content_type: str,
        file_bytes: bytes,
        kind: str,
        source_artifact_refs: tuple[ResourceRef, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef: ...


class BashJournalPort(Protocol):
    def load_bash_execution(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str
    ) -> BashJournalView: ...
    def bind_bash_command(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        command: BashExecutionCommand,
    ) -> None: ...
    def record_bash_execution(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        fact: BashExecutionFact,
    ) -> None: ...
    def record_bash_result(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        receipt: BashExecutionReceipt,
    ) -> None: ...


class BashExecutionPort(Protocol):
    def execute(
        self, command: BashExecutionCommand, inputs: tuple[BashInputContent, ...], *, run_deadline_at: datetime,
    ) -> BashBackendOutcome: ...
    def reconcile(self, command: BashExecutionCommand) -> BashBackendOutcome: ...
    def close_turn(self, scope: ExecutionScope) -> None: ...
