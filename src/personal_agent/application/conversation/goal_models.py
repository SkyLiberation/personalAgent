"""Conversation-owned execution-goal proposals and immutable accepted facts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .history_models import HistoryItemKey


def goal_verification_action_id(run_ref: str, decision_turn: int, call_id: str) -> str:
    return f"{run_ref}:goal:{decision_turn}:{call_id}"


class AnalysisGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    objective: str = Field(min_length=1, max_length=20_000, description="完整任务定义正文，一个非空字符串。用Markdown分别写本轮交付、对象与判定关系、有效约束与未决事项、完成条件与依据；依据原用户要求和有效历史确定含义，明确影响结果的指代及关系。修订完整替换并保留未改要求，不提交额外业务字段，不用提纲、自述或结果猜测代替正文。")


class AnalysisGoalRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_ref: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RetainGoalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoalMaintenanceInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    call_id: str = Field(min_length=1)
    arguments: AnalysisGoal | None


class ReadCurrentGoalArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GoalReadInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    call_id: str = Field(min_length=1)
    arguments: ReadCurrentGoalArguments


class GoalOperationRecord(BaseModel):
    """One accepted operation/result; the Journal is its only write owner."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_ref: str
    call_id: str
    decision_turn: int = Field(ge=1)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: Literal["create", "revise", "retain", "read"]
    base_goal_ref: AnalysisGoalRef | None
    goal_ref: AnalysisGoalRef
    goal: AnalysisGoal
    verification_ref: HistoryItemKey | None = None


class CurrentAnalysisGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: AnalysisGoalRef
    goal: AnalysisGoal


class GoalModelView(BaseModel):
    """Read-only current version; Runtime owns the full branch binding."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    revision: int = Field(ge=1)
    goal: AnalysisGoal


class GoalOperationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    operation: Literal["create", "revise", "retain", "read"]
    current_goal: GoalModelView
