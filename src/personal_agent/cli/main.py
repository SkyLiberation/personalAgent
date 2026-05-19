from __future__ import annotations

import json
import logging

import typer

from ..agent.runtime_results import EntryResult
from ..agent.service import AgentService
from ..core.config import Settings
from ..core.logging_utils import setup_logging
from ..core.models import EntryInput

app = typer.Typer(help="Personal knowledge agent CLI")
logger = logging.getLogger(__name__)


def _build_service() -> AgentService:
    settings = Settings.from_env()
    log_file = setup_logging(settings.log_level)
    logger.info("CLI logging initialized at %s", log_file)
    return AgentService(settings)


def _format_entry_result(result: EntryResult) -> str:
    """Format an EntryResult as JSON for CLI output."""
    output: dict = {
        "intent": result.intent,
        "reason": result.reason,
        "reply": result.reply_text,
        "run_id": result.run_id,
        "run_status": result.run_status,
    }
    if result.plan_steps:
        output["plan_steps"] = result.plan_steps
    if result.execution_trace:
        output["execution_trace"] = result.execution_trace
    if result.capture_result:
        output["note_id"] = result.capture_result.note.id
    if result.ask_result:
        output["citations"] = [
            c.model_dump(mode="json") for c in result.ask_result.citations
        ]
    return json.dumps(output, ensure_ascii=False, indent=2)


@app.command()
def entry(
    text: str = typer.Argument(..., help="入口文本（问题、指令或待采集内容）"),
    user_id: str = "default",
    session_id: str = "default",
) -> None:
    """通过统一 Agent 入口处理文本，走完整的意图路由→规划→执行链路。"""
    service = _build_service()
    logger.info("CLI entry invoked user=%s session=%s", user_id, session_id)
    result = service.entry(EntryInput(
        text=text.strip(),
        user_id=user_id,
        session_id=session_id,
        source_platform="cli",
    ))
    typer.echo(_format_entry_result(result))


@app.command()
def capture(text: str, source_type: str = "text", user_id: str = "default") -> None:
    service = _build_service()
    logger.info("CLI capture invoked user=%s source_type=%s", user_id, source_type)
    result = service.capture(text=text, source_type=source_type, user_id=user_id)
    typer.echo(
        json.dumps(
            {
                "note_id": result.note.id,
                "summary": result.note.summary,
                "tags": result.note.tags,
                "related_note_ids": result.note.related_note_ids,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def ask(question: str, user_id: str = "default", session_id: str = "default") -> None:
    service = _build_service()
    logger.info("CLI ask invoked user=%s session=%s", user_id, session_id)
    result = service.ask(question=question, user_id=user_id, session_id=session_id)
    typer.echo(
        json.dumps(
            {
                "answer": result.answer,
                "session_id": result.session_id,
                "citations": [item.model_dump(mode="json") for item in result.citations],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command()
def digest(user_id: str = "default") -> None:
    service = _build_service()
    logger.info("CLI digest invoked user=%s", user_id)
    typer.echo(service.digest(user_id).message)


if __name__ == "__main__":
    app()
