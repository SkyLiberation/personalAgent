# ADR 0003: Typed Security and Execution Scope

- Status: Accepted
- Date: 2026-07-27
- Removal review: 2027-07-27

## Context and Baseline

Gateway contexts previously accepted separate raw `user_id`, session and metadata values. Resource
ownership was therefore easy to confuse with the execution that happened to produce a result. The
architecture-investigation path crosses HTTP identity, Project recovery, Tool/Agent calls and Artifact
reads; raw strings cannot mechanically prove tenant/workspace ownership.

## Decision

Use three canonical contracts:

- `AuthenticatedPrincipal` identifies the authenticated tenant/user actor;
- `SecurityScope` owns resources by tenant/workspace;
- `ExecutionScope` associates an invocation with principal, execution, Project/Plan/SubGoal and task.

`AgentGatewayContext` and `ToolGatewayContext` contain only `ExecutionScope` plus gateway-specific
transport fields. `ResourceRef.owner_scope` is a `SecurityScope`. HTTP API-key configuration is a JSON
mapping from key to typed principal; the old `key:user` syntax fails closed. When authentication is
enabled, a request body cannot override its tenant/user. Generated Artifact read/write performs both
principal and owner-scope checks.

## Ownership

- Authenticated identity: HTTP/CLI/message interface adapter.
- Resource ownership: `SecurityScope` on the canonical resource.
- Invocation association: Application-created `ExecutionScope`.
- Authorization decision: Policy/ToolGateway/AgentGateway, never a DTO converter.

## Migration and Net Complexity

All known Gateway, Conversation, Tool, Artifact, Web, CLI and Feishu callers were migrated in place.
Legacy raw scope fields and compatibility parsing were deleted. Added three small value models while
removing repeated raw context parameters and ambiguous ownership checks.

## Verification

Scope isolation is covered by LT08 plus Gateway, Artifact, Web route, auth and Tool tests. The system Tool
endpoint rejects authenticated tenant/user spoofing; debug database reset requires an admin key when
authentication is enabled.

## Alternatives and Exit

Raw dict validation at each adapter was rejected because it creates multiple owners and inconsistent
defaults. Do not remove typed scope until a superseding identity model migrates every ResourceRef,
Gateway definition and persisted Project/AgentRun, and equivalent cross-tenant E2E passes.
