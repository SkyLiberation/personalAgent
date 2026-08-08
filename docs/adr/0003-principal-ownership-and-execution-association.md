# ADR 0003: Principal Ownership and Execution Association

- Status: Accepted
- Date: 2026-08-08

## Context and Baseline

The product goal is personal knowledge lifecycle management. No user evidence established a need for a
workspace product boundary, yet Conversation IDs and caller-supplied partition IDs were used as knowledge
owners. L07 executed the natural goal “save my fact, then recall it in a new Conversation”. The baseline save
succeeded but recall returned no record (`data/e2e_traces/20260808T075713.239052Z-30360-52c7f40a`).

## Decision

Use two canonical contracts with distinct responsibilities:

- `AuthenticatedPrincipal` identifies the authenticated tenant/user and owns that user's private resources;
- `ExecutionScope` associates an invocation with that principal, execution, Project/Plan/SubGoal and task.

`AgentGatewayContext` and `ToolGatewayContext` contain `ExecutionScope` plus gateway-specific transport
fields. `ResourceRef.owner` is an `AuthenticatedPrincipal`. HTTP API-key configuration maps a key to that
typed principal; request payloads cannot choose a workspace or owner partition. Execution, Conversation and
Project associations never grant resources owned by another principal.

## Ownership

- Authenticated identity: HTTP/CLI/message interface adapter.
- Resource ownership: `AuthenticatedPrincipal` on the canonical resource.
- Invocation association: Application-created `ExecutionScope`.
- Authorization decision: Policy/ToolGateway/AgentGateway, never a DTO converter.

## Migration and Net Complexity

All known Gateway, Conversation, Knowledge, Investigation, Tool, Artifact and Web callers were migrated in
place. `SecurityScope`, workspace request fields, workspace routes, workspace stores and workspace-named
Application modules were deleted without aliases or dual writes. Personal knowledge storage keys are derived
from the authenticated principal; Conversation retains only short-term interaction identity.

## Verification

L07 now passes for the same natural input and formal entry path
(`data/e2e_traces/20260808T084332.564715Z-7092-0f815eeb`). Principal isolation is additionally covered by
Gateway, Artifact, Web route, auth and Tool tests. These tests prove the current private-knowledge product
contract; they do not prove a future shared-collection requirement.

## Alternatives and Exit

Keeping workspace as an unowned generic container was rejected because it created a second identity without
a user-visible lifecycle. Mapping workspace to Conversation was rejected because a new Conversation then
lost the user's long-term knowledge. If a proven future goal needs sharing, introduce a specifically named
aggregate with its own membership and lifecycle only after its simplest production baseline fails.
