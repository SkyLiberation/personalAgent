from __future__ import annotations

from copy import deepcopy
from typing import Any

# 审计 payload 中需要脱敏的字段：用户内容、工具产出、证据明细。治理结构字段
# （tool_name / risk_level / side_effects / artifact_ok / error_kind / latency 等）
# 始终保留，因为它们是排查与合规追溯的骨架，且不含用户敏感内容。
_REDACTED_INPUT_KEYS: frozenset[str] = frozenset(
    {
        "text",
        "content",
        "summary",
        "title",
        "message",
        "query",
        "answer",
        "url",
        "delete_reason",
        "note_id",
        "snapshot_id",
        "target",
        "file_path",
    }
)


def _mask(value: Any) -> str:
    """Replace a sensitive value with a length-preserving placeholder."""
    text = value if isinstance(value, str) else str(value)
    return f"<redacted:{len(text)} chars>"


def _redact_mapping(payload: dict[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key in keys and value is not None:
            redacted[key] = _mask(value)
        else:
            redacted[key] = value
    return redacted


def redact_audit_payload(payload: dict[str, Any], *, reveal: bool) -> dict[str, Any]:
    """Return a copy of a tool audit payload with user content masked.

    ``reveal=True`` (admin contexts only) returns the payload unchanged. By
    default the user-supplied ``input`` fields, the tool ``output.data`` and any
    ``evidence`` are masked so audit queries never leak knowledge content or PII
    while still exposing the governance shape of the call.
    """
    if reveal:
        return payload
    redacted = deepcopy(payload)

    raw_input = redacted.get("input")
    if isinstance(raw_input, dict):
        redacted["input"] = _redact_mapping(raw_input, _REDACTED_INPUT_KEYS)

    output = redacted.get("output")
    if isinstance(output, dict):
        if output.get("data") is not None:
            output["data"] = _mask(output["data"])
        if output.get("evidence"):
            output["evidence"] = f"<redacted:{len(output['evidence'])} items>"

    if redacted.get("evidence"):
        redacted["evidence"] = f"<redacted:{len(redacted['evidence'])} items>"

    return redacted
