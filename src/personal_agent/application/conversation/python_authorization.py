"""Validate the Python authorization bound to a Conversation run."""

from personal_agent.application.python_execution.models import PythonExecutionAuthorization

from .models import InteractionTrace


def require_python_authorization(
    trace: InteractionTrace, authorization: PythonExecutionAuthorization | None,
) -> PythonExecutionAuthorization:
    if (authorization is None or authorization.authorization_digest != trace.python_authorization_digest
            or authorization.authorized_principal != trace.principal
            or authorization.conversation_id != trace.conversation_id
            or authorization.max_execution_seconds != trace.max_execution_seconds
            or trace.run_deadline_at is None or trace.run_deadline_at > authorization.expires_at):
        raise PermissionError("原Python分析授权不可用或绑定已变化")
    return authorization
