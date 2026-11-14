"""Conversation-owned execution-goal proposals and immutable accepted facts."""
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from personal_agent.application.artifacts.models import DRAFT_MAX_BYTES
from .history_models import HistoryItemKey
from personal_agent.kernel.contracts.resource import ResourceRef

GOAL_PENDING_ACTION_REJECTED = "provider_action_unavailable_goal_pending"
SUBMIT_GOAL_PATCH = "submit_goal_patch"

GoalItemId = Annotated[str, StringConstraints(pattern=r"^i[1-9][0-9]*$")]
GoalItemKind = Literal["requirement", "constraint"]
GoalItemScope = Literal["task", "turn"]
GoalTaskAction = Literal["continue", "start", "side_question", "resume"]
GoalDeliveryMode = Literal["review_plan", "deliver_final_result", "background"]
GoalTaskId = Annotated[str, StringConstraints(min_length=1)]
ExecutionMode = Literal["running", "read_only", "paused"]
GoalText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8_000)]
EvidenceQuote = Annotated[str, StringConstraints(min_length=1, max_length=8_000)]


def goal_verification_action_id(run_ref: str, decision_turn: int, call_id: str) -> str:
    return f"{run_ref}:goal:{decision_turn}:{call_id}"


class GoalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    item_id: GoalItemId
    kind: GoalItemKind
    scope: GoalItemScope
    text: GoalText
    status: Literal["active", "revoked"] = "active"
    source_message_ids: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[GoalText, ...] = ()


class GoalExecutionControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: ExecutionMode
    source_message_id: str


class AnalysisGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    objective: str = Field(max_length=20_000)
    goal_id: str | None = None
    items: tuple[GoalItem, ...] = ()

    def active_items(self, run_ref: str) -> tuple[GoalItem, ...]:
        return tuple(item for item in self.items if item.status == "active" and (
            item.scope == "task" or item.source_message_ids[-1].startswith(f"{run_ref}:user:")
        ))

    def verification_text(self, run_ref: str, control: GoalExecutionControl | None = None,
                          delivery: "SetGoalDelivery | None" = None) -> str:
        if self.goal_id is None:
            return self.objective
        items = self.active_items(run_ref)
        objective = self.objective or next((item.text for item in items if item.kind == "requirement"), "")
        snapshot = {
            "goal_id": self.goal_id, "objective": objective,
            "items": {item.item_id: item.model_dump(mode="json", exclude={"item_id"})
                      for item in items},
            "execution_control": control.model_dump(mode="json") if control else None,
        }
        if delivery is not None:
            snapshot["delivery"] = delivery.model_dump(mode="json")
        return json.dumps(snapshot, ensure_ascii=False, indent=2)

    @field_validator("objective")
    @classmethod
    def validate_draft_size(cls, objective: str) -> str:
        if len(objective.encode("utf-8")) > DRAFT_MAX_BYTES:
            raise ValueError(f"objective exceeds the {DRAFT_MAX_BYTES}-byte UTF-8 draft limit")
        return objective


class AnalysisGoalRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_ref: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _GoalChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence: EvidenceQuote = Field(description="支持这项变更的本轮用户原话片段。逐字引用。")


class _GoalItemContent(_GoalChange):
    text: GoalText = Field(description="按用户原话写明要求或约束及其适用关系。")


class AddGoalItem(_GoalItemContent):
    op: Literal["add"]
    acceptance_criteria: tuple[GoalText, ...] = Field(
        default=(), description="该条目可用实际证据检查的验收条件。没有独立条件时留空。",
    )
    kind: GoalItemKind = Field(description="requirement 表示用户需要的结果。constraint 表示执行或结果须遵守的限制。")
    scope: GoalItemScope = Field(description="task 表示后续轮仍适用。turn 表示只适用于本轮交付。")


class ReplaceGoalItem(_GoalItemContent):
    op: Literal["replace"]
    item_id: GoalItemId = Field(description="用户明确修改的现有有效条目 ID。")
    acceptance_criteria: tuple[GoalText, ...] | None = Field(
        default=None, description="验收条件明确变化时提交完整的新条件。省略时保留原有条件。",
    )


class RevokeGoalItem(_GoalChange):
    op: Literal["revoke"]
    item_id: GoalItemId = Field(description="用户明确撤销的现有有效条目 ID。")


class ChangeExecutionControl(_GoalChange):
    mode: ExecutionMode = Field(description="paused 暂停业务动作。read_only 仅允许只读动作。running 恢复通常的执行权限。")


class ResolveGoalClarification(_GoalChange):
    clarification_id: str = Field(min_length=1, description="待澄清区块中已由本轮用户回答或撤回的问题 ID。")


