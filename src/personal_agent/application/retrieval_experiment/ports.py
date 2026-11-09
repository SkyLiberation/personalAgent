"""Application的Artifact、原Journal及外部实验执行边界。"""

from __future__ import annotations
from typing import TYPE_CHECKING, Protocol
from personal_agent.application.artifacts.models import (
    ArtifactResourceItem,
    ArtifactTextSnapshot,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope
from .models import (
    BackendOutcome,
    BoundArtifact,
    ExperimentActionReceipt,
    ExperimentCommand,
    ExperimentExecutionFact,
    ExperimentJournalView,
)

if TYPE_CHECKING:
    from personal_agent.application.artifacts.service import StoredArtifact


class ExperimentArtifactPort(Protocol):
    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[StoredArtifact, bytes]: ...
    def read_snapshot(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactTextSnapshot: ...
    def resource_item(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem: ...
    def read_limitations(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[str, ...]: ...
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


class ExperimentJournalPort(Protocol):
    def load(
        self, *, execution_scope: ExecutionScope, action_id: str, request_digest: str
    ) -> ExperimentJournalView: ...
    def bind_command(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        command: ExperimentCommand,
    ) -> None: ...
    def record_execution(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        fact: ExperimentExecutionFact,
    ) -> None: ...
    def record_result(
        self,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        receipt: ExperimentActionReceipt,
    ) -> None: ...


class ExperimentExecutionPort(Protocol):
    def execute(
        self, command: ExperimentCommand, inputs: tuple[BoundArtifact, ...]
    ) -> BackendOutcome: ...
    def reconcile(self, command: ExperimentCommand) -> BackendOutcome: ...
    def cleanup(self, command: ExperimentCommand) -> None: ...
