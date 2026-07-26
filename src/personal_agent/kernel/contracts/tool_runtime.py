"""Tool-execution boundary contracts: audit sink, idempotency, gateway context.

Pure structural types (Protocols + a frozen dataclass) shared between the infra
layer (which implements ``ToolAuditSink``/``IdempotencyStore`` over Postgres) and
the governance layer (``ToolGateway``, which depends on them). Kept in the kernel
so infra never has to import the tools/governance packages to satisfy a type.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from personal_agent.kernel.contracts.tool import ToolInvocationEvent


class ToolAuditSink(Protocol):
    def record(self, event: ToolInvocationEvent) -> None:
        """Persist or forward a normalized tool invocation event."""


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool:
        """Return True if this idempotency key was already committed."""

    def reserve(self, key: str, *, context: "ToolGatewayContext", tool_name: str) -> bool:
        """Atomically reserve a key before executing a side effect."""

    def get_receipt(self, key: str) -> dict | None:
        """Return the committed typed tool receipt, if one exists."""

    def commit(self, key: str, receipt: dict | None = None) -> None:
        """Commit a key and its receipt so replays reuse the execution fact."""

    def release(self, key: str) -> None:
        """Release a reserved key when execution did not complete."""


@dataclass(frozen=True, slots=True)
class ToolGatewayContext:
    execution_mode: str
    tool_call_id: str
    step_id: str | None = None
    thread_id: str | None = None
    run_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    source_platform: str | None = None
    react_allowed_tools: frozenset[str] = frozenset()


__all__ = [
    "ToolAuditSink",
    "IdempotencyStore",
    "ToolGatewayContext",
]
