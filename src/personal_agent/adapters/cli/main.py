from __future__ import annotations

import json
import logging

import typer

from personal_agent.application.conversation import ConversationMessage, ConversationTurnView
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.logging_utils import setup_logging
from personal_agent.adapters.feishu import FeishuService
from personal_agent.application.review import (
    DigestSubscription,
    ReviewDigestJob,
    ReviewDigestScheduler,
    subscriptions_from_settings,
)
from personal_agent.application.review.delivery import (
    DeliveryRouter,
    FeishuDeliveryProvider,
    InAppDeliveryProvider,
)
from personal_agent.infra.storage.postgres_review_digest_store import PostgresReviewDigestStore
from personal_agent.application.research import (
    ResearchSubscriptionRecord, ResearchSubscriptionSpec, SchedulePolicy,
)
from personal_agent.kernel.contracts.delivery import DeliveryTarget

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


def _format_conversation_result(result: ConversationTurnView) -> str:
    return result.model_dump_json(indent=2)


@app.command()
def entry(
    text: str = typer.Argument(..., help="入口文本（问题、指令或待采集内容）"),
    user_id: str = "default",
    session_id: str = "default",
) -> None:
    """通过 canonical interaction loop 处理一轮用户消息。"""
    service = _build_service()
    logger.info("CLI entry invoked user=%s session=%s", user_id, session_id)
    result = service.converse(
        conversation_id=session_id,
        messages=[ConversationMessage(role="user", content=text.strip())],
        user_id=user_id,
        source_platform="cli",
    )
    typer.echo(_format_conversation_result(result))


@app.command("worker")
def worker(
    queue: str = typer.Option("graph", help="Queue name to consume."),
    worker_id: str | None = typer.Option(None, help="Stable worker identity."),
    poll_seconds: float = typer.Option(1.0, min=0.05, help="Idle poll interval."),
    lease_seconds: int = typer.Option(300, min=1, help="Task lease duration."),
    max_running_per_user: int = typer.Option(1, min=0, help="Per-user running limit."),
    max_tasks: int = typer.Option(0, min=0, help="Stop after N tasks; 0 runs forever."),
) -> None:
    """Run a durable workflow activity worker."""
    from personal_agent.orchestration.worker import WorkflowWorker

    service = _build_service()
    if queue == "research":
        feishu_service = FeishuService(service.settings, service)
        service.research_service.set_delivery_router(DeliveryRouter({
            "feishu": FeishuDeliveryProvider(feishu_service),
            "in_app": InAppDeliveryProvider(),
        }))
    runner = WorkflowWorker(
        service.runtime,
        queue=queue,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        max_running_per_user=max_running_per_user,
    )
    stats = runner.run_forever(poll_seconds=poll_seconds, max_tasks=max_tasks)
    typer.echo(json.dumps({
        "worker_id": runner.worker_id,
        "queue": queue,
        "leased": stats.leased,
        "completed": stats.completed,
        "failed": stats.failed,
        "unsupported": stats.unsupported,
    }, ensure_ascii=False, indent=2))


@app.command("procedure-eval-record")
def procedure_eval_record(
    procedure_id: str = typer.Argument(...),
    version: str = typer.Argument(...),
    passed: bool = typer.Option(..., help="Whether the suite passed."),
    suite: str = typer.Option("default"),
    score: float | None = typer.Option(None),
    metrics_json: str = typer.Option("{}"),
    report_json: str = typer.Option("{}"),
) -> None:
    """Record an eval result for CI/deployment gating."""
    service = _build_service()
    result = service.record_procedure_eval_run(
        procedure_id,
        version,
        suite=suite,
        passed=passed,
        score=score,
        metrics=json.loads(metrics_json),
        report=json.loads(report_json),
    )
    typer.echo(json.dumps({
        "eval_run_id": result.eval_run_id,
        "procedure_id": result.procedure_id,
        "version": result.version,
        "suite": result.suite,
        "passed": result.passed,
        "score": result.score,
    }, ensure_ascii=False, indent=2))


