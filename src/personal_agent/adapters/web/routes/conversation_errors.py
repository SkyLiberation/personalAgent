"""Safe public projection of Conversation failures for REST and SSE."""

from typing import NotRequired, TypedDict

from personal_agent.application.conversation.errors import (
    ConversationFailure,
    ConversationFailureReason,
    ConversationFailureStage,
)


class ConversationFailureDetail(TypedDict):
    message: str
    reason_code: ConversationFailureReason
    failure_stage: ConversationFailureStage
    retryable: bool
    provider_status_code: NotRequired[int]
    provider_response_complete: NotRequired[bool]


_OUTPUT_FAILURE_STAGES = frozenset({
    "provider_structured_decode",
    "provider_action_decode",
    "application_action_decode",
})


def conversation_failure_status_code(error: Exception) -> int:
    """Map local response status without rewriting the upstream status fact."""
    if not isinstance(error, ConversationFailure):
        return 500
    if error.failure_stage in _OUTPUT_FAILURE_STAGES:
        return 502
    if error.failure_stage == "provider_request":
        if error.reason_code == "provider_timeout":
            return 504
        if (
            error.retryable
            and error.provider_status_code in {429, 503}
        ):
            return 503
        return 502
    return 500


def conversation_failure_detail(
    error: Exception,
) -> ConversationFailureDetail:
    """Expose only stable facts; model output and internal messages stay private."""
    if not isinstance(error, ConversationFailure):
        return ConversationFailureDetail(
            message="对话执行发生内部错误。",
            reason_code="runtime_failure",
            failure_stage="application_runtime",
            retryable=False,
        )
    status_code = conversation_failure_status_code(error)
    if error.failure_stage in _OUTPUT_FAILURE_STAGES:
        message = "模型输出不符合当前协议，无法完成本次请求。"
    elif status_code == 504:
        message = "上游模型请求超时。"
    elif status_code == 503:
        message = "上游模型服务暂时过载。"
    elif error.failure_stage == "provider_request":
        message = "上游模型请求失败。"
    elif error.reason_code == "model_not_configured":
        message = "对话模型尚未配置。"
    elif error.failure_stage == "model_capacity":
        message = "当前模型请求超过容量边界，或部署容量配置不匹配。"
    elif error.reason_code == "run_deadline_exceeded":
        message = "本次任务已达到运行时限。"
    elif error.reason_code == "model_token_budget_exhausted":
        message = "本次任务已达到模型用量额度。"
    elif error.failure_stage == "application_dependency":
        message = "对话所需的依赖尚未就绪。"
    else:
        message = "对话执行发生内部错误。"
    detail = ConversationFailureDetail(
        message=message,
        reason_code=error.reason_code,
        failure_stage=error.failure_stage,
        retryable=error.retryable,
    )
    if error.provider_status_code is not None:
        detail["provider_status_code"] = error.provider_status_code
    if error.provider_response_complete is not None:
        detail["provider_response_complete"] = error.provider_response_complete
    return detail
