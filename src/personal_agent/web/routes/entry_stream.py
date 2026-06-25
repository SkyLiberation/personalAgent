from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from personal_agent.orchestration.orchestration_models import _new_thread_id
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.models import EntryInput
from personal_agent.web.input_normalization import normalize_entry_text
from personal_agent.web.routes._shared import resolve_user_id
from personal_agent.web.routes.entry_serializers import chunk_answer, sse_event

logger = logging.getLogger(__name__)


def register_entry_stream_route(app: FastAPI, *, settings: Settings, service: AgentService) -> None:
    @app.get("/api/entry/stream")
    async def entry_stream(
        request: Request,
        text: str = "",
        user_id: str = "default",
        session_id: str = "default",
    ) -> StreamingResponse:
        normalized_text = normalize_entry_text(text)
        if not normalized_text:
            raise HTTPException(status_code=400, detail="Text is required.")

        resolved_user = user_id if user_id != "default" else resolve_user_id(request, settings)
        thread_id = _new_thread_id(resolved_user, session_id)
        logger.info(
            "Entry stream requested for user=%s session=%s thread_id=%s text=%s",
            resolved_user, session_id, thread_id, text[:120],
        )

        async def event_generator():
            entry_input = EntryInput(
                text=normalized_text,
                user_id=resolved_user,
                session_id=session_id,
                source_platform="web",
            )
            yield sse_event("status", {"message": "正在理解并执行请求..."})

            progress_queue: asyncio.Queue[tuple[str, dict[str, object]]] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            streamed_graph_events = False

            def _on_progress(event: str, payload: dict[str, object]) -> None:
                loop.call_soon_threadsafe(progress_queue.put_nowait, (event, payload))

            execution_task = asyncio.create_task(
                asyncio.to_thread(service.entry, entry_input, on_progress=_on_progress)
            )
            while not execution_task.done() or not progress_queue.empty():
                try:
                    evt, payload = await asyncio.wait_for(progress_queue.get(), timeout=0.05)
                except asyncio.TimeoutError:
                    continue
                streamed_graph_events = True
                yield sse_event(evt, payload)
            result = await execution_task

            if result.pending_confirmation:
                yield sse_event("intent", {
                    "intents": result.intents,
                    "reason": result.reason,
                })
                yield sse_event("confirmation_required", {
                    "run_id": result.run_id,
                    "pending_confirmation": result.pending_confirmation,
                })
                yield sse_event("done", {
                    "reply": result.reply_text,
                    "waiting_confirmation": True,
                    "run_id": result.run_id,
                })
                return

            if result.events and not streamed_graph_events:
                from personal_agent.orchestration.orchestration_models import (
                    AgentEvent,
                    events_to_sse_tuples,
                    execution_trace_from_events,
                )

                parsed_events = [AgentEvent.model_validate(e) for e in result.events]
                for sse_type, payload in events_to_sse_tuples(parsed_events):
                    if sse_type == "done":
                        continue
                    yield sse_event(sse_type, payload)

                if result.steps:
                    yield sse_event("steps_projected", {"steps": result.steps})
                derived_trace = execution_trace_from_events(parsed_events)
                if derived_trace:
                    yield sse_event("execution_trace", {"execution_trace": derived_trace})
            elif not result.events and not streamed_graph_events:
                if result.steps:
                    yield sse_event("steps_projected", {"steps": result.steps})

                if result.execution_trace:
                    yield sse_event("execution_trace", {"execution_trace": result.execution_trace})

            if streamed_graph_events and result.execution_trace:
                yield sse_event("execution_trace", {"execution_trace": result.execution_trace})

            if any(intent in ("capture_text", "capture_link", "capture_file") for intent in result.intents):
                capture_data = result.capture_result.model_dump(mode="json") if result.capture_result else None
                yield sse_event("capture_result", {
                    "note": capture_data.get("note") if capture_data else None,
                    "reply": result.reply_text,
                })
                yield sse_event("done", {
                    "reply": result.reply_text,
                    "run_id": result.run_id,
                })

            if "ask" in result.intents:
                ask_data = result.ask_result.model_dump(mode="json") if result.ask_result else {}
                yield sse_event("status", {"message": "正在检索你的个人记忆..."})
                yield sse_event("metadata", {
                    "citations": ask_data.get("citations", []),
                    "matches": ask_data.get("matches", []),
                    "session_id": session_id,
                })
                answer_text = result.reply_text
                built_answer = ""
                for chunk in chunk_answer(answer_text):
                    built_answer += chunk
                    yield sse_event("answer_delta", {
                        "delta": chunk,
                        "answer": built_answer,
                    })
                    await asyncio.sleep(0.02)
                yield sse_event("done", {
                    "answer": answer_text,
                    "citations": ask_data.get("citations", []),
                    "matches": ask_data.get("matches", []),
                    "session_id": session_id,
                    "run_id": result.run_id,
                })

            else:
                yield sse_event("status", {"message": result.reason})
                yield sse_event("done", {
                    "reply": result.reply_text,
                    "run_id": result.run_id,
                })

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