@app.command("procedure-deploy")
def procedure_deploy(
    procedure_id: str = typer.Argument(...),
    stable_version: str = typer.Argument(...),
    environment: str = typer.Option("default"),
    status: str = typer.Option("stable"),
    canary_version: str | None = typer.Option(None),
    canary_percent: int = typer.Option(0, min=0, max=100),
    eval_suite: str = typer.Option("default"),
    force: bool = typer.Option(False, help="Bypass eval gate."),
) -> None:
    """Deploy a procedure version after the eval gate passes."""
    service = _build_service()
    result = service.set_procedure_deployment(
        procedure_id,
        stable_version=stable_version,
        environment=environment,
        status=status,
        canary_version=canary_version,
        canary_percent=canary_percent,
        eval_suite=eval_suite,
        require_eval_gate=not force,
    )
    typer.echo(json.dumps({
        "procedure_id": result.procedure_id,
        "environment": result.environment,
        "stable_version": result.stable_version,
        "canary_version": result.canary_version,
        "canary_percent": result.canary_percent,
        "status": result.status,
    }, ensure_ascii=False, indent=2))


@app.command("procedure-dry-run")
def procedure_dry_run(
    procedure_id: str = typer.Argument(...),
    routing_key: str = typer.Option("cli-dry-run"),
) -> None:
    """Validate and project the active procedure without executing it."""
    service = _build_service()
    typer.echo(json.dumps(
        service.dry_run_procedure(procedure_id=procedure_id, routing_key=routing_key),
        ensure_ascii=False,
        indent=2,
    ))


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
        service.review_digest_use_case,
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


@app.command("research-once")
def research_once(
    topic: str = typer.Argument(...),
    user_id: str = typer.Option("default"),
    instructions: str = typer.Option(""),
    max_items: int = typer.Option(5, min=1, max=20),
    lookback_hours: int = typer.Option(24, min=1, max=720),
) -> None:
    """Run a one-shot external research workflow."""
    service = _build_service()
    run = service.run_research_once(
        user_id=user_id,
        topic=topic,
        instructions=instructions,
        max_items=max_items,
        lookback_hours=lookback_hours,
    )
    digest = service.research_store.get_digest(run.digest_id) if run.digest_id else None
    typer.echo(json.dumps({
        "run": run.model_dump(mode="json"),
        "digest": digest.model_dump(mode="json") if digest else None,
    }, ensure_ascii=False, indent=2))


@app.command("research-subscribe")
def research_subscribe(
    topic: str = typer.Argument(...),
    name: str | None = typer.Option(None),
    user_id: str = typer.Option("default"),
    schedule_time: str = typer.Option("09:00"),
    timezone: str = typer.Option("Asia/Shanghai"),
    frequency: str = typer.Option("daily"),
    chat_id: str = typer.Option(""),
    instructions: str = typer.Option(""),
    max_items: int = typer.Option(5, min=1, max=20),
) -> None:
    """Create a durable scheduled research subscription."""
    service = _build_service()
    subscription = service.create_research_subscription(ResearchSubscriptionRecord.create(
        ResearchSubscriptionSpec(
        user_id=user_id,
        name=name or f"{topic} 情报简报",
        topic=topic,
        instructions=instructions,
        max_items=max_items,
        schedule=SchedulePolicy(
            frequency=frequency,
            schedule_time=schedule_time,
            timezone=timezone,
        ),
        delivery=DeliveryTarget(target_id=chat_id),
        )
    ))
    typer.echo(subscription.model_dump_json(indent=2))


@app.command("research-schedule")
def research_schedule() -> None:
    """Enqueue all due research subscriptions."""
    from personal_agent.application.research import ResearchScheduler

    service = _build_service()
    runs = ResearchScheduler(
        service.research_store,
        service.research_service,
    ).enqueue_due()
    typer.echo(json.dumps(
        [run.model_dump(mode="json") for run in runs],
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    app()
