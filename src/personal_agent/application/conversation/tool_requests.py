"""Exact typed requests accepted before this conversation's durable tools run."""

from pydantic import BaseModel, ConfigDict, Field
from personal_agent.application.artifacts.models import (
    DRAFT_MAX_EDITS,
    ArtifactWriteRequest,
    CreateArtifact,
    PatchArtifact,
    TextEdit,
    TextPosition,
    TextPositionInput,
    TextRange,
)


CREATE_ARTIFACT_ACTION = "tool_create_artifact"
PATCH_ARTIFACT_ACTION = "tool_patch_artifact"


class WriteArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ArtifactWriteRequest


class ArtifactPatchEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start_line: TextPositionInput = Field(description="起点行号，从 1 开始。")
    start_column: TextPositionInput = Field(description="起点 Unicode 字符列，从 1 开始。")
    end_line: TextPositionInput = Field(description="终点行号，从 1 开始。")
    end_column: TextPositionInput = Field(description="终点 Unicode 字符列，从 1 开始。终点不包含在替换范围内。")
    new_text: str = Field(description="写入该范围的完整替换文本。以空字符串替换非空范围会删除该范围。")

    def to_text_edit(self) -> TextEdit:
        start = TextPosition.model_validate({"line": self.start_line, "column": self.start_column})
        end = TextPosition.model_validate({"line": self.end_line, "column": self.end_column})
        return TextEdit(range=TextRange(start=start, end=end), new_text=self.new_text)


class ArtifactPatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_resource_id: str = Field(min_length=1, description="当前可读草稿的resource_id；按该确切快照的行列范围修改。")
    edits: tuple[ArtifactPatchEdit, ...] = Field(
        min_length=1,
        max_length=DRAFT_MAX_EDITS,
        description="同一基稿上的编辑数组。单次编辑也直接放进数组。每项提供起止行列和替换正文。",
    )

    def to_request(self) -> PatchArtifact:
        return PatchArtifact(
            operation="patch",
            base_resource_id=self.base_resource_id,
            edits=tuple(edit.to_text_edit() for edit in self.edits),
        )


def decode_artifact_write_arguments(action_name: str, payload: dict[str, object]) -> WriteArtifactArgs:
    if action_name == PATCH_ARTIFACT_ACTION:
        return WriteArtifactArgs(request=ArtifactPatchArguments.model_validate(payload).to_request())
    if action_name == CREATE_ARTIFACT_ACTION:
        return WriteArtifactArgs(request=CreateArtifact.model_validate({**payload, "operation": "create"}))
    # Recovery can still be bound to an older, already dispatched declaration.
    return WriteArtifactArgs.model_validate(payload)
