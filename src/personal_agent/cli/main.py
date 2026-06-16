from __future__ import annotations

import json
import logging

import typer

from ..agent.runtime_results import EntryResult
from ..agent.service import AgentService
from ..core.config import Settings
from ..core.logging_utils import setup_logging
from ..core.models import EntryInput
from ..feishu import FeishuService
from ..review import (
    DigestSubscription,
    ReviewDigestJob,
    ReviewDigestScheduler,
    ReviewDigestUseCase,
    subscriptions_from_settings,
)
from ..review.delivery import DeliveryRouter, FeishuDeliveryProvider
from ..storage.postgres_review_digest_store import PostgresReviewDigestStore

app = typer.Typer(help="Personal knowledge agent CLI")
logger = logging.getLogger(__name__)


@app.callback()
def main() -> None:
    """Personal knowledge agent command line interface."""


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
    if result.steps:
        output["steps"] = result.steps
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


@app.command("review-digest")
def review_digest(
    user_id: str | None = typer.Option(None, help="Override digest user_id for this run."),
    chat_id: str | None = typer.Option(None, help="Override Feishu chat_id for this run."),
) -> None:
    """Run the internal review digest delivery job."""
    service = _build_service()
    feishu_service = FeishuService(service.settings, service)
    digest_store = PostgresReviewDigestStore(service.settings.postgres_url or "")
    for subscription in subscriptions_from_settings(service.settings):
        digest_store.upsert_subscription(subscription)
    job = ReviewDigestJob(
        ReviewDigestUseCase(service.memory),
        DeliveryRouter({"feishu": FeishuDeliveryProvider(feishu_service)}),
        ledger=digest_store,
    )
    subscriptions = digest_store.list_subscriptions()
    if chat_id:
        resolved_user_id = user_id or service.settings.default_user
        subscriptions = [
            DigestSubscription(
                id=f"manual:feishu:{resolved_user_id}:{chat_id}",
                user_id=resolved_user_id,
                channel="feishu",
                target_type="chat_id",
                target_id=chat_id,
                enabled=True,
            )
        ]
        results = [job.run(subscription) for subscription in subscriptions]
    elif user_id:
        subscriptions = [
            subscription
            for subscription in subscriptions
            if subscription.user_id == user_id
        ]
        scheduler = ReviewDigestScheduler(digest_store, job)
        due_ids = {subscription.id for subscription in scheduler.due_subscriptions()}
        results = [job.run(subscription) for subscription in subscriptions if subscription.id in due_ids]
    else:
        results = ReviewDigestScheduler(digest_store, job).run_due()

    typer.echo(json.dumps([r.model_dump(mode="json") for r in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
