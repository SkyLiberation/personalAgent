"""Tool-execution boundary contracts: audit sink and gateway context.

Pure structural types (Protocols + a frozen dataclass) shared between the infra
layer (which implements ``ToolAuditSink`` over Postgres) and
the governance layer (``ToolGateway``, which depends on them). Kept in the kernel
so infra never has to import the tools/governance packages to satisfy a type.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Protocol

from pydantic import BaseModel

from personal_agent.kernel.contracts.tool import ToolInvocationEvent
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.resource import ResourceRef


def accepted_tool_request_digest(
    *,
    execution_scope: ExecutionScope,
    action_id: str,
    tool_name: str,
    arguments: BaseModel,
) -> str:
    envelope = {
        "execution_scope": execution_scope.model_dump(mode="json"),
        "action_id": action_id,
        "tool_name": tool_name,
        "arguments": arguments.model_dump(mode="json"),
    }
    body = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return sha256(body.encode("utf-8")).hexdigest()


class ToolAuditSink(Protocol):
    def record(self, event: ToolInvocationEvent) -> None:
        """Persist or forward a normalized tool invocation event."""


@dataclass(frozen=True, slots=True)
class ToolGatewayContext:
    execution_scope: ExecutionScope
    execution_mode: str
    tool_call_id: str
    source_platform: str | None = None
    react_allowed_tools: frozenset[str] = frozenset()
    allowed_resource_refs: tuple[ResourceRef, ...] = ()
    accepted_request_digest: str | None = None


__all__ = [
    "accepted_tool_request_digest",
    "ToolAuditSink",
    "ToolGatewayContext",
]
