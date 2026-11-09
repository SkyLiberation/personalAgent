from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from personal_agent.kernel.observability import (
    _current_langsmith_run_id,
    PolicyDecisionRecorder,
    record_tool_audit,
)
from personal_agent.kernel.rate_limit import InMemoryRateLimiter
from personal_agent.kernel.models import EntryInput
from personal_agent.kernel.contracts.tool_runtime import (
    ToolAuditSink,
    ToolGatewayContext,
)
from personal_agent.governance.policy import PolicyEngine
from personal_agent.capabilities.contracts.grants import (
    AtomicCapabilityGrant,
    ProcedureNodeGrant,
)
from personal_agent.kernel.contracts.scope import ExecutionScope, AuthenticatedPrincipal
from personal_agent.kernel.contracts.policy import (
    PolicyDecision,
    PolicyDecisionEvent,
    PolicyEvaluator,
    PolicyInput,
)
from personal_agent.tools.base import (
    ToolArtifact,
    ToolError,
    ToolGovernance,
    ToolInvocationEvent,
    tool_failure,
    tool_governance,
    tool_invocation_event,
    url_allowed,
)

logger = logging.getLogger(__name__)

_EXTERNAL_NETWORK_EFFECTS = frozenset({"external_network", "send_external"})
# 异常类型 -> 错误分类的默认映射，用于未显式抛出 ToolError 的底层异常。
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
)


def _classify_exception(exc: BaseException) -> str:
    """Map a raw exception to a ToolErrorKind when the tool did not classify it."""
    if isinstance(exc, ToolError):
        return exc.kind
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "invalid_param"
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, _TRANSIENT_EXCEPTIONS):
        return "transient"
    return "unrecoverable"


@dataclass(slots=True)
class InMemoryToolAuditSink:
    events: list[ToolInvocationEvent] = field(default_factory=list)

    def record(self, event: ToolInvocationEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True, slots=True)
class _PolicyViolation:
    """A pre-execution policy rejection carrying its error classification."""

    message: str
    kind: str = "permission"


