"""Artifact, canonical Conversation journal and isolated process boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from personal_agent.application.artifacts.models import ArtifactResourceItem
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from .models import (
    PythonBackendOutcome,
    PythonExecutionCommand,
    PythonExecutionFact,
    PythonExecutionReceipt,
    PythonInputContent,
    PythonJournalView,
)

if TYPE_CHECKING:
    from personal_agent.application.artifacts.service import StoredArtifact


class PythonArtifactPort(Protocol):
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


class PythonJournalPort(Protocol):
    def load_python_execution(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str
    ) -> PythonJournalView: ...
    def bind_python_command(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        command: PythonExecutionCommand,
    ) -> None: ...
    def record_python_execution(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        fact: PythonExecutionFact,
    ) -> None: ...
    def record_python_result(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        receipt: PythonExecutionReceipt,
    ) -> None: ...


class PythonExecutionPort(Protocol):
    def execute(
        self, command: PythonExecutionCommand, inputs: tuple[PythonInputContent, ...]
    ) -> PythonBackendOutcome: ...
    def reconcile(self, command: PythonExecutionCommand) -> PythonBackendOutcome: ...
    def cleanup(self, command: PythonExecutionCommand) -> None: ...
