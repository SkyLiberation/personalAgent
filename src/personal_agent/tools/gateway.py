from __future__ import annotations

import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool

from ..core.observability import (
    _current_langsmith_run_id,
    record_policy_decision,
    record_tool_audit,
)
from ..policy import PolicyDecision, PolicyEngine, PolicyInput
from .base import (
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
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (TimeoutError, ConnectionError, OSError)


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


class ToolAuditSink(Protocol):
    def record(self, event: ToolInvocationEvent) -> None:
        """Persist or forward a normalized tool invocation event."""


@dataclass(slots=True)
class InMemoryToolAuditSink:
    events: list[ToolInvocationEvent] = field(default_factory=list)

    def record(self, event: ToolInvocationEvent) -> None:
        self.events.append(event)


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool:
        """Return True if this idempotency key was already committed."""

    def reserve(self, key: str, *, context: ToolGatewayContext, tool_name: str) -> bool:
        """Atomically reserve a key before executing a side effect."""

    def commit(self, key: str) -> None:
        """Mark an idempotency key as committed so replays are rejected."""

    def release(self, key: str) -> None:
        """Release a reserved key when execution did not complete."""


@dataclass(slots=True)
class InMemoryIdempotencyStore:
    """Process-local idempotency ledger.

    Guards confirmed high-risk executions against duplicate side effects from
    checkpoint resume, user double-confirmation, or network retries. A durable
    backend can replace this without changing the gateway contract.
    """

    _committed: set[str] = field(default_factory=set)

    def seen(self, key: str) -> bool:
        return key in self._committed

    def reserve(self, key: str, *, context: ToolGatewayContext, tool_name: str) -> bool:
        if self.seen(key):
            return False
        self._committed.add(key)
        return True

    def commit(self, key: str) -> None:
        self._committed.add(key)

    def release(self, key: str) -> None:
        self._committed.discard(key)


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
    domain allow-listing, idempotent side-effect dedup, and structured audit.
    """

    def __init__(
        self,
        audit_sink: ToolAuditSink | None = None,
        *,
        idempotency_store: IdempotencyStore | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.audit_sink = audit_sink
        self._idempotency = idempotency_store or InMemoryIdempotencyStore()
        self._policy = policy_engine or PolicyEngine()
        self._rate_windows: dict[tuple[str, str], deque[float]] = {}
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="tool-gateway")

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def invoke(self, name: str, args: dict[str, Any], context: ToolGatewayContext) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return tool_failure(f"未找到工具：{name}", error_kind="invalid_param").model_dump(mode="json")

        started = perf_counter()
        output: ToolArtifact
        attempts = 0
        timed_out = False
        rate_limited = False
        try:
            violation = self._validate_policy(tool, args, context)
            if violation is not None:
                output = tool_failure(violation.message, error_kind=violation.kind)
            elif self._is_rate_limited(tool, context):
                rate_limited = True
                output = tool_failure(
                    f"工具 {tool.name} 触发速率限制，请稍后再试。", error_kind="transient"
                )
            else:
                idempotency_key = self._reserve_idempotency(tool, args, context)
                try:
                    output, attempts, timed_out = self._invoke_with_strategy(tool, name, args, context)
                    self._commit_idempotency(tool, args, output)
                    if idempotency_key and not output.ok:
                        self._idempotency.release(idempotency_key)
                except Exception:
                    if idempotency_key:
                        self._idempotency.release(idempotency_key)
                    raise
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
                    f"工具 {tool.name} 执行超时（>{governance.timeout_seconds}s）。",
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
            last_output or tool_failure(f"工具 {tool.name} 未执行。", error_kind="unrecoverable"),
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
            return tool.invoke({
                "name": name,
                "args": args,
                "id": context.tool_call_id,
                "type": "tool_call",
            })

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
        return tool_failure(str(getattr(message, "content", "工具执行失败。")))

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
        subject = context.user_id or context.thread_id or "anonymous"
        key = (tool.name, subject)
        now = time.monotonic()
        window = self._rate_windows.setdefault(key, deque())
        while window and now - window[0] >= 60.0:
            window.popleft()
        if len(window) >= limit:
            return True
        window.append(now)
        return False

    def invoke_graph(self, state: Any) -> dict[str, list[ToolMessage]]:
        call = self._latest_tool_call(state)
        if call is None:
            return {
                "tool_messages": [
                    ToolMessage(
                        content="工具节点未收到待执行的工具调用。",
                        tool_call_id="",
                        artifact=tool_failure("工具节点未收到待执行的工具调用。").model_dump(mode="json"),
                    )
                ]
            }

        name = str(call.get("name", ""))
        args = call.get("args", {})
        normalized_args = args if isinstance(args, dict) else {}
        call_id = str(call.get("id", ""))
        context = self._context_from_state(state, call_id)
        artifact = self.invoke(name, normalized_args, context)
        content = (
            str(artifact.get("data"))
            if artifact.get("ok")
            else str(artifact.get("error") or "工具执行失败。")
        )
        return {
            "tool_messages": [
                ToolMessage(content=content, tool_call_id=call_id, artifact=artifact)
            ]
        }

    def _validate_policy(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        context: ToolGatewayContext,
    ) -> _PolicyViolation | None:
        governance = tool_governance(tool)
        decision = self._policy.evaluate(
            PolicyInput(
                action="tool_call",
                user_id=context.user_id,
                session_id=context.session_id,
                source_platform=context.source_platform,
                execution_mode=context.execution_mode,
                tool_name=tool.name,
                risk_level=governance.risk_level,
                requires_confirmation=governance.requires_confirmation,
                side_effects=tuple(governance.side_effects),
                permission_scope=governance.permission_scope,
                confirmed=bool(args.get("confirmed")),
                react_allowed_tools=context.react_allowed_tools,
            )
        )
        self._record_policy_decision(tool, governance, context, decision)
        if decision.effect in ("deny", "require_escalation"):
            return _PolicyViolation(decision.reason, kind=decision.error_kind)
        # require_confirmation 不阻断调用：工具会走无副作用的确认预览分支，生成
        # pending_confirmation 负载，由图层的 HITL interrupt 暂停等待用户确认。真实
        # 副作用只在 confirmed=true 时发生，并受下方幂等机制保护。

        domain_violation = self._validate_external_access(tool, governance, args)
        if domain_violation is not None:
            return domain_violation

        # 策略放行后，gateway 仍负责确认动作的幂等前置校验（key 必填）。
        # 真正的并发去重在执行前的 reserve() 完成，避免 seen()/commit()
        # 分离导致两个进程同时通过检查。
        return self._validate_idempotency(tool, governance, args)

    def _validate_idempotency(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        args: dict[str, Any],
    ) -> _PolicyViolation | None:
        is_confirmed_execution = bool(args.get("confirmed"))
        if not (governance.requires_confirmation and governance.risk_level == "high" and is_confirmed_execution):
            return None
        key = str(args.get("idempotency_key", "")).strip()
        if governance.idempotency_key_required and not key:
            return _PolicyViolation(
                f"工具 {tool.name} 执行高风险确认动作时缺少 idempotency_key。",
                kind="invalid_param",
            )
        return None

    def _reserve_idempotency(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        context: ToolGatewayContext,
    ) -> str | None:
        governance = tool_governance(tool)
        if not (governance.idempotency_key_required and bool(args.get("confirmed"))):
            return None
        key = str(args.get("idempotency_key", "")).strip()
        if not key:
            return None
        if not self._idempotency.reserve(key, context=context, tool_name=tool.name):
            raise ToolError(
                f"工具 {tool.name} 的确认动作已执行过或正在执行（idempotency_key={key}），已跳过重复副作用。",
                kind="unrecoverable",
            )
        return key

    def _record_policy_decision(
        self,
        tool: BaseTool,
        governance: ToolGovernance,
        context: ToolGatewayContext,
        decision: PolicyDecision,
    ) -> None:
        record_policy_decision(
            action="tool_call",
            effect=decision.effect,
            rule=decision.rule,
            reason=decision.reason,
            tool_name=tool.name,
            permission_scope=governance.permission_scope,
            risk_level=governance.risk_level,
            user_id=context.user_id,
            session_id=context.session_id,
            source_platform=context.source_platform,
            execution_mode=context.execution_mode,
            thread_id=context.thread_id,
            run_id=context.run_id,
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
                    f"工具 {tool.name} 的目标 URL 不在允许域名列表中。",
                    kind="permission",
                )
        return None

    def _commit_idempotency(
        self, tool: BaseTool, args: dict[str, Any], output: ToolArtifact
    ) -> None:
        """Record a successful confirmed side effect so replays are rejected."""
        if not output.ok:
            return
        governance = tool_governance(tool)
        if not (governance.idempotency_key_required and bool(args.get("confirmed"))):
            return
        key = str(args.get("idempotency_key", "")).strip()
        if key:
            self._idempotency.commit(key)

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
    ) -> None:
        event = tool_invocation_event(
            tool,
            tool_call_id=context.tool_call_id,
            input=args,
            output=output,
            execution_mode=context.execution_mode,
            step_id=context.step_id,
            thread_id=context.thread_id,
            run_id=context.run_id,
            user_id=context.user_id,
            latency_ms=latency_ms,
            langsmith_run_id=_current_langsmith_run_id(),
            attempts=attempts,
            timed_out=timed_out,
            rate_limited=rate_limited,
        )
        if self.audit_sink is not None:
            self.audit_sink.record(event)
        record_tool_audit(event)
        logger.info("Tool invocation completed", extra={"tool_invocation": event.model_dump(mode="json")})

    def _context_from_state(self, state: Any, call_id: str) -> ToolGatewayContext:
        tracking = getattr(state, "tool_tracking", None)
        react = getattr(state, "react", None)
        active_context = getattr(tracking, "active_context", None)
        execution_mode = "react" if active_context == "react" else "deterministic"
        entry_input = getattr(state, "entry_input", None)
        source_platform = getattr(entry_input, "source_platform", None)
        return ToolGatewayContext(
            execution_mode=execution_mode,
            tool_call_id=call_id,
            step_id=getattr(tracking, "pending_step_id", None),
            thread_id=getattr(state, "thread_id", None),
            run_id=getattr(state, "run_id", None),
            user_id=getattr(state, "user_id", None),
            session_id=getattr(state, "session_id", None),
            source_platform=source_platform,
            react_allowed_tools=frozenset(getattr(react, "allowed_tools", []) or []),
        )

    @staticmethod
    def _latest_tool_call(state: Any) -> dict[str, Any] | None:
        for message in reversed(getattr(state, "tool_messages", []) or []):
            if isinstance(message, AIMessage) and message.tool_calls:
                return message.tool_calls[-1]
        return None
