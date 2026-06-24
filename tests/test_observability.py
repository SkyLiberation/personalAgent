from __future__ import annotations

import logging

from personal_agent.application.verifier import AnswerVerifier
from personal_agent.tools import InMemoryToolAuditSink, ToolExecutor

from tests.test_tools import echo


def test_verifier_emits_structured_observability(caplog):
    verifier = AnswerVerifier()

    with caplog.at_level(logging.INFO, logger="personal_agent.kernel.observability"):
        result = verifier.verify(
            "问题",
            "一个没有证据的答案",
            [],
            [],
            run_id="run-1",
            thread_id="u1:s1",
            user_id="u1",
            step_id="verify-1",
        )

    assert result.ok is True
    messages = [record.getMessage() for record in caplog.records]
    verifier_logs = [message for message in messages if "verifier.result" in message]
    assert verifier_logs
    assert '"prompt_name": "verifier"' in verifier_logs[0]
    assert '"question_chars": 2' in verifier_logs[0]
    assert '"answer_chars": 9' in verifier_logs[0]
    assert "一个没有证据的答案" not in verifier_logs[0]


def test_tool_gateway_emits_audit_event(caplog):
    sink = InMemoryToolAuditSink()
    executor = ToolExecutor(audit_sink=sink)
    executor.register(echo)

    with caplog.at_level(logging.INFO, logger="personal_agent.kernel.observability"):
        result = executor.invoke_direct("echo", message="hello", user_id="u1")

    assert result["ok"] is True
    assert len(sink.events) == 1
    messages = [record.getMessage() for record in caplog.records]
    assert any("tool.audit" in message and '"tool_name": "echo"' in message for message in messages)
    assert any("metric" in message and '"metric_name": "tool.invocation"' in message for message in messages)
