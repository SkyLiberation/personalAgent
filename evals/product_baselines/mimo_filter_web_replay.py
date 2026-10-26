"""One formal-Web fault replay; only external model HTTP responses are fixtures."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from dotenv import load_dotenv

from personal_agent.application.conversation.journal import FileInteractionJournal
from .mimo_tool_stream_replay import chunks, load, valid_response
from .run_longds import baseline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    history = root / ".tmp/research-mimo-longds-20261023/l2-prefix-17/sdk"
    intent = None
    for path in history.glob("*.candidate.response.json"):
        record = load(path)
        response = record.get("response")
        request = path.with_name(path.name.replace(".response.", ".request."))
        if response and not load(request).get("tools"):
            intent = response
            break
    assert intent is not None
    _, filtered = valid_response(history)
    filtered = json.loads(json.dumps(filtered))
    filtered["choices"][0]["finish_reason"] = "content_filter"
    seen = []

    class Fixture(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *values):
            pass

        def do_POST(self):
            assert urlsplit(self.path).hostname == "token-plan-cn.xiaomimimo.com"
            request = json.loads(self.rfile.read(int(self.headers["content-length"])))
            response = filtered if request.get("tools") else intent
            seen.append(response)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for frame in chunks(response):
                data = b"data: " + json.dumps(frame, ensure_ascii=False).encode() + b"\n\n"
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
            self.wfile.write(b"e\r\ndata: [DONE]\n\n\r\n0\r\n\r\n")
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    load_dotenv(root / ".env", override=True)
    os.environ.update(HTTP_PROXY=f"http://127.0.0.1:{server.server_address[1]}", NO_PROXY="127.0.0.1",
        PYTHON_DOTENV_DISABLED="1", PERSONAL_AGENT_ANSWER_RESULT='{"writer":"direct","verification":"none"}',
        PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS="480", PERSONAL_AGENT_STRUCTURED_MAX_RETRIES="0",
        PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS="40", PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS="256",
        PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS="4", PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS="10000000")
    for prefix in ("STRUCTURED", "OPENAI"):
        os.environ[prefix + "_MODEL"] = "mimo-v2.6-flash"
        os.environ[prefix + "_BASE_URL"] = "http://token-plan-cn.xiaomimimo.com/v1"
        os.environ[prefix + "_API_KEY"] = "local-offline-key"
        os.environ[prefix + "_MODEL_CAPACITY"] = json.dumps({"provider_host": "token-plan-cn.xiaomimimo.com",
            "model": "mimo-v2.6-flash", "context_window_tokens": 1000000, "max_output_tokens": 131072,
            "protocol_reserve_tokens": 8192})
    try:
        result = baseline(root / ".tmp/longds-implementation-20261023/materials", args.output,
            purpose="target", user_turns=2,
            python_image_id="sha256:510b3b843826cf0bb0684f73e33171ef96735856d2f6569c7a235a2426678755",
            docker_endpoint="npipe:////./pipe/dockerDesktopLinuxEngine")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    request = load(args.output / "turn-01.request.json")
    trace = FileInteractionJournal(args.output / "server-data/interaction_runs").get(request["interaction_run_ref"])
    assert result.actual_process_stopped and result.answered_turns == 0 and result.requested_turns == 1
    assert result.unknown_usage_attempts == 0 and trace.usage.provider_usage_complete
    assert result.known_tokens == trace.usage.total_tokens == sum(response["usage"]["total_tokens"] for response in seen)
    assert not trace.accepted_tool_requests and len(seen) == 2
    assert load(args.output / "turn-01.http.json")["status_code"] == 503
    log = (args.output / "server.log").read_text(encoding="utf-8")
    assert '"provider_response_complete": true' in log and '"reason_code": "provider_rejected"' in log
    print(json.dumps({"evidence_class": "offline_formal_web_external_filter_fault", "passed": 1,
        "samples": 1, "loopback_model_requests": len(seen), "journal_known_tokens": trace.usage.total_tokens,
        "unknown_usage_attempts": 0, "paid_model_calls": 0, "tool_executions": 0}))


if __name__ == "__main__":
    main()
