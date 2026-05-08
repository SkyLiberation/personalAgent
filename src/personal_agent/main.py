from __future__ import annotations

import json
import logging

import typer

from .config import Settings
from .logging_utils import setup_logging
from .service import AgentService

app = typer.Typer(help="Personal knowledge agent CLI")
logger = logging.getLogger(__name__)


def _build_service() -> AgentService:
    settings = Settings.from_env()
    log_file = setup_logging(settings.log_level)
    logger.info("CLI logging initialized at %s", log_file)
    return AgentService(settings)


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
def ask(question: str, user_id: str = "default") -> None:
    service = _build_service()
    logger.info("CLI ask invoked user=%s", user_id)
    result = service.ask(question=question, user_id=user_id)
    typer.echo(
        json.dumps(
            {
                "answer": result.answer,
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
