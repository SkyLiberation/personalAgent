"""Replay a complete captured SDK stage against a local HTTP fault boundary.

Only the external server is substituted. This is an Offline Eval of transport
observability, with no model generation, tool execution or Product E2E claim.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from time import sleep
from typing import Any

from pydantic import BaseModel, ConfigDict


class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case: str
    physical_requests: int
    wire_sha256: str
    wire_unchanged: bool
    qualified: bool
    public_message: str | None = None
    diagnostics: dict[str, Any] | None = None  # Serialized external-version contract.
    response_unchanged: bool | None = None


def _save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _worker(args: argparse.Namespace) -> None:
    from openai.types.chat import ChatCompletion

    if args.role == "before":
        # The sealed historical source retains its original public error name.
        from personal_agent.application.conversation.errors import ConversationUnavailable as ConversationFailure
    else:
        from personal_agent.application.conversation.errors import ConversationFailure
        from personal_agent.infra.structured_model import _ProviderCompletion
    from personal_agent.application.conversation.service import ConversationService
    from personal_agent.capabilities.contracts.model import ModelInvocationUnavailable, StructuredModelRequest
    from personal_agent.infra.structured_model import OpenAIModelClient
    from personal_agent.kernel.config_models import StructuredConfig
    import personal_agent.infra.structured_model as implementation

    source = args.before_source if args.role == "before" else Path.cwd() / "src"
    assert Path(implementation.__file__).resolve().is_relative_to(source.resolve())
    candidates = list(args.capture.glob("*.candidate.response.json"))
    failed = [path for path in candidates if not json.loads(path.read_bytes())["completed"]]
    assert len(failed) == 1
    failure = json.loads(failed[0].read_bytes())
    request_file = failed[0].with_name(failed[0].name.replace(".response.", ".request."))
    wire = json.loads(request_file.read_bytes())
    original_bodies = list(args.capture.glob("*.http.request.json"))
    expected_value = {key: value for key, value in wire.items() if key != "extra_body"}
    expected_value.update(wire.get("extra_body") or {})
    matching = [path for path in original_bodies if json.loads(path.read_bytes()) == expected_value]
    assert len(matching) == 1 and not expected_value.get("stream")
    expected_bytes = matching[0].read_bytes()
    successes = [json.loads(path.read_bytes()) for path in candidates if json.loads(path.read_bytes())["completed"]]
    assert successes
    archived_response = successes[0]["response"]
    normal_bytes = json.dumps(archived_response, ensure_ascii=False).encode("utf-8")
    output = args.output / args.role
    output.mkdir(parents=True, exist_ok=False)
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.name.startswith("personal_agent"):
                records.append(record.getMessage())

    logging.getLogger().addHandler(Capture())
    logging.getLogger().setLevel(logging.INFO)
    if args.role == "candidate":
        from .retrieval_acceptance_server import install_acceptance_observer

        install_acceptance_observer(output / "sdk")
    key = "local-offline-api-key-DO-NOT-LOG"
    private = "local-offline-private-header-DO-NOT-LOG"
    cases: list[ReplayCase] = []
    for scenario in ("body_disconnect", "redirect_body_disconnect", "complete_response"):
        sent: list[bytes] = []
        log_start = len(records)

        class Fixture(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *values: object) -> None:
                pass

            def do_POST(self) -> None:
                sent.append(self.rfile.read(int(self.headers["content-length"])))
                if scenario == "redirect_body_disconnect" and self.path == "/v1/chat/completions":
                    self.send_response(307)
                    self.send_header("Location", "/v1/redirected/chat/completions")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Request-Id", "offline-body-fixture")
                self.send_header("Set-Cookie", private)
                self.send_header("X-Private-Fixture", private)
                if scenario != "complete_response":
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for chunk in (b"\n", b" ", b'{"id":"incomplete-external-fixture"'):
                        self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                        self.wfile.flush()
                        sleep(0.01)
                    # Deliberately omit the terminal chunk. HTTPX must produce
                    # the actual RemoteProtocolError rather than a fake SDK error.
                    self.close_connection = True
                else:
                    self.send_header("Content-Length", str(len(normal_bytes)))
                    self.end_headers()
                    self.wfile.write(normal_bytes)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        adapter = OpenAIModelClient(StructuredConfig(api_key=key, base_url=f"http://127.0.0.1:{port}/v1",
            model=wire["model"], timeout_seconds=480))
        sdk = adapter._client()
        assert sdk.max_retries == 0

        class HistoricalStage:
            def generate(self, request):
                return adapter._create_chat_completion(sdk, request.operation, wire)

        request = StructuredModelRequest(operation=failure["operation"], version="captured-sdk-stage",
            messages=wire["messages"], output_type=BaseModel,
            context_projection_ref="historical:longds-mimo-20261023/7e50c5bb4e9748f6b14c4709cdff5ec7",
            max_tokens=32768)
        try:
            try:
                try:
                    response = HistoricalStage().generate(request)
                except ModelInvocationUnavailable as failure_error:
                    raise ConversationService._model_failure(failure_error,
                        message="conversation model is temporarily unavailable", failure_stage="provider_request",
                        component="conversation") from failure_error
            except ConversationFailure as error:
                assert scenario != "complete_response"
                assert str(error) == "conversation model is temporarily unavailable"
                assert error.reason_code == "provider_transport" and error.retryable
                assert error.provider_status_code is None
                diagnostics = error.provider_diagnostics.model_dump(mode="json", exclude_none=True) if error.provider_diagnostics else {}
                transport = diagnostics.get("transport") or {}
                chain = diagnostics.get("exception_chain") or []
                types = [frame["exception_type"] for frame in chain]
                qualified = bool(transport.get("status_code") == 200 and transport.get("headers_seconds") is not None
                    and 0 <= transport["headers_seconds"] <= transport.get("first_byte_seconds", -1)
                    <= transport.get("last_byte_seconds", -1) <= transport.get("elapsed_seconds", -1)
                    and transport.get("body_bytes", 0) > 0 and transport.get("body_chunks", 0) > 0
                    and transport.get("closed") and not transport.get("body_complete")
                    and transport.get("connect_host") in (None, "127.0.0.1") and transport.get("connect_port") in (None, port)
                    and transport.get("peer_host") == "127.0.0.1" and transport.get("peer_port") == port
                    and transport.get("failure_phase", "").endswith("receive_response_body.failed")
                    and diagnostics.get("request_id") == "offline-body-fixture"
                    and any(name.endswith(".RemoteProtocolError") for name in types)
                    and any("incomplete chunked read" in (frame.get("message") or "") for frame in chain))
                projected = [json.loads(line.split(" | ", 1)[1])["provider_diagnostics"] for line in records[log_start:]
                             if line.startswith("conversation.model_failure | ") and "provider_diagnostics" in line]
                qualified = qualified and projected == [diagnostics]
                if scenario == "redirect_body_disconnect" and args.role == "candidate":
                    redirect_closed = [json.loads(line.split(" | ", 1)[1])["transport"] for line in records[log_start:]
                                       if line.startswith("llm.http.body_closed | ")
                                       and json.loads(line.split(" | ", 1)[1])["transport"].get("status_code") == 307]
                    qualified = qualified and len(redirect_closed) == 1 and not redirect_closed[0].get("failure_phase")
                cases.append(ReplayCase(case=scenario, physical_requests=len(sent), wire_sha256=sha256(sent[0]).hexdigest(),
                    wire_unchanged=all(body == expected_bytes for body in sent), qualified=qualified, public_message=str(error), diagnostics=diagnostics))
            else:
                assert scenario == "complete_response"
                if args.role == "before":
                    payload = response
                else:
                    completion: _ProviderCompletion = response
                    payload = completion.payload
                unchanged = payload.model_dump(mode="json") == ChatCompletion.model_validate(archived_response).model_dump(mode="json")
                closed = [json.loads(line.split(" | ", 1)[1])["transport"] for line in records[log_start:]
                          if line.startswith("llm.http.body_closed | ")]
                qualified = unchanged and (args.role == "before" or (len(closed) == 1
                    and closed[0]["body_complete"] and closed[0]["closed"] and closed[0]["body_bytes"] == len(normal_bytes)))
                cases.append(ReplayCase(case=scenario, physical_requests=len(sent), wire_sha256=sha256(sent[0]).hexdigest(),
                    wire_unchanged=sent == [expected_bytes], qualified=qualified, response_unchanged=unchanged))
        finally:
            sdk.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        assert cases[-1].physical_requests == (2 if scenario == "redirect_body_disconnect" else 1) and cases[-1].wire_unchanged
        text = "\n".join(records[log_start:])
        assert key not in text and private not in text and wire["messages"][0]["content"] not in text
    if args.role == "candidate":
        from .retrieval_capture_audit import HttpSendObservation, SdkResponseObservation

        http = [HttpSendObservation.model_validate_json(path.read_bytes()) for path in (output / "sdk").glob("*.http.response.json")]
        sdk_records = [SdkResponseObservation.model_validate_json(path.read_bytes()) for path in (output / "sdk").glob("*.candidate.response.json")]
        assert len(http) == len(sdk_records) == 3
        for interrupted in (item for item in http if item.exception_type):
            assert not interrupted.response_received and interrupted.transport.status_code == 200
            assert interrupted.transport.body_bytes > 0 and not interrupted.transport.body_complete
            assert any(item.provider_diagnostics.transport.attempt_id == interrupted.transport.attempt_id
                       for item in sdk_records if not item.completed)
    (output / "events.log").write_text("\n".join(records), encoding="utf-8")
    _save(output / "result.json", {"role": args.role, "cases": [case.model_dump() for case in cases], "paid_calls": 0})
    print(args.role, [case.qualified for case in cases])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--before-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", choices=("before", "candidate"))
    args = parser.parse_args()
    if args.role:
        _worker(args)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    for role, source in (("before", args.before_source), ("candidate", Path.cwd() / "src")):
        env = {**os.environ, "PYTHONPATH": str(source.resolve()), "PYTHON_DOTENV_DISABLED": "1", "PYTHONUTF8": "1",
               "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}
        result = subprocess.run([sys.executable, "-m", "evals.product_baselines.model_transport_diagnostics", *sys.argv[1:], "--role", role],
                                env=env, capture_output=True, text=True, encoding="utf-8", timeout=1000)
        (args.output / f"{role}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"{role} Offline Eval failed; see {args.output / (role + '.log')}")
    before = json.loads((args.output / "before/result.json").read_bytes())
    candidate = json.loads((args.output / "candidate/result.json").read_bytes())
    assert [case["qualified"] for case in before["cases"]] == [False, False, True]
    assert [case["qualified"] for case in candidate["cases"]] == [True, True, True]
    assert [case["wire_sha256"] for case in before["cases"]] == [case["wire_sha256"] for case in candidate["cases"]]
    _save(args.output / "summary.json", {"evidence_class": "offline_real_stage_transport_replay", "samples": 3,
        "repetitions_per_version": 1, "before_qualified": 1, "candidate_qualified": 3, "paid_calls": 0,
        "tool_executions": 0, "limitation": "本机 HTTP 故障反事实，不证明原 MiMo 断连方或长任务通过。",
        "before": before, "candidate": candidate})
    print("Offline Eval: before 1/3; candidate 3/3; paid calls 0")


if __name__ == "__main__":
    main()
