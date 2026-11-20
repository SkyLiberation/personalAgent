"""Estimate one final text SDK body and accept or reject without mutation."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Any
import unicodedata

from personal_agent.capabilities.contracts.model import (
    ModelCapacityCheck,
    ModelCapacityRefused,
)
from personal_agent.kernel.config_models import ModelCapacityConfig


def _normalized_text_payload(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_normalized_text_payload(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _normalized_text_payload(item) for key, item in value.items()}
    raise ValueError("unsupported non-JSON model payload")


def _utf8_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def check_model_capacity(
    *,
    operation: str,
    provider_host: str,
    model: str,
    kwargs: dict[str, Any],
    capacity: ModelCapacityConfig,
) -> ModelCapacityCheck:
    """A declared estimate, not a tokenizer count or mathematical upper bound."""
    if capacity.provider_host != provider_host or capacity.model != model:
        raise ModelCapacityRefused(operation, "capacity_profile_mismatch")
    body = {key: value for key, value in kwargs.items() if key != "extra_body"}
    extra = kwargs.get("extra_body") or {}
    if not isinstance(extra, dict) or set(extra) - {"thinking"}:
        raise ModelCapacityRefused(operation, "capacity_payload_unsupported")
    if "thinking" in extra and extra["thinking"] not in (
        {"type": "enabled"},
        {"type": "disabled"},
        {"type": "adaptive"},
    ):
        raise ModelCapacityRefused(operation, "capacity_payload_unsupported")
    body.update(extra)
    messages = body.get("messages")
    if (
        body.get("model") != model
        or set(body).intersection(
            {"audio", "modalities", "input_audio", "video", "image", "file"}
        )
        or not isinstance(messages, list)
        or any(
            not isinstance(message, dict)
            or (
                message.get("content") is not None
                and not isinstance(message["content"], str)
            )
            or any(message.get(key) is not None for key in ("audio", "image_url", "video"))
            for message in messages
        )
    ):
        raise ModelCapacityRefused(operation, "capacity_payload_unsupported")
    limits = [
        body[key] for key in ("max_tokens", "max_completion_tokens") if key in body
    ]
    if len(limits) > 1 or any(type(value) is not int or value <= 0 for value in limits):
        raise ModelCapacityRefused(operation, "capacity_payload_unsupported")
    requested_output = limits[0] if limits else None
    output_reserve = (
        requested_output if requested_output is not None else capacity.max_output_tokens
    )
    envelope_sha256 = None
    estimator_version = "ascii_json_bytes_v1"
    try:
        serialized = _utf8_json(body)
        if operation in {"agent_interaction_turn", "conversation_history_compaction"}:
            estimator_version = "utf8_json_density_v1"
            input_tokens = (len(serialized) + 3) // 4
        else:
            input_tokens = len(json.dumps(
                _normalized_text_payload(body),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ))
        if operation == "agent_interaction_turn":
            envelope = _utf8_json({key: value for key, value in body.items() if key != "messages"})
            envelope_sha256 = sha256(envelope).hexdigest()
    except (TypeError, ValueError, UnicodeError):
        raise ModelCapacityRefused(operation, "capacity_payload_unsupported") from None
    check = ModelCapacityCheck(
        operation=operation,
        provider_host=provider_host,
        model=model,
        payload_sha256=sha256(serialized).hexdigest(),
        estimator_version=estimator_version,
        envelope_sha256=envelope_sha256,
        serialized_body_bytes=len(serialized),
        estimated_input_tokens=input_tokens,
        requested_output_tokens=requested_output,
        output_reserve_tokens=output_reserve,
        protocol_reserve_tokens=capacity.protocol_reserve_tokens,
        context_window_tokens=capacity.context_window_tokens,
    )
    if output_reserve > capacity.max_output_tokens:
        raise ModelCapacityRefused(operation, "output_capacity_exceeded", check=check)
    if (
        input_tokens + output_reserve + capacity.protocol_reserve_tokens
        > capacity.context_window_tokens
    ):
        raise ModelCapacityRefused(operation, "context_capacity_exceeded", check=check)
    return check
