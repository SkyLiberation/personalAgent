"""Model-facing Python execution through the original governed Tool Port."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from personal_agent.application.python_execution.models import (
    ExecutePythonArgs,
    PythonInputBinding,
)
from personal_agent.application.python_execution.service import PythonExecutionService
from personal_agent.kernel.prompts import get_prompt
from personal_agent.tools.base import (
    ToolArtifact,
    ToolError,
    governance_extras,
    require_gateway_context,
    tool_response,
)


def build_execute_python_tool(service: PythonExecutionService) -> BaseTool:
    @tool(
        "execute_python",
        description=get_prompt("python_execution.description").template,
        args_schema=ExecutePythonArgs,
        response_format="content_and_artifact",
        extras={"strict": False, **governance_extras(
            side_effects=("write_local",),
            permission_scope="python:execute",
            timeout_seconds=None,
            max_retries=0,
        )},
    )
    def execute_python(
        code: str,
        config: RunnableConfig,
        input_files: tuple[PythonInputBinding, ...] = (),
    ):
        context = require_gateway_context(config)
        if context.accepted_request_digest is None:
            raise PermissionError("Python执行请求缺少已接受记录。")
        try:
            result = service.execute(
                ExecutePythonArgs(
                    code=code, input_files=input_files
                ),
                execution_scope=context.execution_scope,
                action_id=context.tool_call_id,
                request_digest=context.accepted_request_digest,
            )
        except TimeoutError as error:
            raise ToolError(str(error), kind="unrecoverable") from error
        succeeded = result.receipt.status == "succeeded"
        return tool_response(
            ToolArtifact(
                ok=succeeded,
                data=result.model_dump(mode="json"),
                evidence=[],
                error=None
                if succeeded
                else f"Python实际执行状态：{result.receipt.status}；{result.receipt.error_code or '请读回执和诊断原件'}",
                error_kind=None if succeeded else "unrecoverable",
            )
        )

    return execute_python
