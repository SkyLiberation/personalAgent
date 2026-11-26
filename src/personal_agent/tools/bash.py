"""Model-facing Bash execution through the governed Tool Port."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from personal_agent.application.bash_execution.models import (
    BASH_SHARED_INPUTS_DIR, BASH_TEMP_DIR, BashArgs, BashWorkspaceFileAction,
)
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
    if workspace is not None:
        tool_description = prompts.render(
            "bash_execution.shared_workspace", workspace_root=workspace.root, inputs_root=BASH_SHARED_INPUTS_DIR,
        )
    elif service.profile.persistent_bash:
        tool_description = prompts.render("bash_execution.persistent_bash", temp_dir=BASH_TEMP_DIR)
    elif service.profile.task_workspace is not None:
        tool_description = prompts.render("bash_execution.task_workspace", temp_dir=BASH_TEMP_DIR)
    else:
        tool_description = prompts.get("bash_execution.description").template

    @tool(
        "bash",
        description=tool_description,
        args_schema=BashArgs,
        response_format="content_and_artifact",
        extras={"strict": False, **governance_extras(
            side_effects=("write_local", "external_network") if service.profile.allow_network else ("write_local",),
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
        workspace_file: BashWorkspaceFileAction | None = None,
    ):
        context = require_gateway_context(config, prompts=prompts)
        if context.accepted_request_digest is None:
            raise PermissionError(prompts.render('tools.bash.acceptance_missing'))
        try:
            result = service.execute(
                BashArgs.model_validate(
                    {"command": command, "description": description, "workdir": workdir,
                     "workspace_file": workspace_file}, context=prompts,
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
