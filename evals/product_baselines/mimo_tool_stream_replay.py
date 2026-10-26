"""Offline replay of complete LongDS SDK stages against a local SSE boundary."""

from __future__ import annotations

import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from pydantic import BaseModel

from personal_agent.capabilities.contracts.model import ModelActionDefinition, ModelInvocationUnavailable, StructuredModelRequest
from personal_agent.infra.structured_model import OpenAIModelClient
from personal_agent.kernel.config_models import StructuredConfig


def load(path: Path):
    return json.loads(path.read_bytes())


def chunks(response):
    base = {key: response[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    choice = response["choices"][0]
    message = choice["message"]

    def frame(delta, finish=None, *, usage=None):
        return {**base, "choices": ([{"index": 0, "delta": delta, "finish_reason": finish}] if usage is None else []),
                "usage": usage}

    yield frame({"role": "assistant", "content": ""})
    for field in ("reasoning_content", "content"):
        content = message.get(field) or ""
        for position in range(0, len(content), 257):
            yield frame({field: content[position:position + 257]})
    for index, call in enumerate(message.get("tool_calls") or []):
        function = call["function"]
        yield frame({"tool_calls": [{"index": index, "id": call["id"], "type": "function",
                                    "function": {"name": function["name"], "arguments": ""}}]})
        for position in range(0, len(function["arguments"]), 257):
            yield frame({"tool_calls": [{"index": index, "function": {"arguments": function["arguments"][position:position + 257]}}]})
    yield frame({}, choice["finish_reason"])
    yield frame({}, usage=response["usage"])


def valid_response(directory: Path, name: str | None = None):
    for path in sorted(directory.glob("*.candidate.response.json")):
        response = load(path).get("response")
        if not response or not response.get("usage"):
            continue
        calls = response["choices"][0]["message"].get("tool_calls") or []
        if not calls or not all(call["function"]["name"].startswith("tool_") for call in calls):
            continue
        if name and any(call["function"]["name"] != name for call in calls):
            continue
        try:
            for call in calls:
                assert isinstance(json.loads(call["function"]["arguments"]), dict)
        except (ValueError, TypeError, AssertionError):
            continue
        return path, response
    raise ValueError("历史原件缺可用完整工具响应")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    capture = Path(".tmp/research-mimo-longds-20261023")
    failed = capture / "l2-prefix-17/sdk/7e50c5bb4e9748f6b14c4709cdff5ec7.candidate.request.json"
    invalid = capture / "l1-mimo-flow/sdk/199d0213a9264625b079107d41eca115.candidate.response.json"
    valid_file, good = valid_response(capture / "l2-prefix-17/sdk")
    repaired_file, repaired = valid_response(capture / "l1-mimo-flow/sdk", "tool_execute_python")
    bad = load(invalid)["response"]
    bad_request = invalid.with_name(invalid.name.replace(".response.", ".request."))
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            if record.name.startswith("personal_agent"):
                records.append(record.getMessage())

    logging.getLogger().addHandler(Capture())
    logging.getLogger().setLevel(logging.INFO)
    reports = []
    for scenario in ("complete_fragments", "invalid_json_repair", "stream_disconnect", "content_filter"):
        wire = load(bad_request if scenario == "invalid_json_repair" else failed)
        fixtures = [bad, repaired] if scenario == "invalid_json_repair" else [good]
        if scenario == "content_filter":
            filtered = json.loads(json.dumps(good))
            filtered["choices"][0]["finish_reason"] = "content_filter"
            fixtures = [filtered]
        sent = []
        definitions = tuple(ModelActionDefinition(name=item["function"]["name"], kind="tool",
            target_name=item["function"]["name"], description=item["function"].get("description", ""),
            input_schema=item["function"]["parameters"]) for item in wire["tools"])
        request = StructuredModelRequest(operation="agent_interaction_turn", version="historical-full-sdk-stage",
            messages=wire["messages"], context_projection_ref="historical:longds-mimo-tool-stream",
            output_type=BaseModel, kind="tool_calling", action_definitions=definitions,
            action_choice="required", max_tokens=wire["max_completion_tokens"])
        log_start = len(records)

        class Fixture(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *values):
                pass

            def do_POST(self):
                assert urlsplit(self.path).hostname == "token-plan-cn.xiaomimimo.com"
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                sent.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.send_header("X-Request-Id", "local-stream-fixture")
                self.end_headers()
                response = fixtures[len(sent) - 1]
                for index, frame in enumerate(chunks(response)):
                    data = b"data: " + json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n\n"
                    self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                    self.wfile.flush()
                    if scenario == "stream_disconnect" and index == 1:
                        self.close_connection = True
                        return
                self.wfile.write(b"e\r\ndata: [DONE]\n\n\r\n0\r\n\r\n")
                self.wfile.flush()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        # Substitute only the external HTTP boundary. No DNS or MiMo requests:
        # the canonical host goes through this loopback HTTP proxy fixture.
        previous_proxy = os.environ.get("HTTP_PROXY")
        os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            adapter = OpenAIModelClient(StructuredConfig(api_key="local-stream-key", model=wire["model"],
                base_url="http://token-plan-cn.xiaomimimo.com/v1", timeout_seconds=480,
                extra_body=wire.get("extra_body") or {}))
            projected = adapter._chat_kwargs(request)
            expected = {key: value for key, value in wire.items() if key != "extra_body"}
            expected.update(wire.get("extra_body") or {})
            candidate = {key: value for key, value in projected.items() if key != "extra_body"}
            candidate.update(projected.get("extra_body") or {})
            assert candidate == {**expected, "stream": True, "stream_options": {"include_usage": True}, "tool_choice": "auto"}
            try:
                result = adapter.generate(request)
            except ModelInvocationUnavailable as error:
                if scenario == "content_filter":
                    from personal_agent.application.conversation.service import ConversationService

                    observation = {"category": error.category, "retryable": error.retryable,
                        "response_present": error.response is not None,
                        "provider_response_complete": getattr(error, "provider_response_complete", False),
                        "known_tokens": error.response.total_tokens if error.response else None}
                    (args.output / "filter-observation.json").write_text(json.dumps(observation, indent=2), encoding="utf-8")
                    assert error.category == "provider_rejected" and not error.retryable and len(sent) == 1
                    assert observation["provider_response_complete"] and error.response is not None
                    assert error.response.total_tokens == good["usage"]["total_tokens"]
                    assert not error.response.action_invocations
                    converted = ConversationService._model_failure(error, message="conversation model is temporarily unavailable",
                        failure_stage="provider_request", component="conversation")
                    assert converted.provider_response_complete and converted.response == error.response
                    outcome = observation
                else:
                    assert scenario == "stream_disconnect" and error.category == "provider_transport"
                    assert error.response is None and len(sent) == 1
                    assert not getattr(error, "provider_response_complete", False)
                    transport = error.diagnostics.transport
                    assert transport.status_code == 200 and transport.body_bytes > 0 and not transport.body_complete
                    assert transport.peer_host == "127.0.0.1" and transport.peer_port == server.server_address[1]
                    assert any(frame.exception_type.endswith("RemoteProtocolError") for frame in error.diagnostics.exception_chain)
                    outcome = {"category": error.category, "diagnostics": error.diagnostics.model_dump(mode="json")}
            else:
                assert scenario != "stream_disconnect"
                wanted = fixtures[-1]["choices"][0]["message"]["tool_calls"]
                assert [(call.call_id, call.name, call.arguments) for call in result.action_invocations] == [
                    (call["id"], call["function"]["name"], json.loads(call["function"]["arguments"])) for call in wanted]
                assert result.total_tokens == sum(item["usage"]["total_tokens"] for item in fixtures)
                assert len(sent) == len(fixtures)
                if scenario == "invalid_json_repair":
                    assert result.retry_errors == ["provider_action_arguments_invalid_json"]
                    feedback = sent[1]["messages"][0]["content"]
                    assert "provider_action_arguments_invalid_json" in feedback and "parsed_arguments" not in feedback
                    assert len(result.protocol_exchanges) == 1
                    original_assistant = result.protocol_exchanges[0].assistant
                    (args.output / "native-protocol-observation.json").write_text(json.dumps({
                        "actual": original_assistant.payload, "archived": bad["choices"][0]["message"]},
                        ensure_ascii=False, indent=2), encoding="utf-8")
                    assert original_assistant.payload["reasoning_content"] == bad["choices"][0]["message"]["reasoning_content"]
                    # This replay converts an archived nonstream response into
                    # SSE deltas. The SDK retains their actual call index.
                    assert original_assistant.payload["tool_calls"] == [
                        {**call, "index": index}
                        for index, call in enumerate(bad["choices"][0]["message"]["tool_calls"])]
                    native = sent[1]["messages"][len(request.messages) + 1:]
                    assert native[0] == original_assistant.payload
                    assert [message["tool_call_id"] for message in native[1:]] == list(original_assistant.call_ids)
                outcome = {"total_tokens_from_archived_fixtures": result.total_tokens,
                           "retry_errors": result.retry_errors, "action_count": len(result.action_invocations)}
            assert sent[0] == candidate
            if scenario != "stream_disconnect":
                assert not any(line.startswith("llm.http.failed") and "GeneratorExit" in line
                               for line in records[log_start:])
            reports.append({"case": scenario, "passed": True, "loopback_http_requests": len(sent), "outcome": outcome})
            (args.output / f"{scenario}.requests.json").write_text(json.dumps(sent, ensure_ascii=False, indent=2), encoding="utf-8")
            (args.output / f"{scenario}.events.log").write_text("\n".join(records[log_start:]), encoding="utf-8")
        finally:
            if previous_proxy is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = previous_proxy
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)
    summary = {"evidence_class": "offline_full_sdk_stage_sse_replay", "passed": len(reports), "samples": 4,
        "cases": reports, "paid_model_calls": 0, "tool_executions": 0,
        "sources": {str(path): sha256(path.read_bytes()).hexdigest() for path in (failed, invalid, bad_request, valid_file, repaired_file)},
        "limitation": "完整真实SDK阶段、本机外部响应反事实；不代表真实模型修复语义、MiMo根因或Product E2E。"}
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MiMo tool SSE Offline Eval: 4/4; paid calls 0; tool executions 0")


if __name__ == "__main__":
    main()
