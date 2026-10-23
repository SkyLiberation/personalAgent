"""The single accepted research experiment tool; no model-supplied identity."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from personal_agent.application.retrieval_experiment.models import (
    ExperimentAction,
    ExperimentToolArgs,
)
from personal_agent.application.retrieval_experiment.service import (
    RetrievalExperimentService,
)
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import (
    ToolArtifact,
    governance_extras,
    require_gateway_context,
    tool_response,
)


def build_retrieval_experiment_tool(service: RetrievalExperimentService) -> BaseTool:
    @tool(
        "retrieval_experiment",
        description=get_prompt("retrieval_experiment.description").template,
        args_schema=ExperimentToolArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            side_effects=("write_local",),
            permission_scope="experiment:execute",
            timeout_seconds=None,
            max_retries=0,
        ),
    )
    def retrieval_experiment(action: ExperimentAction, config: RunnableConfig):
        context = require_gateway_context(config)
        if context.accepted_request_digest is None:
            raise PermissionError("实验请求缺少已接受记录。")
        result = service.execute(
            action,
            execution_scope=context.execution_scope,
            action_id=context.tool_call_id,
            request_digest=context.accepted_request_digest,
        )
        succeeded = result.receipt.status == "succeeded"
        return tool_response(
            ToolArtifact(
                ok=succeeded,
                data=result.model_dump(mode="json"),
                evidence=[],
                error=None
                if succeeded
                else f"实验状态：{result.receipt.status}；{result.receipt.error_code or '详见实际回执'}",
                error_kind=None if succeeded else "unrecoverable",
            )
        )

    return retrieval_experiment
