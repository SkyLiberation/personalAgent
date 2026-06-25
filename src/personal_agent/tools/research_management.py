from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.application.research import ResearchFeedback
from personal_agent.tools.base import governance_extras, tool_failure, tool_response, tool_success


class ListResearchSubscriptionsArgs(BaseModel):
    user_id: str = "default"
    enabled_only: bool = True


class UpdateResearchSubscriptionArgs(BaseModel):
    subscription_id: str = Field(min_length=1)
    user_id: str = "default"
    name: str | None = None
    topic: str | None = None
    instructions: str | None = None
    schedule_time: str | None = None
    max_items: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None


class SubscriptionActionArgs(BaseModel):
    subscription_id: str = Field(min_length=1)
    user_id: str = "default"


class ListResearchRunsArgs(BaseModel):
    user_id: str = "default"
    limit: int = Field(default=20, ge=1, le=100)


class GetResearchDigestArgs(BaseModel):
    run_id: str = Field(min_length=1)
    user_id: str = "default"


class SubmitResearchFeedbackArgs(BaseModel):
    event_id: str = Field(min_length=1)
    action: str = Field(pattern="^(expand|useful|not_interested|save)$")
    user_id: str = "default"
    subscription_id: str | None = None
    comment: str = ""


class SaveResearchEventArgs(BaseModel):
    event_id: str = Field(min_length=1)
    user_id: str = "default"


def _subscription_summary(subscription) -> dict:
    return subscription.model_dump(mode="json")


def _run_summary(run) -> dict:
    return run.model_dump(mode="json")


def build_list_research_subscriptions_tool(service) -> BaseTool:
    @tool(
        "list_research_subscriptions",
        description="列出用户的周期性情报订阅，供 Agent 判断是否需要新增、暂停或调整。",
        args_schema=ListResearchSubscriptionsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="research:read"),
    )
    def list_research_subscriptions(user_id: str = "default", enabled_only: bool = True):
        subscriptions = service.list_subscriptions(user_id=user_id, enabled_only=enabled_only)
        return tool_response(tool_success({
            "subscriptions": [_subscription_summary(item) for item in subscriptions]
        }))

    return list_research_subscriptions


def build_update_research_subscription_tool(service) -> BaseTool:
    @tool(
        "update_research_subscription",
        description="更新情报订阅的主题、说明、运行时间、条数或启用状态。",
        args_schema=UpdateResearchSubscriptionArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:subscribe",
            timeout_seconds=20,
        ),
    )
    def update_research_subscription(
        subscription_id: str,
        user_id: str = "default",
        name: str | None = None,
        topic: str | None = None,
        instructions: str | None = None,
        schedule_time: str | None = None,
        max_items: int | None = None,
        enabled: bool | None = None,
    ):
        subscription = service.get_subscription(subscription_id)
        if subscription is None or subscription.user_id != user_id:
            return tool_response(tool_failure("未找到该用户的订阅。", error_kind="invalid_param"))
        update = {}
        if name is not None:
            update["name"] = name
        if topic is not None:
            update["topic"] = topic
        if instructions is not None:
            update["instructions"] = instructions
        if max_items is not None:
            update["max_items"] = max_items
        if enabled is not None:
            update["enabled"] = enabled
        if schedule_time is not None:
            update["schedule"] = subscription.schedule.model_copy(update={"schedule_time": schedule_time})
        saved = service.update_subscription(subscription.model_copy(update=update))
        return tool_response(tool_success({"subscription": _subscription_summary(saved)}))

    return update_research_subscription


def build_pause_research_subscription_tool(service) -> BaseTool:
    @tool(
        "pause_research_subscription",
        description="暂停一个情报订阅，后续外部 cron 不再为其入队。",
        args_schema=SubscriptionActionArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:subscribe",
        ),
    )
    def pause_research_subscription(subscription_id: str, user_id: str = "default"):
        return _set_enabled(service, subscription_id, user_id, False)

    return pause_research_subscription


