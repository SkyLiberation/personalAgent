from __future__ import annotations

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .base import governance_extras, tool_failure, tool_response, tool_success


class InspectWorkerQueueArgs(BaseModel):
    queue: str | None = None
    statuses: list[str] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class RetryWorkerTaskArgs(BaseModel):
    task_id: str = Field(min_length=1)


class InspectWorkflowRunArgs(BaseModel):
    run_id: str = Field(min_length=1)
    include_history: bool = False
    history_limit: int = Field(default=30, ge=1, le=100)


def build_inspect_worker_queue_tool(runtime) -> BaseTool:
    @tool(
        "inspect_worker_queue",
        description="查看 durable worker 队列状态和最近任务，用于诊断后台任务是否堆积、失败或死亡。",
        args_schema=InspectWorkerQueueArgs,
        response_format="content_and_artifact",
        extras=governance_extras(side_effects=("none",), permission_scope="ops:read"),
    )
    def inspect_worker_queue(
        queue: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
    ):
        stats = runtime.worker_queue_store.queue_stats(queue)
        tasks = runtime.worker_queue_store.list_tasks(queue=queue, statuses=statuses, limit=limit)
        return tool_response(tool_success({
            "stats": stats,
            "tasks": [task.model_dump(mode="json") for task in tasks],
        }))

    return inspect_worker_queue


def build_retry_worker_task_tool(runtime) -> BaseTool:
    @tool(
        "retry_worker_task",
        description="将 dead 状态的 durable worker 任务重新排队。仅用于用户明确要求重试失败任务时。",
        args_schema=RetryWorkerTaskArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            risk_level="medium",
            side_effects=("write_longterm",),
            permission_scope="ops:worker",
        ),
    )
    def retry_worker_task(task_id: str):
        ok = runtime.worker_queue_store.retry_dead(task_id)
        if not ok:
            return tool_response(tool_failure("任务不存在或不是 dead 状态，无法重试。", error_kind="invalid_param"))
        return tool_response(tool_success({"task_id": task_id, "status": "queued"}))

    return retry_worker_task


def build_inspect_workflow_run_tool(runtime) -> BaseTool:
    @tool(
        "inspect_workflow_run",
        description="查看一个 Agent workflow run 的快照、步骤状态和可选历史，用于解释执行过程或失败原因。",
        args_schema=InspectWorkflowRunArgs,
        response_format="content_and_artifact",
        extras=governance_extras(side_effects=("none",), permission_scope="workflow:read"),
    )
    def inspect_workflow_run(
        run_id: str,
        include_history: bool = False,
        history_limit: int = 30,
    ):
        snapshot = runtime.get_run_snapshot(run_id)
        if snapshot is None:
            return tool_response(tool_failure("未找到该 workflow run。", error_kind="invalid_param"))
        payload = {"snapshot": snapshot.model_dump(mode="json")}
        if include_history:
            payload["history"] = runtime.list_run_history(run_id, limit=history_limit)
        return tool_response(tool_success(payload))

    return inspect_workflow_run