class ToolGateway:
    """LangGraph-native boundary for policy, execution, and audit.

    The gateway keeps the same ``tool_messages`` contract expected by the
    graph, but centralizes project-specific governance before a real tool can
    touch storage or the network: error-kind-driven retries, external-access
    domain allow-listing, dispatch admission, and structured audit.
    """

    def __init__(
        self,
        audit_sink: ToolAuditSink | None = None,
        *,
        policy_engine: PolicyEvaluator | None = None,
        policy_decisions: PolicyDecisionRecorder | None = None,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
        application_owned_tools: frozenset[str] = frozenset(),
    ) -> None:
        self._prompts = prompts
        self._tools: dict[str, BaseTool] = {}
        self._application_owned_tools = application_owned_tools
        self.audit_sink = audit_sink
        self._policy = policy_engine or PolicyEngine(prompts=prompts)
        self._policy_decisions = policy_decisions or PolicyDecisionRecorder()
        self._rate_limiter = InMemoryRateLimiter()
        self._executor = ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="tool-gateway"
        )

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def invoke(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolGatewayContext,
        *,
        grant: AtomicCapabilityGrant | ProcedureNodeGrant | None = None,
    ) -> dict[str, Any]:
        return self._invoke(name, args, context, grant=grant, confirmed=False)

    def invoke_confirmed(
        self, name: str, args: dict[str, Any], context: ToolGatewayContext,
    ) -> dict[str, Any]:
        """Dispatch a command already approved by the owning Application."""
        if name not in self._application_owned_tools:
            raise PermissionError("tool has no application-owned approval binding")
        return self._invoke(name, args, context, grant=None, confirmed=True)

    def _invoke(
        self, name: str, args: dict[str, Any], context: ToolGatewayContext, *,
        grant: AtomicCapabilityGrant | ProcedureNodeGrant | None, confirmed: bool,
    ) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return tool_failure(
                self._prompts.render('tool_gateway.not_found', tool_name=name), error_kind="invalid_param"
            ).model_dump(mode="json")

        started = perf_counter()
        output: ToolArtifact
        attempts = 0
        timed_out = False
        rate_limited = False
        try:
            governance = tool_governance(tool)
            violation = (
                self._validate_execution_grant(tool, args, context, grant)
                or self._validate_policy(tool, governance, context, confirmed=confirmed)
                or self._validate_external_access(tool, governance, args)
            )
            if violation is not None:
                output = tool_failure(violation.message, error_kind=violation.kind)
            elif self._is_rate_limited(tool, context):
                rate_limited = True
                output = tool_failure(
                    self._prompts.render('tool_gateway.rate_limited', tool_name=tool.name),
                    error_kind="transient",
                )
            else:
                output, attempts, timed_out = self._invoke_with_strategy(
                    tool, name, args, context
                )
        except Exception as exc:
            logger.exception("Tool gateway execution failed for %s", name)
            output = tool_failure(str(exc)[:500], error_kind=_classify_exception(exc))
            attempts = max(attempts, 1)

        self._record_invocation(
            tool,
            args,
            output,
            context,
            (perf_counter() - started) * 1000,
            attempts=attempts,
            timed_out=timed_out,
            rate_limited=rate_limited,
            confirmed=confirmed,
        )
        return output.model_dump(mode="json")

    def _invoke_with_strategy(
        self,
        tool: BaseTool,
        name: str,
        args: dict[str, Any],
        context: ToolGatewayContext,
    ) -> tuple[ToolArtifact, int, bool]:
        governance = tool_governance(tool)
        max_attempts = governance.max_retries + 1
        timed_out = False
        last_output: ToolArtifact | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                output = self._invoke_once(tool, name, args, context)
                # 仅瞬时类失败才重试；参数/权限/不可恢复错误立即返还。
                if (
                    not output.ok
                    and output.error_kind == "transient"
                    and attempt < max_attempts
                ):
                    last_output = output
                    self._sleep_before_retry(governance.retry_backoff_seconds, attempt)
                    continue
                return output, attempt, timed_out
            except TimeoutError:
                timed_out = True
                last_output = tool_failure(
                    self._prompts.render('tool_gateway.timed_out', tool_name=tool.name, seconds=governance.timeout_seconds),
                    error_kind="transient",
                )
                if attempt < max_attempts:
                    self._sleep_before_retry(governance.retry_backoff_seconds, attempt)
                    continue
                return last_output, attempt, timed_out
            except Exception as exc:
                kind = _classify_exception(exc)
                last_output = tool_failure(str(exc)[:500], error_kind=kind)
                if kind == "transient" and attempt < max_attempts:
                    self._sleep_before_retry(governance.retry_backoff_seconds, attempt)
                    continue
                return last_output, attempt, timed_out
        return (
            last_output
            or tool_failure(self._prompts.render('tool_gateway.not_executed', tool_name=tool.name), error_kind="unrecoverable"),
            max_attempts,
            timed_out,
        )

    def _invoke_once(
        self,
        tool: BaseTool,
        name: str,
        args: dict[str, Any],
        context: ToolGatewayContext,
    ) -> ToolArtifact:
        governance = tool_governance(tool)

        def run_tool():
            return tool.invoke(
                {
                    "name": name,
                    "args": args,
                    "id": context.tool_call_id,
                    "type": "tool_call",
                },
                config={"configurable": {"__personal_agent_gateway_context": context}},
            )

        if governance.timeout_seconds is None:
            message = run_tool()
        else:
            future = self._executor.submit(run_tool)
            try:
                message = future.result(timeout=float(governance.timeout_seconds))
            except TimeoutError:
                future.cancel()
                raise
        artifact = getattr(message, "artifact", None)
        if isinstance(artifact, ToolArtifact):
            return artifact
        if isinstance(artifact, dict) and "ok" in artifact:
            return ToolArtifact.model_validate(artifact)
        return tool_failure(str(getattr(message, "content", self._prompts.render('tools.execution_failed'))))

    @staticmethod
    def _sleep_before_retry(backoff_seconds: float, attempt: int) -> None:
        if backoff_seconds <= 0:
            return
        time.sleep(backoff_seconds * attempt)

    def _is_rate_limited(self, tool: BaseTool, context: ToolGatewayContext) -> bool:
        governance = tool_governance(tool)
        limit = governance.rate_limit_per_minute
        if limit is None or limit <= 0:
            return False
        subject = context.execution_scope.principal.principal_id
        key = f"{tool.name}:{subject}"
        return not self._rate_limiter.allow(key, limit=limit, window_seconds=60.0)

    def invoke_graph(self, state: Any) -> dict[str, list[ToolMessage]]:
        call = self._latest_tool_call(state)
        if call is None:
            return {
                "tool_messages": [
                    ToolMessage(
                        content=self._prompts.render('tool_gateway.no_pending_call'),
                        tool_call_id="",
                        artifact=tool_failure(
                            self._prompts.render('tool_gateway.no_pending_call')
                        ).model_dump(mode="json"),
                    )
                ]
            }

        name = str(call.get("name", ""))
        args = call.get("args", {})
        normalized_args = args if isinstance(args, dict) else {}
        call_id = str(call.get("id", ""))
        context = self._context_from_state(state, call_id)
        grant = self._grant_from_state(
            state,
            context.execution_scope.logical_subgoal_id
            or context.execution_scope.task_id,
        )
        artifact = self.invoke(name, normalized_args, context, grant=grant)
        content = (
            str(artifact.get("data"))
            if artifact.get("ok")
            else str(artifact.get("error") or self._prompts.render('tools.execution_failed'))
        )
        return {
            "tool_messages": [
                ToolMessage(content=content, tool_call_id=call_id, artifact=artifact)
            ]
        }

    def _validate_policy(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        context: ToolGatewayContext,
        *,
        confirmed: bool,
    ) -> _PolicyViolation | None:
        decision = self.policy_decision(
            tool, governance, principal=context.execution_scope.principal,
            source_platform=context.source_platform, execution_mode=context.execution_mode,
            react_allowed_tools=context.react_allowed_tools,
            confirmed=confirmed,
        )
        self._record_policy_decision(tool, governance, context, decision)
        if not decision.allowed:
            return _PolicyViolation(decision.reason, kind=decision.error_kind)
        return None

    def policy_decision(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        *,
        principal: AuthenticatedPrincipal,
        source_platform: str | None,
        execution_mode: str = "direct",
        react_allowed_tools: frozenset[str] = frozenset(),
        confirmed: bool = False,
    ) -> PolicyDecision:
        return self._policy.evaluate(
            PolicyInput(
                action="tool_call",
                principal=principal,
                source_platform=source_platform,
                execution_mode=execution_mode,
                tool_name=tool.name,
                risk_level=governance.risk_level,
                requires_confirmation=governance.requires_confirmation,
                side_effects=tuple(governance.side_effects),
                permission_scope=governance.permission_scope,
                react_allowed_tools=react_allowed_tools,
                confirmed=confirmed,
            )
        )

    @staticmethod
    def _validate_execution_grant(
        tool: BaseTool,
        args: dict[str, Any],
        context: ToolGatewayContext,
        grant: AtomicCapabilityGrant | ProcedureNodeGrant | None,
    ) -> _PolicyViolation | None:
        if context.execution_mode == "direct":
            return None
        if grant is None:
            return _PolicyViolation(
                "agent tool dispatch requires a leaf execution grant"
            )
        tool_name = tool.name
        bound_name = grant.provider_binding_ref.rsplit(":", 1)[-1]
        if bound_name != tool_name:
            return _PolicyViolation("execution grant is bound to a different tool")
        if (
            (
                context.execution_scope.logical_subgoal_id
                or context.execution_scope.task_id
            )
            and isinstance(grant, AtomicCapabilityGrant)
            and grant.action_ref
            != (
                context.execution_scope.logical_subgoal_id
                or context.execution_scope.task_id
            )
        ):
            return _PolicyViolation(
                "execution grant is bound to a different invocation"
            )
        locator = grant.granted_resource_selector.locator
        mcp = (tool.extras or {}).get("mcp")
        if locator is not None and isinstance(mcp, dict):
            locator_arg = mcp.get("resource_locator_arg")
            if not isinstance(locator_arg, str) or not locator_arg:
                return _PolicyViolation(
                    "scoped MCP dispatch has no declared resource locator binding"
                )
            if args.get(locator_arg) != locator:
                return _PolicyViolation(
                    "MCP tool input does not match the resource locator frozen by the grant"
                )
        return None

    @staticmethod
    def _grant_from_state(
        state: Any,
        step_id: str | None,
    ) -> AtomicCapabilityGrant | ProcedureNodeGrant | None:
        invocations = getattr(
            getattr(state, "invocation_batch", None), "invocations", ()
        )
        invocation = next(
            (item for item in invocations if item.step_id == step_id), None
        )
        if invocation is None:
            react_step_id = getattr(getattr(state, "react", None), "step_id", "")
            invocation = next(
                (item for item in invocations if item.step_id == react_step_id), None
            )
        grant_ref = getattr(invocation, "execution_grant_ref", None)
        grant = getattr(state, "execution_grants", {}).get(grant_ref or "")
        if isinstance(grant, ProcedureNodeGrant) and invocation is not None:
            node_id = (
                getattr(invocation, "procedure_node_id", None) or invocation.step_id
            )
            if grant.node_id != node_id:
                return None
        return (
            grant
            if isinstance(grant, (AtomicCapabilityGrant, ProcedureNodeGrant))
            else None
        )

    def _record_policy_decision(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        context: ToolGatewayContext,
        decision: PolicyDecision,
    ) -> None:
        self._policy_decisions.record(
            PolicyDecisionEvent(
                action="tool_call",
                effect=decision.effect,
                rule=decision.rule,
                reason=decision.reason,
                tool_name=tool.name,
                permission_scope=governance.permission_scope,
                risk_level=governance.risk_level,
                user_id=context.execution_scope.principal.principal_id,
                session_id=context.execution_scope.principal.user_id,
                source_platform=context.source_platform,
                execution_mode=context.execution_mode,
                thread_id=context.execution_scope.thread_id,
                run_id=context.execution_scope.execution_id,
            ),
            audit_required=governance.audit_required,
        )

    def _validate_external_access(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        args: dict[str, Any],
    ) -> _PolicyViolation | None:
        """Enforce domain allow-listing on external-network tool arguments."""
        if not _EXTERNAL_NETWORK_EFFECTS.intersection(governance.side_effects):
            return None
        if not governance.allowed_domains:
            return None
        for value in args.values():
            if not isinstance(value, str) or "://" not in value:
                continue
            if not url_allowed(value, governance.allowed_domains):
                return _PolicyViolation(
                    self._prompts.render('tool_gateway.domain_denied', tool_name=tool.name),
                    kind="permission",
                )
        return None

    def _record_invocation(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        output: ToolArtifact,
        context: ToolGatewayContext,
        latency_ms: float,
        *,
        attempts: int = 1,
        timed_out: bool = False,
        rate_limited: bool = False,
        confirmed: bool = False,
    ) -> None:
        event = tool_invocation_event(
            tool,
            tool_call_id=context.tool_call_id,
            input=args,
            output=output,
            execution_mode=context.execution_mode,
            step_id=(
                context.execution_scope.logical_subgoal_id
                or context.execution_scope.task_id
            ),
            thread_id=context.execution_scope.thread_id,
            run_id=context.execution_scope.execution_id,
            user_id=context.execution_scope.principal.principal_id,
            latency_ms=latency_ms,
            langsmith_run_id=_current_langsmith_run_id(),
            attempts=attempts,
            timed_out=timed_out,
            rate_limited=rate_limited,
        ).model_copy(update={"confirmed": confirmed})
        if self.audit_sink is not None:
            self.audit_sink.record(event)
        record_tool_audit(event)
        logger.info(
            "Tool invocation completed",
            extra={"tool_invocation": event.model_dump(mode="json")},
        )

    def _context_from_state(self, state: Any, call_id: str) -> ToolGatewayContext:
        tracking = getattr(state, "tool_tracking", None)
        react = getattr(state, "react", None)
        active_context = getattr(tracking, "active_context", None)
        execution_mode = "react" if active_context == "react" else "deterministic"
        entry_input = getattr(state, "entry_input", None)
        source_platform = getattr(entry_input, "source_platform", None)
        tenant_id = str(getattr(state, "tenant_id", None) or "personal-agent")
        user_id = str(getattr(state, "user_id", None) or "anonymous")
        return ToolGatewayContext(
            execution_scope=ExecutionScope(
                principal=AuthenticatedPrincipal(
                    tenant_id=tenant_id,
                    user_id=user_id,
                ),
                execution_id=str(getattr(state, "run_id", None) or call_id),
                thread_id=getattr(state, "thread_id", None),
                task_id=getattr(tracking, "pending_step_id", None),
            ),
            execution_mode=execution_mode,
            tool_call_id=call_id,
            source_platform=source_platform,
            react_allowed_tools=frozenset(getattr(react, "allowed_tools", []) or []),
            allowed_resource_refs=tuple(entry_input.artifacts)
            if isinstance(entry_input, EntryInput)
            else (),
        )

    @staticmethod
    def _latest_tool_call(state: Any) -> dict[str, Any] | None:
        for message in reversed(getattr(state, "tool_messages", []) or []):
            if isinstance(message, AIMessage) and message.tool_calls:
                return message.tool_calls[-1]
        return None
