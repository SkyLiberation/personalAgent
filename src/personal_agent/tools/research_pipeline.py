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


def build_research_initialize_state_tool(service) -> BaseTool:
    @tool(
        "research_initialize_state",
        description="初始化 evidence-driven ResearchState，生成初始研究动作和查询策略。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:run",
            timeout_seconds=30,
        ),
    )
    def research_initialize_state(run_id: str, user_id: str = "default"):
        state = service.initialize_state(run_id)
        return tool_response(tool_success({
            "run_id": run_id,
            "state": state.model_dump(mode="json"),
            "planned_actions": len(state.decisions),
            "queries": [decision.query for decision in state.decisions if decision.query],
        }))

    return research_initialize_state


def build_research_run_loop_tool(service) -> BaseTool:
    @tool(
        "research_run_loop",
        description="运行 evidence-driven 研究循环，按证据缺口动态搜索、聚类、排序并更新 ResearchState。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("external_network", "write_longterm"),
            permission_scope="research:collect",
            timeout_seconds=240,
            rate_limit_per_minute=5,
        ),
    )
    def research_run_loop(run_id: str, user_id: str = "default"):
        state = service.run_research_loop(run_id)
        return tool_response(tool_success({
            "run_id": run_id,
            "state": state.model_dump(mode="json"),
            "iteration_count": state.iteration_count,
            "gap_count": len(state.evidence_gaps),
            "stop_reason": state.stop_reason,
        }))

    return research_run_loop


def build_research_synthesize_digest_tool(service) -> BaseTool:
    @tool(
        "research_synthesize_digest",
        description="根据 ResearchState 中的事件和证据状态生成情报简报。",
        args_schema=ResearchRankEventsArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:compose",
            timeout_seconds=60,
        ),
    )
    def research_synthesize_digest(run_id: str, user_id: str = "default", max_items: int | None = None):
        run = service.synthesize_digest(run_id, max_items=max_items)
        digest = service.get_digest(run.digest_id) if run.digest_id else None
        return tool_response(tool_success({
            "run_id": run_id,
            "run": run.model_dump(mode="json"),
            "digest": digest.model_dump(mode="json") if digest else None,
            "answer": digest.to_text() if digest else run.failure_reason or "研究未生成简报。",
        }))

    return research_synthesize_digest


def build_research_verify_digest_tool(service) -> BaseTool:
    @tool(
        "research_verify_digest",
        description="校验情报简报是否有来源支撑，并降级无证据条目。",
        args_schema=ResearchRunIdArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            side_effects=("write_longterm",),
            permission_scope="research:verify",
            timeout_seconds=30,
        ),
    )
    def research_verify_digest(run_id: str, user_id: str = "default"):
        digest = service.verify_digest(run_id)
        return tool_response(tool_success({
            "run_id": run_id,
            "digest": digest.model_dump(mode="json") if digest else None,
            "answer": digest.to_text() if digest else "",
        }))

    return research_verify_digest
