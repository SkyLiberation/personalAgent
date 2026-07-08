from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.request import Request, urlopen

from personal_agent.kernel.config_models import GPTResearcherA2AConfig


class A2AError(RuntimeError):
    """Transport or protocol error returned by an A2A JSON-RPC agent."""


@dataclass(frozen=True, slots=True)
class A2AResearchResponse:
    task_id: str
    context_id: str
    state: str
    report: str
    artifacts: list[dict[str, Any]]
    metadata: dict[str, Any]
    raw: dict[str, Any]


class GPTResearcherA2AClient:
    """Minimal JSON-RPC client for the GPT Researcher A2A backend."""

    def __init__(self, config: GPTResearcherA2AConfig) -> None:
        self.config = config
        self._next_id = 1

    def agent_card(self) -> dict[str, Any]:
        request = Request(
            self.config.agent_card_url,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return _decode_json(response.read())
        except OSError as exc:
            raise A2AError(f"GPT Researcher A2A agent card request failed: {exc}") from exc

    def research(
        self,
        *,
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
        blocking: bool = True,
    ) -> A2AResearchResponse:
        topic = topic.strip()
        if not topic:
            raise ValueError("GPT Researcher A2A topic is required.")
        metadata: dict[str, Any] = {
            "report_type": report_type or self.config.report_type,
            "report_source": report_source or self.config.report_source,
            "tone": tone or self.config.tone,
        }
        if max_search_results is not None:
            metadata["max_search_results"] = max_search_results
        elif self.config.max_search_results is not None:
            metadata["max_search_results"] = self.config.max_search_results
        result = self._rpc("message/send", {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": topic}],
                "metadata": metadata,
            },
            "configuration": {"blocking": blocking},
        })
        if not isinstance(result, dict):
            raise A2AError("GPT Researcher A2A returned a non-object task result.")
        return _research_response_from_task(result)

    def submit_research(
        self,
        *,
        topic: str,
        report_type: str | None = None,
        report_source: str | None = None,
        tone: str | None = None,
        max_search_results: int | None = None,
    ) -> A2AResearchResponse:
        return self.research(
            topic=topic,
            report_type=report_type,
            report_source=report_source,
            tone=tone,
            max_search_results=max_search_results,
            blocking=False,
        )

    def get_task(self, task_id: str) -> A2AResearchResponse:
        result = self._rpc("tasks/get", {"id": task_id})
        if not isinstance(result, dict):
            raise A2AError("GPT Researcher A2A returned a non-object task result.")
        return _research_response_from_task(result)

    def cancel_task(self, task_id: str) -> A2AResearchResponse:
        result = self._rpc("tasks/cancel", {"id": task_id})
        if not isinstance(result, dict):
            raise A2AError("GPT Researcher A2A returned a non-object task result.")
        return _research_response_from_task(result)

    def stream_task(self, task_id: str) -> Iterator[dict[str, Any]]:
        response = self.get_task(task_id)
        if response.report:
            yield {
                "kind": "text",
                "text": response.report,
                "task_id": response.task_id,
                "state": response.state,
            }

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        request_id = f"gpt-researcher-{self._next_id}"
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.config.endpoint,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                decoded = _decode_json(response.read())
        except OSError as exc:
            raise A2AError(f"GPT Researcher A2A request failed: {exc}") from exc
        if decoded.get("jsonrpc") != "2.0":
            raise A2AError("GPT Researcher A2A returned an invalid JSON-RPC response.")
        error = decoded.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "GPT Researcher A2A request failed.")
            raise A2AError(message)
        return decoded.get("result")


def _decode_json(raw: bytes) -> dict[str, Any]:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise A2AError("GPT Researcher A2A returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise A2AError("GPT Researcher A2A returned a non-object JSON payload.")
    return decoded


def _research_response_from_task(task: dict[str, Any]) -> A2AResearchResponse:
    artifacts = task.get("artifacts") if isinstance(task.get("artifacts"), list) else []
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    status = task.get("status") if isinstance(task.get("status"), dict) else {}
    report = ""
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        for part in artifact.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "text" and isinstance(part.get("text"), str):
                report = part["text"]
                break
        if report:
            break
    if not report:
        message = status.get("message") if isinstance(status.get("message"), dict) else {}
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "text" and isinstance(part.get("text"), str):
                report = part["text"]
                break
    return A2AResearchResponse(
        task_id=str(task.get("id") or ""),
        context_id=str(task.get("contextId") or ""),
        state=str(status.get("state") or ""),
        report=report,
        artifacts=[item for item in artifacts if isinstance(item, dict)],
        metadata=metadata,
        raw=task,
    )


__all__ = ["A2AError", "A2AResearchResponse", "GPTResearcherA2AClient"]
