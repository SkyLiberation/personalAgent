"""Validate the Bash authorization bound to a Conversation run."""

from personal_agent.application.bash_execution.models import BashExecutionAuthorization

from .models import InteractionTrace


def require_bash_authorization(
    trace: InteractionTrace, authorization: BashExecutionAuthorization | None,
) -> BashExecutionAuthorization:
    if (authorization is None or authorization.authorization_digest != trace.bash_authorization_digest
            or authorization.authorized_principal != trace.principal
            or authorization.conversation_id != trace.conversation_id
            or authorization.max_execution_seconds != trace.max_execution_seconds
            or trace.run_deadline_at is None):
        raise PermissionError("原Bash分析授权不可用或绑定已变化")
    return authorization
