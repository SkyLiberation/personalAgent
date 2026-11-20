"""Local MCP destination for the public ambiguous-effect workload."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Event, Thread
from time import perf_counter_ns
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError


EFFECT_ID = "effect-1"
WRITE = "apply_effect"
READ = "read_effect"
ToolName = Literal["apply_effect", "read_effect"]
DESCRIPTIONS = {
    WRITE: "提交指定操作并返回回执。每次调用都新增一条记录。",
    READ: "按操作编号查询目标端已经提交的回执。只读取状态。",
}


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effect_id: Literal["effect-1"]


class ToolCall(BaseModel):
    name: ToolName
    arguments: ToolArguments


class DestinationCall(BaseModel):
    operation: ToolName
    sequence: int
    receipt: str | None
    recorded_ns: int


class Destination:
    def __init__(self, database: Path, *, hold_reply: bool) -> None:
        self.database = database
        self.committed = Event()
        self.release_reply = Event()
        if not hold_reply:
            self.release_reply.set()
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("""CREATE TABLE calls (
                sequence INTEGER PRIMARY KEY, operation TEXT NOT NULL, receipt TEXT, recorded_ns INTEGER NOT NULL
            )""")

    def calls(self) -> list[DestinationCall]:
        with closing(sqlite3.connect(self.database)) as db:
            db.row_factory = sqlite3.Row
            return [DestinationCall.model_validate(dict(row)) for row in db.execute("SELECT * FROM calls ORDER BY sequence")]

    def execute(self, call: ToolCall) -> dict[str, Any]:
        receipt = uuid4().hex if call.name == WRITE else None
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                "INSERT INTO calls(operation, receipt, recorded_ns) VALUES(?, ?, ?)",
                (call.name, receipt, perf_counter_ns()),
            )
        if call.name == WRITE:
            self.committed.set()
            if not self.release_reply.wait(150):
                raise TimeoutError("Fault controller did not release the committed response")
            return {"effect_id": EFFECT_ID, "receipt": receipt}
        receipts = [event.receipt for event in self.calls() if event.operation == WRITE]
        return {"effect_id": EFFECT_ID, "receipts": receipts}


class RpcRequest(BaseModel):
    jsonrpc: Literal["2.0"]
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class DestinationServer(ThreadingHTTPServer):
    def __init__(self, destination: Destination) -> None:
        self.destination = destination
        super().__init__(("127.0.0.1", 0), DestinationRequest)


class DestinationRequest(BaseHTTPRequestHandler):
    server: DestinationServer

    def do_GET(self) -> None:
        self.send_response(405 if self.path == "/mcp" else 404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self.send_error(404)
            return
        request = None
        try:
            request = RpcRequest.model_validate_json(self.rfile.read(int(self.headers["Content-Length"])))
            if request.id is None:
                self.send_response(202)
                self.end_headers()
                return
            result = {"result": self.dispatch(request)}
        except (ValidationError, ValueError, TimeoutError, KeyError) as error:
            result = {"error": {"code": -32602, "message": str(error)}}
        data = json.dumps({"jsonrpc": "2.0", "id": request.id if request else None, **result}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return  # Expected after the fault controller stops the first client.

    def dispatch(self, request: RpcRequest) -> dict[str, Any]:
        match request.method:
            case "initialize":
                return {
                    "protocolVersion": (request.params or {}).get("protocolVersion", "2024-11-05"),
                    "serverInfo": {"name": "ambiguous-effect", "version": "1.0"},
                    "capabilities": {"tools": {}},
                }
            case "tools/list":
                return {"tools": [
                    {"name": name, "description": description, "inputSchema": ToolArguments.model_json_schema(),
                     "annotations": {"readOnlyHint": name == READ, "destructiveHint": False}}
                    for name, description in DESCRIPTIONS.items()
                ]}
            case "tools/call":
                payload = self.server.destination.execute(ToolCall.model_validate(request.params))
                return {"content": [{"type": "text", "text": json.dumps(payload)}]}
            case "ping":
                return {}
            case _:
                raise ValueError(f"Unknown MCP method: {request.method}")

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def serve(destination: Destination) -> Iterator[str]:
    with DestinationServer(destination) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/mcp"
        finally:
            destination.release_reply.set()
            server.shutdown()
            thread.join()
