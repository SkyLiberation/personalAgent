"""专用回放进程的 SDK 封存、首发对照和逐物理发送费用门禁。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import wraps
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterator
from uuid import uuid4

from pydantic import ValidationError

from evals.product_baselines.retrieval_http_server import redact_payload
from evals.provider_diagnostics.python_result_analysis_models import (
    FirstSdkAudit,
    GroupPlan,
    GroupState,
    PhysicalCall,
    Record,
    Usage,
)


class SampleStopped(BaseException):
    """在下一次付费前离开循环，不变成模型可修复反馈或 SDK 重试。"""

    def __init__(self, reason: str, *, stop_group: bool = False) -> None:
        self.reason = reason
        self.stop_group = stop_group
        super().__init__(reason)


def write_record(path: Path, value: Record) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(value.model_dump_json(indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class GroupLedger:
    """本组调度事实唯一写入口；用量从逐物理回执推导，不写原 run。"""

    def __init__(self, directory: Path, plan: GroupPlan) -> None:
        self.path = directory / "group-state.json"
        self.plan = plan
        self.lock = RLock()
        self.state = GroupState.model_validate_json(self.path.read_bytes())
        if self.state.group_id != plan.group_id:
            raise ValueError("group-state 不属于当前计划")

    def save(self, state: GroupState) -> None:
        with self.lock:
            write_record(self.path, state)
            self.state = state

    def replace_call(self, call: PhysicalCall) -> None:
        with self.lock:
            self.save(
                self.state.model_copy(
                    update={
                        "physical_calls": tuple(
                            call if item.send_id == call.send_id else item
                            for item in self.state.physical_calls
                        ),
                    }
                )
            )

    def stop(self, reason: str) -> None:
        with self.lock:
            self.save(self.state.model_copy(update={"stopped_reason": reason}))


def _system_projection(text: str, *, remove_python: bool) -> tuple[str, float | None]:
    """只消除声明的能力变量及 wall 快照；Plan 和其他文字逐字保留。"""
    lines = text.splitlines()
    wall = None
    for index, line in enumerate(lines):
        if line.startswith("可用能力："):
            policy = json.loads(line.removeprefix("可用能力："))
            if remove_python:
                policy["tools"] = [
                    item
                    for item in policy["tools"]
                    if item.get("capability_id") != "execute_python"
                ]
            lines[index] = "可用能力：" + json.dumps(
                policy,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        elif line.startswith("剩余预算："):
            remaining = json.loads(line.removeprefix("剩余预算："))
            wall = remaining.pop("wall_seconds_at_input", None)
            lines[index] = "剩余预算：" + json.dumps(remaining, sort_keys=True)
    return "\n".join(lines), wall


def compare_first_sdk(
    source: dict[str, Any],
    actual: dict[str, Any],
    *,
    sample_id: str,
    source_sha256: str,
    wall_upper: float,
) -> FirstSdkAudit:
    expected_messages, actual_messages = (
        source.get("messages", []),
        actual.get("messages", []),
    )
    source_tools = source.get("tools", [])
    actual_tools = actual.get("tools", [])
    python_tools = [
        item
        for item in actual_tools
        if item.get("function", {}).get("name") == "tool_execute_python"
    ]
    original_tools = [item for item in actual_tools if item not in python_tools]
    messages_match = (
        len(expected_messages) == len(actual_messages) == 3
        and expected_messages[1:] == actual_messages[1:]
        and [item.get("role") for item in expected_messages]
        == [item.get("role") for item in actual_messages]
    )
    expected_system, _ = _system_projection(
        expected_messages[0]["content"], remove_python=False
    )
    actual_system, wall = _system_projection(
        actual_messages[0]["content"], remove_python=True
    )
    excluded = {"messages", "tools"}
    configuration_match = {
        key: value for key, value in source.items() if key not in excluded
    } == {key: value for key, value in actual.items() if key not in excluded}
    differences = []
    checks = {
        "完整用户消息／89项typed输入或角色不同": messages_match,
        "源模型参数或输出协议不同": configuration_match,
        "原19项工具定义／顺序不同": original_tools == source_tools,
        "除Python投影与时间映射外System不同": actual_system == expected_system,
        "Python入口数量不符合组别": len(python_tools) == int(sample_id.startswith("C")),
        "wall映射超出源剩余或缺失": wall is not None and 0 < wall <= wall_upper,
    }
    differences.extend(reason for reason, passed in checks.items() if not passed)
    return FirstSdkAudit(
        sample_id=sample_id,
        source_request_sha256=source_sha256,
        actual_request_sha256=sha256(
            json.dumps(
                actual,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest(),
        matching_user_and_typed_inputs=messages_match,
        matching_model_configuration=configuration_match,
        matching_original_tools=original_tools == source_tools,
        matching_system_after_declared_projection=actual_system == expected_system,
        python_tool_count=len(python_tools),
        wall_seconds=wall,
        allowed_wall_upper=wall_upper,
        differences=tuple(differences),
    )


class SdkCapture:
    """只在一个原子样本的专用进程内安装；真实输出不被修订或评分。"""

    def __init__(
        self,
        *,
        ledger: GroupLedger,
        sample_id: str,
        directory: Path,
        source_sdk: dict[str, Any],
        mapped_deadline: datetime,
        provider_host: str,
        provider_timeout: float,
    ) -> None:
        self.ledger, self.sample_id, self.directory = ledger, sample_id, directory
        self.source_sdk, self.mapped_deadline = source_sdk, mapped_deadline
        self.provider_host, self.provider_timeout = provider_host, provider_timeout
        self.clients: dict[object, str] = {}
        self.candidate_bodies: dict[str, dict[str, Any]] = {}
        self.first_audit: FirstSdkAudit | None = None
        self.sdk_seen = False

    def _admit(self, candidate_id: str, request: Any) -> PhysicalCall:
        body = json.loads(request.content)
        sdk_body = dict(self.candidate_bodies[candidate_id])
        sdk_body.update(sdk_body.pop("extra_body", {}) or {})
        if body != sdk_body:
            raise SampleStopped("http_body_differs_from_captured_sdk", stop_group=True)
        if request.url.host != self.provider_host or not request.url.path.endswith(
            "/chat/completions"
        ):
            raise SampleStopped("unexpected_model_endpoint", stop_group=True)
        if body.get("model") != self.source_sdk.get("model"):
            raise SampleStopped("unexpected_model_identity", stop_group=True)
        output = body.get("max_tokens", body.get("max_completion_tokens"))
        if (
            type(output) is not int
            or output != self.ledger.plan.limits.max_output_tokens
        ):
            raise SampleStopped("unexpected_request_output_budget", stop_group=True)
        # ASCII JSON counts all SDK text and declarations conservatively, with
        # explicit protocol/output reservation. This is not a provider tokenizer.
        input_bound = len(
            json.dumps(body, ensure_ascii=True, sort_keys=True).encode("ascii")
        )
        reserved = (
            input_bound + output + self.ledger.plan.limits.protocol_reserve_tokens
        )
        now = datetime.now(UTC)
        state, limits = self.ledger.state, self.ledger.plan.limits
        sample_calls = [
            item for item in state.physical_calls if item.sample_id == self.sample_id
        ]
        if state.stopped_reason:
            raise SampleStopped(state.stopped_reason, stop_group=True)
        if any(item.usage is None for item in state.physical_calls):
            raise SampleStopped("unknown_or_unsettled_provider_usage", stop_group=True)
        if len(sample_calls) >= limits.physical_calls_per_sample:
            raise SampleStopped("sample_physical_call_limit")
        if len(state.physical_calls) >= limits.physical_calls:
            raise SampleStopped("group_physical_call_limit", stop_group=True)
        if state.known_tokens + reserved > limits.tokens:
            raise SampleStopped("group_token_reservation_insufficient", stop_group=True)
        sample_tokens = sum(
            item.usage.total_tokens for item in sample_calls if item.usage
        )
        if sample_tokens + reserved > self.ledger.plan.source.remaining.tokens:
            raise SampleStopped(
                "source_token_reservation_insufficient", stop_group=True
            )
        if state.started_at is None:
            raise SampleStopped("group_start_missing", stop_group=True)
        group_deadline = state.started_at + timedelta(seconds=limits.wall_seconds)
        # The original model timeout stays unchanged; reserve a complete bounded
        # provider call plus the authorized 60-second Python action.
        if (
            min(group_deadline, self.mapped_deadline) - now
        ).total_seconds() < self.provider_timeout + 60:
            raise SampleStopped("wall_reservation_insufficient", stop_group=True)
        send_id = uuid4().hex
        (self.directory / f"{send_id}.http.request.json").write_bytes(request.content)
        call = PhysicalCall(
            send_id=send_id,
            candidate_id=candidate_id,
            sample_id=self.sample_id,
            at=now,
            request_sha256=sha256(request.content).hexdigest(),
            reservation_tokens=reserved,
            request_input_bound=input_bound,
            requested_output_tokens=output,
        )
        self.ledger.save(
            state.model_copy(update={"physical_calls": (*state.physical_calls, call)})
        )
        return call

    @contextmanager
    def installed(self) -> Iterator[SdkCapture]:
        import httpx
        from personal_agent.infra.structured_model import OpenAIModelClient, _ProviderCompletion

        original_create = OpenAIModelClient._create_chat_completion
        original_send = httpx.Client.send

        @wraps(original_send)
        def observed_send(client, request, *args, **kwargs):
            candidate_id = self.clients.get(client)
            if candidate_id is None:
                if request.url.host == self.provider_host or request.url.path.endswith(
                    ("/chat/completions", "/embeddings", "/responses")
                ):
                    raise SampleStopped("unobserved_provider_call", stop_group=True)
                return original_send(client, request, *args, **kwargs)
            with self.ledger.lock:
                call = self._admit(candidate_id, request)
            try:
                response = original_send(client, request, *args, **kwargs)
                call = call.model_copy(
                    update={
                        "response_received": True,
                        "http_status": response.status_code,
                    }
                )
                self.ledger.replace_call(call)
                return response
            except BaseException as error:
                call = call.model_copy(update={"error_type": type(error).__name__})
                self.ledger.replace_call(call)
                raise
            finally:
                write_record(
                    self.directory / f"{call.send_id}.http.response.json", call
                )

        @wraps(original_create)
        def observed_create(adapter, client, operation, kwargs, *, before_send=None) -> _ProviderCompletion:
            candidate_id = uuid4().hex
            payload = redact_payload(kwargs)
            self.candidate_bodies[candidate_id] = payload
            (self.directory / f"{candidate_id}.candidate.request.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if not self.sdk_seen:
                self.sdk_seen = True
                self.first_audit = compare_first_sdk(
                    self.source_sdk,
                    payload,
                    sample_id=self.sample_id,
                    source_sha256=self.ledger.plan.source.request.sha256,
                    wall_upper=self.ledger.plan.source.remaining.wall_seconds_at_input,
                )
                write_record(
                    self.directory.parent / "first-sdk-audit.json", self.first_audit
                )
                if not self.first_audit.passed:
                    raise SampleStopped("first_sdk_source_mismatch", stop_group=True)
            with self.ledger.lock:
                self.clients[client._client] = candidate_id
            try:
                completion = original_create(adapter, client, operation, kwargs, before_send=before_send)
                raw = completion.payload.model_dump(mode="json")
                (self.directory / f"{candidate_id}.candidate.response.json").write_text(
                    json.dumps(raw, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                calls = [
                    item
                    for item in self.ledger.state.physical_calls
                    if item.candidate_id == candidate_id
                ]
                try:
                    raw_usage = raw.get("usage") or {}
                    usage = Usage(
                        input_tokens=raw_usage.get("prompt_tokens"),
                        output_tokens=raw_usage.get("completion_tokens"),
                        total_tokens=raw_usage.get("total_tokens"),
                    )
                except ValidationError:
                    self.ledger.stop("provider_usage_unknown")
                    raise SampleStopped(
                        "provider_usage_unknown", stop_group=True
                    ) from None
                if len(calls) != 1:
                    self.ledger.stop("physical_usage_attribution_unknown")
                    raise SampleStopped(
                        "physical_usage_attribution_unknown", stop_group=True
                    )
                settled = calls[0].model_copy(update={"usage": usage})
                # Always settle the last paid response before any stopping test.
                self.ledger.replace_call(settled)
                write_record(
                    self.directory / f"{settled.send_id}.http.response.json", settled
                )
                if usage.total_tokens > settled.reservation_tokens:
                    self.ledger.stop("provider_usage_exceeded_reserved_bound")
                    raise SampleStopped(
                        "provider_usage_exceeded_reserved_bound", stop_group=True
                    )
                return completion
            except SampleStopped:
                raise
            except BaseException as error:
                (self.directory / f"{candidate_id}.candidate.failure.json").write_text(
                    json.dumps(
                        {"operation": operation, "error_type": type(error).__name__}
                    ),
                    encoding="utf-8",
                )
                self.ledger.stop("provider_or_sdk_failure")
                raise SampleStopped(
                    "provider_or_sdk_failure", stop_group=True
                ) from error
            finally:
                with self.ledger.lock:
                    self.clients.pop(client._client, None)

        OpenAIModelClient._create_chat_completion = observed_create
        httpx.Client.send = observed_send
        try:
            yield self
        finally:
            OpenAIModelClient._create_chat_completion = original_create
            httpx.Client.send = original_send
