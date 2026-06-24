from __future__ import annotations

import re

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..research import DeliveryTarget, ResearchSubscription, SchedulePolicy
from .base import governance_extras, tool_response, tool_success


class ResearchOnceArgs(BaseModel):
    topic: str = Field(min_length=1, description="要研究或收集信息的主题及要求。")
    user_id: str = "default"
    max_items: int = Field(default=5, ge=1, le=20)
    lookback_hours: int = Field(default=24, ge=1, le=720)


class CreateResearchSubscriptionArgs(BaseModel):
    request: str = Field(min_length=1, description="用户对周期、主题、筛选要求的完整自然语言描述。")
    user_id: str = "default"
    target_id: str = Field(default="", description="投递目标，例如当前飞书 chat_id。")


def build_research_once_tool(service) -> BaseTool:
    @tool(
        "research_once",
        description="对指定主题执行一次多来源外部研究，完成搜索、去重、验证、个人知识关联并生成简报。",
        args_schema=ResearchOnceArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            side_effects=("external_network", "read_longterm"),
            permission_scope="research:run",
            timeout_seconds=180,
            max_retries=0,
            rate_limit_per_minute=5,
        ),
    )
    def research_once(
        topic: str,
        user_id: str = "default",
        max_items: int = 5,
        lookback_hours: int = 24,
    ):
        run = service.run_once(
            user_id=user_id,
            topic=topic,
            max_items=max_items,
            lookback_hours=lookback_hours,
        )
        digest = service.get_digest(run.digest_id) if run.digest_id else None
        return tool_response(tool_success({
            "run": run.model_dump(mode="json"),
            "digest": digest.model_dump(mode="json") if digest else None,
            "answer": digest.to_text() if digest else run.failure_reason or "研究未生成简报。",
        }))

    return research_once


def build_create_research_subscription_tool(service) -> BaseTool:
    @tool(
        "create_research_subscription",
        description="创建周期性外部情报收集订阅，例如每天 9 点收集 AI 新闻并投递到当前飞书会话。",
        args_schema=CreateResearchSubscriptionArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="research:subscribe",
            timeout_seconds=20,
            rate_limit_per_minute=10,
        ),
    )
    def create_research_subscription(
        request: str, user_id: str = "default", target_id: str = ""
    ):
        schedule_time = _extract_time(request)
        max_items = _extract_max_items(request)
        topic = _extract_topic(request)
        frequency = "weekdays" if "工作日" in request else "weekly" if "每周" in request else "daily"
        subscription = ResearchSubscription(
            user_id=user_id,
            name=f"{topic} 情报简报",
            topic=topic,
            instructions=request,
            seed_queries=[f"{topic} latest news", f"{topic} official announcement"],
            max_items=max_items,
            schedule=SchedulePolicy(
                frequency=frequency,
                schedule_time=schedule_time,
            ),
            delivery=DeliveryTarget(target_id=target_id),
        )
        saved = service.create_subscription(subscription)
        return tool_response(tool_success({
            "subscription": saved.model_dump(mode="json"),
            "answer": (
                f"已创建“{saved.name}”，{saved.schedule.frequency} "
                f"{saved.schedule.schedule_time}（{saved.schedule.timezone}）运行。"
            ),
        }))

    return create_research_subscription


def _extract_time(text: str) -> str:
    match = re.search(r"(\d{1,2})(?:[:：](\d{1,2}))?\s*点?", text)
    if not match:
        return "09:00"
    hour = max(0, min(23, int(match.group(1))))
    minute = max(0, min(59, int(match.group(2) or 0)))
    return f"{hour:02d}:{minute:02d}"


def _extract_max_items(text: str) -> int:
    match = re.search(r"(?:最多|保留|精选)\s*(\d{1,2})\s*条", text)
    return max(1, min(20, int(match.group(1)))) if match else 5


def _extract_topic(text: str) -> str:
    match = re.search(r"(?:关于|收集|关注|跟踪)\s*([A-Za-z0-9\u4e00-\u9fff +#.-]{1,40}?)(?:的)?(?:新闻|资讯|动态|更新|简报)", text)
    if match:
        return match.group(1).strip()
    for candidate in ("AI", "Agent", "大模型", "RAG", "GraphRAG"):
        if candidate.lower() in text.lower():
            return candidate
    return text[:40].strip()
