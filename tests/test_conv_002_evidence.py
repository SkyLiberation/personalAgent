from __future__ import annotations

from urllib.error import HTTPError

from evals.product_baselines.test_conv_002_agent_initiated_working_plan import (
    _request_failure_fields,
    _tool_failure_fields,
)


def test_conv_002_classifies_provider_http_failure() -> None:
    error = HTTPError(
        url="https://example.test/v1/chat/completions",
        code=400,
        msg="bad request",
        hdrs=None,
        fp=None,
    )

    assert _request_failure_fields(error) == {
        "failure_class": "provider_failure",
        "failure_reason": "http_error",
        "exception_type": "HTTPError",
        "http_status": 400,
    }


def test_conv_002_classifies_client_timeout_without_calling_it_provider_failure() -> None:
    fields = _request_failure_fields(TimeoutError("request deadline exceeded"))

    assert fields == {
        "failure_class": "request_timeout",
        "failure_reason": "client_deadline_exceeded",
        "exception_type": "TimeoutError",
        "http_status": None,
    }


def test_conv_002_preserves_mixed_provider_and_execution_tool_failures() -> None:
    fields = _tool_failure_fields([
        {"payload": {"error_kind": "transient"}},
        {"payload": {"error_kind": "transient"}},
        {"payload": {"error_kind": "execution_failure"}},
    ])

    assert fields == {
        "failure_class": "provider_failure",
        "failed_tool_result_count": 3,
        "failed_tool_error_kind_counts": {
            "execution_failure": 1,
            "transient": 2,
        },
    }


def test_conv_002_does_not_call_local_tool_failure_a_provider_failure() -> None:
    fields = _tool_failure_fields([
        {"payload": {"error_kind": "execution_failure"}},
    ])

    assert fields["failure_class"] == "execution_failure"
