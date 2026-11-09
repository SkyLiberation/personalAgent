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
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.tools.base import (
    ToolArtifact,
    governance_extras,
    require_gateway_context,
    tool_response,
)


def build_retrieval_experiment_tool(
    service: RetrievalExperimentService, *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> BaseTool:
    @tool(
        "retrieval_experiment",
        description=prompts.get("retrieval_experiment.description").template,
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
        context = require_gateway_context(config, prompts=prompts)
        if context.accepted_request_digest is None:
            raise PermissionError(prompts.render('tools.experiment.acceptance_missing'))
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
                else prompts.render('tools.experiment.status', status=result.receipt.status, detail=result.receipt.error_code or prompts.render('tools.experiment.read_receipt')),
                error_kind=None if succeeded else "unrecoverable",
            )
        )

    return retrieval_experiment
