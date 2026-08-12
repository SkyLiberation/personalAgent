# ADR 0003: Principal Ownership and Execution Association

- Status: Accepted
- Date: 2026-08-08

## Context and Baseline

The product goal is private personal knowledge and interaction lifecycle management. No user evidence
established a workspace product boundary, yet Conversation IDs and caller-supplied partition IDs were used as
knowledge owners. L07 executed the natural goal “save my fact, then recall it in a new Conversation”. The
baseline save succeeded but recall returned no record
(`data/e2e_traces/20260808T075713.239052Z-30360-52c7f40a`).

DUR-001 later created a private natural interaction, restarted the Web process, and read its public
`interaction_run_ref` as another principal. Both the owner and the other principal received `200`; the second
response contained the owner's original secret-bearing message
(`data/e2e_traces/20260811T123526.301024Z-18200-577304a8`). The same request produced no same-run policy
diagnosis. This proved an Interaction owner gap rather than a generic checkpoint or observability-platform gap.

## Decision

Use two canonical contracts with distinct responsibilities:

- `AuthenticatedPrincipal` identifies the authenticated tenant/user and owns that user's private resources;
- `ExecutionScope` associates an invocation with that principal, execution, Project/Plan/SubGoal and task.

`AgentGatewayContext` and `ToolGatewayContext` contain `ExecutionScope` plus gateway-specific transport
fields. `ResourceRef.owner` is an `AuthenticatedPrincipal`. HTTP API-key configuration maps a key to that
typed principal; request payloads cannot choose a workspace or owner partition. Execution, Conversation and
Project associations never grant resources owned by another principal.

`InteractionTrace` stores the same `AuthenticatedPrincipal` as a canonical field. `ConversationService` checks
it before trace reads and before resuming an existing run; scope mismatch fails as not-found and records one
existing `policy.decision` with `run_id=interaction_run_ref`, action, deny effect, and rule
`conversation_run_scope_mismatch`. The audit record diagnoses the authorization stage but does not decide or
alter the denial.

## Ownership

- Authenticated identity: HTTP/CLI/message interface adapter.
- Resource ownership: `AuthenticatedPrincipal` on the canonical resource.
- Invocation association: Application-created `ExecutionScope`.
- Interaction owner and read/resume admission: `InteractionTrace` and `ConversationService`.
- Authorization decision: Policy/ToolGateway/AgentGateway, never a DTO converter.

## Migration and Net Complexity

All known Gateway, Conversation, Knowledge, Investigation, Tool, Artifact and Web callers were migrated in
place. `SecurityScope`, workspace request fields, workspace routes, workspace stores and workspace-named
Application modules were deleted without aliases or dual writes. Personal knowledge storage keys are derived
from the authenticated principal. Interaction journal snapshots created before the principal field cannot be
safely migrated because no trustworthy owner fact exists; they are quarantined and return not-found instead
of being assigned to the current caller. No owner side table, fallback identity, duplicate trace model, or new
observability store was added.

## Referenced Mechanisms

- **A, installed LangGraph 1.1.10 / langgraph-checkpoint 4.1.1**:
  `langgraph/checkpoint/base/__init__.py:182-192` makes `thread_id` the checkpoint lookup key, while user
  context is supplied separately. We adopt the separation between execution pointer and principal; a run ref
  is not authorization.
- **A, Temporal Python SDK main branch, `temporalio/workflow.py::execute_activity` and
  `README.md#workflow-replay`**: non-deterministic work is an Activity and Workflow history is replayed;
  a workflow ID is still not authority. Existing Project journals already follow the recorded-result rule;
  DUR-001 did not justify replacing the Conversation journal with Temporal.
- **A, OpenTelemetry Specification 1.59.0, Logs / Log Correlation**: logs correlate by execution context using
  trace/span identifiers. We adopt the smaller same-run correlation field already present in
  `policy.decision`; we reject a new OTel backend because the failed baseline required a diagnosable event,
  not a telemetry platform.

## Verification

L07 now passes for the same natural input and formal entry path
(`data/e2e_traces/20260808T084332.564715Z-7092-0f815eeb`). Principal isolation is additionally covered by
Gateway, Artifact, Web route, auth and Tool tests. DUR-001 and OBS-001 now pass the same process-restart
scenario: the owner receives `200`, the other principal receives `404` without the secret, and the server log
contains the same run ref plus the unique denial rule
(`data/e2e_traces/20260811T131846.157075Z-14556-f95a2089`). These tests prove the current private-resource
contract; they do not prove a future shared-collection requirement or distributed session-store requirement.

## Alternatives and Exit

Keeping workspace as an unowned generic container was rejected because it created a second identity without
a user-visible lifecycle. Mapping workspace to Conversation was rejected because a new Conversation then
lost the user's long-term knowledge. Treating `interaction_run_ref` as a bearer credential was rejected because
it allowed durable private messages to escape their owner scope. Adding a second owner index was rejected
because the owner belongs on the canonical snapshot. If a proven future goal needs sharing, introduce a
specifically named aggregate with its own membership and lifecycle only after its simplest production
baseline fails.
