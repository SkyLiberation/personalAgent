"""Drive the real LongDS request and tools with a controlled localhost model response."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread


MODEL = "longds-filesystem-preflight"
KEY = "longds-preflight-local-key"
PROMPT = "检查本次 LongDS 运行的文件工具和 Bash 能否共同访问任务沙箱。"
FINAL = "LongDS filesystem preflight completed."
TOOLS = {"bash", "read", "write", "edit"}


@dataclass(frozen=True)
class ProbeCall:
    name: str
    arguments: dict[str, object]
    result_text: str
    error: bool = False


def bash(command: str, result_text: str, *, workdir: str | None = None) -> ProbeCall:
    arguments = {"command": command, "description": "Verify filesystem isolation"}
    if workdir is not None:
        arguments["workdir"] = workdir
    return ProbeCall("bash", arguments, result_text)


CALLS = (
    bash("set -eu; test \"$PWD\" = /workspace; test -z \"${DSH_EVAL_PROVIDER_KEY-}\"; "
         "test ! -e /var/run/docker.sock; test ! -e /workspace/evaluator-private; "
         "test ! -e /dsh-config/provider.env; test ! -w /workspace; "
         "test \"$(tail -n +3 /proc/net/dev | wc -l)\" -eq 1; "
         "printf 'probe-original\\n' >/tmp/original.txt; printf 'sandbox-ok\\n'", "sandbox-ok"),
    ProbeCall("read", {"file_path": "/tmp/original.txt"}, "probe-original"),
    ProbeCall("edit", {"file_path": "/tmp/original.txt", "old_string": "probe-original",
                      "new_string": "已编辑"}, "updated successfully"),
    ProbeCall("write", {"file_path": "/tmp/native/subdir/created.txt", "content": "原生写入\n"}, "created"),
    bash("set -eu; test \"$PWD\" = /tmp; grep -Fx '已编辑' original.txt; "
         "grep -Fx '原生写入' /tmp/native/subdir/created.txt; "
         "python -c \"from pathlib import Path; tail = (b'x'*2047 + bytes([10]))*5121; "
         "Path('/tmp/window.txt').write_bytes(b'stream-window' + bytes([10]) + tail); "
         "Path('/tmp/invalid-utf8.txt').write_bytes(bytes([255]) + tail)\"; printf 'shared-ok\\n'",
         "shared-ok", workdir="/tmp"),
    bash("set -eu; test \"$PWD\" = /tmp/native/subdir; grep -Fx '原生写入' created.txt",
         "原生写入", workdir="../tmp/native/subdir"),
    ProbeCall("read", {"file_path": "/tmp/window.txt", "limit": 1}, "Showing lines 1-1 of 5122."),
    ProbeCall("read", {"file_path": "/tmp/invalid-utf8.txt", "limit": 1}, "invalid UTF-8 text", True),
    ProbeCall("read", {"file_path": "/dsh-config/provider.env"}, "provider.env", True),
    ProbeCall("read", {"file_path": "../evaluator-private/task.json"}, "task.json", True),
    ProbeCall("write", {"file_path": "blocked.txt", "content": "unexpected"}, "blocked.txt", True),
)


def response_chunks(index: int) -> bytes:
    header = {"id": f"preflight-response-{index}", "object": "chat.completion.chunk", "created": 1, "model": MODEL}
    if index < len(CALLS):
        call = CALLS[index]
        delta = {"role": "assistant", "tool_calls": [{
            "index": 0, "id": f"call_preflight_{index}", "type": "function",
            "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)},
        }]}
        reason = "tool_calls"
    else:
        delta = {"role": "assistant", "content": FINAL}
        reason = "stop"

    def chunk(content: dict, finish_reason: str | None) -> dict:
        return {**header, "choices": [{"index": 0, "delta": content, "finish_reason": finish_reason}]}

    frames = (
        chunk(delta, None),
        {**chunk({}, reason), "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
    )
    return ("".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n").encode()


class FilesystemPreflight:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.base_url = ""

    def run(self, session, output) -> None:
        result = session.run(PROMPT)
        evidence = {
            "kind": "controlled_provider_tool_preflight", "calls": [],
            "wire_requests": self.requests, "finish_reason": result.finish_reason,
        }
        try:
            if result.finish_reason != "completed" or result.final_response != FINAL:
                raise ValueError(f"Unexpected preflight termination: {result.finish_reason}")
            if len(self.requests) != len(CALLS) + 1:
                raise ValueError(f"Unexpected model request count: {len(self.requests)}")
            for request in self.requests:
                tools = {row["function"]["name"] for row in request["tools"]}
                if tools != TOOLS:
                    raise ValueError(f"Unexpected model-visible tools: {sorted(tools)}")
            replies = [event["data"]["message"] for event in result.events if event["type"] == "tool/result"]
            if len(replies) != len(CALLS):
                raise ValueError(f"Unexpected native tool reply count: {len(replies)}")
            for index, (call, reply) in enumerate(zip(CALLS, replies, strict=True)):
                text = "\n".join(part["text"] for part in reply["content"] if part["type"] == "text")
                evidence["calls"].append({"name": call.name, "is_error": reply["isError"], "result": text})
                if (reply["toolCallId"] != f"call_preflight_{index}" or reply["isError"] != call.error
                        or call.result_text.casefold() not in text.casefold()):
                    raise ValueError(f"Unexpected preflight tool result {index + 1} ({call.name}): {text}")
        finally:
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")


@contextmanager
def local_preflight():
    probe = FilesystemPreflight()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            index = len(probe.requests)
            probe.requests.append(body)
            data = response_chunks(index)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    with HTTPServer(("0.0.0.0", 0), Handler) as server:
        probe.base_url = f"http://host.docker.internal:{server.server_port}/v1"
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield probe
        finally:
            server.shutdown()
            thread.join()