class SelectGoalTask(_GoalChange):
    action: GoalTaskAction = Field(
        description="continue 延续当前任务，start 开始独立任务，side_question 临时插问，resume 恢复旧任务。",
    )
    task_id: GoalTaskId | None = Field(default=None, description="仅 resume 填写可恢复任务视图中的 ID。")


class SetGoalDelivery(_GoalChange):
    mode: GoalDeliveryMode = Field(description=(
        "review_plan 表示先交计划并等待审阅，deliver_final_result 表示完成此前待审的工作，"
        "background 表示用户要求本次响应返回后仍继续执行。"
    ))


GoalChange = Annotated[AddGoalItem | ReplaceGoalItem | RevokeGoalItem, Field(discriminator="op")]


class _GoalPatchEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task: SelectGoalTask | None = Field(default=None, description="本轮首次提交选择任务，后续修订省略。")
    delivery: SetGoalDelivery | None = Field(default=None, description="仅在本轮首次提交时声明用户明确指定的交付方式。普通交付省略。")
    base_version: int = Field(strict=True, ge=0, description="选中任务的快照版本。新开和插问填 0。")
    clarifications: tuple[GoalText, ...] = Field(
        default=(), max_length=8, description="影响执行且原话无法解决时，填写需要用户回答的具体问题。",
    )
    execution_control: ChangeExecutionControl | None = Field(
        default=None, description="仅在用户明确改变执行限制时填写。省略时保留现有限制。",
    )
    resolve_clarification: ResolveGoalClarification | None = Field(
        default=None, description="只在本轮用户已回答或撤回一个待澄清事项时填写。省略时保留该事项。",
    )


class GoalPatch(_GoalPatchEnvelope):
    changes: tuple[GoalChange, ...] = Field(max_length=64)


class GoalChangeProposal(_GoalChange):
    op: Literal["add", "replace", "revoke"] = Field(
        description="add 填 kind、scope、text。replace 填 item_id、text。revoke 只填 item_id 和 evidence。",
    )
    item_id: GoalItemId | None = Field(default=None, description="replace 或 revoke 使用的现有有效条目 ID。")
    kind: GoalItemKind | None = Field(default=None, description="仅 add 填写。requirement 是结果要求，constraint 是限制。")
    scope: GoalItemScope | None = Field(default=None, description="仅 add 填写。task 跨轮适用，turn 仅用于本轮。")
    text: GoalText | None = Field(default=None, description="add 和 replace 填写的条目正文及适用条件。")
    criterion: str | None = Field(default=None, max_length=8_000,
        description="add 或 replace 的验收条件。用一个字符串，每行一项。空字符串清空，替换时省略保留已有条件。",
    )

    def patch_arguments(self) -> dict:
        arguments = self.model_dump(exclude_unset=True)
        if "criterion" in arguments:
            criterion = arguments.pop("criterion")
            arguments["acceptance_criteria"] = (
                tuple(line.strip() for line in criterion.splitlines() if line.strip()) if criterion is not None else None
            )
        return arguments


class GoalPatchProposal(_GoalPatchEnvelope):
    """Model protocol for the existing, version-bound goal patch."""

    changes: tuple[GoalChangeProposal, ...] = Field(
        max_length=64, description="仅提交本轮新增、明确修改或撤销的条目。没有变更时提交空数组。",
    )

    @classmethod
    def tool_schema(cls) -> dict:
        schema = cls.model_json_schema()
        schema["properties"]["changes"]["items"] = schema["$defs"].pop("GoalChangeProposal")
        return schema

    def to_patch(self) -> GoalPatch:
        return GoalPatch.model_validate({
            **self.model_dump(exclude={"changes"}),
            "changes": [change.patch_arguments() for change in self.changes],
        })


class GoalMaintenanceInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    call_id: str = Field(min_length=1)
    arguments: GoalPatch


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
    operation: Literal["create", "revise", "retain", "read", "control", "resolve"]
    base_goal_ref: AnalysisGoalRef | None
    goal_ref: AnalysisGoalRef
    goal: AnalysisGoal
    patch: GoalPatch | None = None
    execution_control: GoalExecutionControl | None = None
    verification_ref: HistoryItemKey | None = None
    draft_ref: ResourceRef | None = None

    def verification_text(self) -> str:
        return self.goal.verification_text(self.run_ref, self.execution_control,
                                           self.patch.delivery if self.patch is not None else None)


class CurrentAnalysisGoal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reference: AnalysisGoalRef
    goal: AnalysisGoal
    execution_control: GoalExecutionControl | None = None

    def verification_text(self, run_ref: str) -> str:
        return self.goal.verification_text(run_ref, self.execution_control)