def build_resume_research_subscription_tool(service) -> BaseTool:
    @tool(
        "resume_research_subscription",
        description="恢复一个已暂停的情报订阅。",
        args_schema=SubscriptionActionArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:subscribe",
        ),
    )
    def resume_research_subscription(subscription_id: str, user_id: str = "default"):
        return _set_enabled(service, subscription_id, user_id, True)

    return resume_research_subscription


def build_run_research_subscription_now_tool(service) -> BaseTool:
    @tool(
        "run_research_subscription_now",
        description="立即为一个情报订阅创建 durable run 并入队，由 research worker 异步执行。",
        args_schema=SubscriptionActionArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:run",
        ),
    )
    def run_research_subscription_now(subscription_id: str, user_id: str = "default"):
        subscription = service.get_subscription(subscription_id)
        if subscription is None or subscription.user_id != user_id:
            return tool_response(tool_failure("未找到该用户的订阅。", error_kind="invalid_param"))
        run = service.enqueue_subscription_run(subscription, trigger_type="manual")
        return tool_response(tool_success({"run": _run_summary(run)}))

    return run_research_subscription_now


def build_list_research_runs_tool(service) -> BaseTool:
    @tool(
        "list_research_runs",
        description="列出用户最近的 Research 执行记录，用于诊断简报是否运行、失败或投递。",
        args_schema=ListResearchRunsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="research:read"),
    )
    def list_research_runs(user_id: str = "default", limit: int = 20):
        runs = service.list_runs(user_id=user_id, limit=limit)
        return tool_response(tool_success({"runs": [_run_summary(run) for run in runs]}))

    return list_research_runs


def build_get_research_digest_tool(service) -> BaseTool:
    @tool(
        "get_research_digest",
        description="读取某次 Research run 的简报内容。",
        args_schema=GetResearchDigestArgs,
        response_format="content_and_artifact",
        extras=governance_extras(exposure="public_agent", side_effects=("read_longterm",), permission_scope="research:read"),
    )
    def get_research_digest(run_id: str, user_id: str = "default"):
        run = service.get_run(run_id)
        if run is None or run.user_id != user_id:
            return tool_response(tool_failure("未找到该用户的 Research run。", error_kind="invalid_param"))
        digest = service.get_digest(run.digest_id) if run.digest_id else None
        return tool_response(tool_success({
            "run": _run_summary(run),
            "digest": digest.model_dump(mode="json") if digest else None,
            "text": digest.to_text() if digest else "",
        }))

    return get_research_digest


def build_submit_research_feedback_tool(service) -> BaseTool:
    @tool(
        "submit_research_feedback",
        description="记录用户对 Research 事件的反馈，例如有用、不感兴趣、保存。",
        args_schema=SubmitResearchFeedbackArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            side_effects=("write_longterm",),
            permission_scope="research:feedback",
            timeout_seconds=20,
        ),
    )
    def submit_research_feedback(
        event_id: str,
        action: str,
        user_id: str = "default",
        subscription_id: str | None = None,
        comment: str = "",
    ):
        feedback = service.feedback(ResearchFeedback(
            user_id=user_id,
            event_id=event_id,
            subscription_id=subscription_id,
            action=action,
            comment=comment,
        ))
        return tool_response(tool_success({"feedback": feedback.model_dump(mode="json")}))

    return submit_research_feedback


def build_save_research_event_tool(service) -> BaseTool:
    @tool(
        "save_research_event",
        description="将 Research 事件保存为长期知识笔记。",
        args_schema=SaveResearchEventArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="scoped_agent",
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:save",
            timeout_seconds=30,
        ),
    )
    def save_research_event(event_id: str, user_id: str = "default"):
        note = service.save_event(event_id, user_id=user_id)
        return tool_response(tool_success({"note": note.model_dump(mode="json") if hasattr(note, "model_dump") else note}))

    return save_research_event


def _set_enabled(service, subscription_id: str, user_id: str, enabled: bool):
    subscription = service.get_subscription(subscription_id)
    if subscription is None or subscription.user_id != user_id:
        return tool_response(tool_failure("未找到该用户的订阅。", error_kind="invalid_param"))
    saved = service.update_subscription(subscription.model_copy(update={"enabled": enabled}))
    return tool_response(tool_success({"subscription": _subscription_summary(saved)}))
