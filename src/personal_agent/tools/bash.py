"""Model-facing Bash execution through the governed Tool Port."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from personal_agent.application.bash_execution.models import BASH_SHARED_INPUTS_DIR, BashArgs
from personal_agent.application.bash_execution.service import BashExecutionService
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.tools.base import (
    ToolArtifact,
    ToolError,
    governance_extras,
    require_gateway_context,
)


def build_bash_tool(
    service: BashExecutionService, *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> BaseTool:
    workspace = service.profile.workspace
    tool_description = (
        prompts.render("bash_execution.shared_workspace", workspace_root=workspace.root, inputs_root=BASH_SHARED_INPUTS_DIR)
        if workspace is not None else prompts.get("bash_execution.description").template
    )

    @tool(
        "bash",
        description=tool_description,
        args_schema=BashArgs,
        response_format="content_and_artifact",
        extras={"strict": False, **governance_extras(
            side_effects=("write_local", "external_network")
            if workspace is not None and workspace.network_container_id is not None else ("write_local",),
            permission_scope="bash:execute",
            timeout_seconds=None,
            max_retries=0,
        )},
    )
    def bash(
        command: str,
        description: str,
        config: RunnableConfig,
        workdir: str = ".",
    ):
        context = require_gateway_context(config, prompts=prompts)
        if context.accepted_request_digest is None:
            raise PermissionError(prompts.render('tools.bash.acceptance_missing'))
        try:
            result = service.execute(
                BashArgs.model_validate(
                    {"command": command, "description": description, "workdir": workdir}, context=prompts,
                ),
                execution_scope=context.execution_scope,
                action_id=context.tool_call_id,
                request_digest=context.accepted_request_digest,
            )
        except TimeoutError as error:
            raise ToolError(str(error), kind="unrecoverable") from error
        succeeded = result.receipt.status == "succeeded"
        return result.shell_output(), ToolArtifact(
            ok=succeeded,
            data=result.model_dump(mode="json"),
            evidence=[],
            error_kind=None if succeeded else "unrecoverable",
        )

    return bash
