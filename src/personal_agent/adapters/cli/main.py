from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import ValidationError
import typer

from personal_agent.application.capture import CaptureService
from personal_agent.application.conversation import ConversationMessage, ConversationTurnView
from personal_agent.application.conversation.errors import (
    ConversationInputError,
    ConversationOperationConflict,
    ConversationOperationNotFound,
    ConversationTurnBlocked,
    ConversationTurnPending,
)
from personal_agent.application.conversation.service import submitted_turn_id
from personal_agent.kernel.contracts.scope import (
    AuthenticatedPrincipal,
)
from personal_agent.orchestration.service import AgentService
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.policy import EntryPolicyDenied
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
    return AgentService(
        settings,
        capture_service=CaptureService(settings, logger),
    )


def _format_conversation_result(result: ConversationTurnView, client_request_id: str | None) -> str:
    payload = {
        "session_id": result.conversation_id,
        "turn_id": result.interaction_run_ref,
        **result.model_dump(mode="json", exclude={"conversation_id", "interaction_run_ref"}),
    }
    if client_request_id is not None:
        payload["client_request_id"] = client_request_id
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _resume_conversation(
    service: AgentService,
    *,
    principal: AuthenticatedPrincipal,
    session_id: str | None,
    turn_id: str,
) -> ConversationTurnView:
    service.authorize_entry(principal, "cli", preflight=True)
    try:
        trace = service.conversation_trace(turn_id, principal=principal)
    except PermissionError:
        raise ConversationOperationNotFound("轮次不存在。") from None
    except ValueError as exc:
        raise typer.BadParameter("轮次 ID 无效。", param_hint="--resume-turn-id") from exc
    if trace is None or (session_id is not None and trace.conversation_id != session_id):
        raise ConversationOperationNotFound("轮次不存在。")
    return service.converse(
        conversation_id=trace.conversation_id,
        interaction_run_ref=turn_id,
        principal=principal,
        source_platform="cli",
    )


@app.command()
def entry(
    text: str | None = typer.Argument(None, help="入口文本（问题、指令或待采集内容）"),
    user_id: str | None = None,
    session_id: str | None = typer.Option(None, help="续聊使用已有会话 ID。省略时创建新会话。"),
    create_session: bool = typer.Option(False, "--create-session", help="使用指定会话 ID 创建新会话。"),
    client_request_id: str | None = typer.Option(None, help="重试时沿用原会话 ID 和请求 ID。"),
    resume_turn_id: str | None = typer.Option(None, help="按原轮次 ID 恢复会话。"),
) -> None:
    """通过 canonical interaction loop 处理一轮用户消息。"""
    if session_id == "":
        raise typer.BadParameter("会话 ID 不能为空。", param_hint="--session-id")
    if client_request_id == "":
        raise typer.BadParameter("请求 ID 不能为空。", param_hint="--client-request-id")
    if (text is None) == (resume_turn_id is None):
        raise typer.BadParameter("请提供消息文本或 --resume-turn-id，二者只能选一项。")
    if resume_turn_id is not None and (not resume_turn_id or create_session or client_request_id is not None):
        raise typer.BadParameter("恢复需要轮次 ID，且不能指定新会话或请求 ID。", param_hint="--resume-turn-id")
    message = None
    if text is not None:
        if not text.strip():
            raise typer.BadParameter("消息不能为空。", param_hint="text")
        try:
            message = ConversationMessage(role="user", content=text)
        except ValidationError as exc:
            raise typer.BadParameter("消息超过长度限制。", param_hint="text") from exc

    registered_turn_id: str | None = None

    def remember_registered_turn(turn_id: str) -> None:
        nonlocal registered_turn_id
        registered_turn_id = turn_id

    with _build_service() as service:
        try:
            if service.settings.policy.restricts_principals:
                assigned_user = service.settings.default_user
                if user_id is not None and user_id != assigned_user:
                    raise EntryPolicyDenied("启用主体名单时，命令行不能切换部署配置的主体。")
            else:
                assigned_user = user_id or "default"
            principal = AuthenticatedPrincipal(tenant_id="personal-agent", user_id=assigned_user)
            if resume_turn_id is not None:
                result = _resume_conversation(
                    service, principal=principal, session_id=session_id, turn_id=resume_turn_id,
                )
            else:
                if session_id is None:
                    session_id = f"session_{uuid4().hex}"
                    create_session = True
                client_request_id = client_request_id or uuid4().hex
                logger.info("CLI entry invoked user=%s session=%s", assigned_user, session_id)
                try:
                    result = service.converse(
                        conversation_id=session_id,
                        message=message,
                        principal=principal,
                        source_platform="cli",
                        create_session=create_session,
                        client_request_id=client_request_id,
                        on_registered=remember_registered_turn,
                    )
                except ConversationTurnPending:
                    typer.echo(json.dumps({
                        "session_id": session_id,
                        "turn_id": registered_turn_id or submitted_turn_id(principal, session_id, client_request_id),
                        "client_request_id": client_request_id,
                        "status": "pending",
                    }, ensure_ascii=False, indent=2))
                    return
                except (Exception, KeyboardInterrupt):
                    if registered_turn_id is not None:
                        typer.echo(f"轮次已登记，可用 --resume-turn-id {registered_turn_id} 恢复。", err=True)
                    raise
        except ConversationTurnBlocked as exc:
            typer.echo(f"{exc}。可使用 --resume-turn-id {exc.turn_id} 恢复。", err=True)
            raise typer.Exit(code=1) from exc
        except PermissionError as exc:
            typer.echo("当前入口无法访问或恢复该轮次。", err=True)
            raise typer.Exit(code=1) from exc
        except (EntryPolicyDenied, ConversationInputError, ConversationOperationConflict,
                ConversationOperationNotFound) as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=1) from exc
        typer.echo(_format_conversation_result(result, client_request_id))


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

    with _build_service() as service:
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
    with _build_service() as service:
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
    with _build_service() as service:
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
    with _build_service() as service:
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
    with _build_service() as service:
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
    with _build_service() as service:
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
    with _build_service() as service:
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

    with _build_service() as service:
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
