from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from personal_agent.tools.base import governance_extras, tool_response, tool_success


class ResearchPrepareRunArgs(BaseModel):
    topic: str = Field(min_length=1)
    user_id: str = "default"
    instructions: str = ""
    max_items: int = Field(default=5, ge=1, le=20)
    lookback_hours: int = Field(default=24, ge=1, le=720)


class ResearchRunIdArgs(BaseModel):
    run_id: str = Field(min_length=1)
    user_id: str = "default"


class ResearchRankEventsArgs(BaseModel):
    run_id: str = Field(min_length=1)
    user_id: str = "default"
    max_items: int | None = Field(default=None, ge=1, le=20)


def build_research_prepare_run_tool(service) -> BaseTool:
    @tool(
        "research_prepare_run",
        description="创建 ResearchRun 并进入 running 状态，作为 Research workflow 的业务状态锚点。",
        args_schema=ResearchPrepareRunArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:run",
            timeout_seconds=20,
        ),
    )
    def research_prepare_run(
        topic: str,
        user_id: str = "default",
        instructions: str = "",
        max_items: int = 5,
        lookback_hours: int = 24,
    ):
        run = service.prepare_run(
            user_id=user_id,
            topic=topic,
            instructions=instructions,
            max_items=max_items,
            lookback_hours=lookback_hours,
        )
        return tool_response(tool_success({
            "run_id": run.id,
            "run": run.model_dump(mode="json"),
            "max_items": max_items,
        }))

    return research_prepare_run


def build_research_plan_queries_tool(service) -> BaseTool:
    @tool(
        "research_plan_queries",
        description="为 ResearchRun 规划查询词，并将查询计划写回 run。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:run",
            timeout_seconds=30,
        ),
    )
    def research_plan_queries(run_id: str, user_id: str = "default"):
        queries = service.plan_queries(run_id)
        return tool_response(tool_success({"run_id": run_id, "queries": queries}))

    return research_plan_queries


def build_research_collect_sources_tool(service) -> BaseTool:
    @tool(
        "research_collect_sources",
        description="按查询计划收集 Research 来源，并抓取高价值来源全文。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("external_network", "write_longterm"),
            permission_scope="research:collect",
            timeout_seconds=180,
            rate_limit_per_minute=5,
        ),
    )
    def research_collect_sources(run_id: str, user_id: str = "default"):
        sources = service.collect_sources(run_id)
        return tool_response(tool_success({
            "run_id": run_id,
            "source_count": len(sources),
            "sources": [source.model_dump(mode="json") for source in sources[:10]],
        }))

    return research_collect_sources


def build_research_cluster_events_tool(service) -> BaseTool:
    @tool(
        "research_cluster_events",
        description="将 Research 来源去重并聚类为事件，计算初始可信度和新颖性。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:evaluate",
            timeout_seconds=60,
        ),
    )
    def research_cluster_events(run_id: str, user_id: str = "default"):
        events = service.cluster_events(run_id)
        return tool_response(tool_success({
            "run_id": run_id,
            "event_count": len(events),
            "events": [event.model_dump(mode="json") for event in events[:10]],
        }))

    return research_cluster_events


def build_research_rank_events_tool(service) -> BaseTool:
    @tool(
        "research_rank_events",
        description="结合个人知识图谱、重要性、新颖性和可信度排序 Research 事件。",
        args_schema=ResearchRankEventsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("read_longterm", "write_longterm"),
            permission_scope="research:rank",
            timeout_seconds=120,
        ),
    )
    def research_rank_events(run_id: str, user_id: str = "default", max_items: int | None = None):
        events = service.rank_events(run_id, max_items=max_items)
        return tool_response(tool_success({
            "run_id": run_id,
            "selected_count": len(events),
            "selected_event_ids": [event.id for event in events],
            "events": [event.model_dump(mode="json") for event in events],
        }))

    return research_rank_events


def build_research_compose_digest_tool(service) -> BaseTool:
    @tool(
        "research_compose_digest",
        description="根据已排序 Research 事件生成情报简报，并完成 run 状态。",
        args_schema=ResearchRankEventsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:compose",
            timeout_seconds=60,
        ),
    )
    def research_compose_digest(run_id: str, user_id: str = "default", max_items: int | None = None):
        run = service.compose_digest(run_id, max_items=max_items)
        digest = service.get_digest(run.digest_id) if run.digest_id else None
        return tool_response(tool_success({
            "run_id": run_id,
            "run": run.model_dump(mode="json"),
            "digest": digest.model_dump(mode="json") if digest else None,
            "answer": digest.to_text() if digest else run.failure_reason or "研究未生成简报。",
        }))

    return research_compose_digest
