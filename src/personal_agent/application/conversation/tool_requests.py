"""Exact typed requests accepted before this conversation's durable tools run."""

from pydantic import BaseModel, ConfigDict

from personal_agent.application.artifacts.models import ArtifactWriteRequest, EditArtifact
from personal_agent.application.bash_execution.models import BASH_TEMP_DIR, BashArgs
from personal_agent.application.bash_execution.workspace_edit import workspace_edit_command
from personal_agent.application.text_edit import LiteralTextEdit
from personal_agent.kernel.prompt_registry import PromptCatalog

CREATE_ARTIFACT_ACTION = "tool_create_artifact"
EDIT_ACTION = "tool_edit"
READ_FILE_ACTION = "tool_read_file"


class WriteArtifactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: ArtifactWriteRequest


def decode_edit_arguments(
    payload: dict[str, object], *, prompts: PromptCatalog,
) -> tuple[str, WriteArtifactArgs | BashArgs]:
    edit = LiteralTextEdit.model_validate(payload)
    if edit.file_path.startswith(f"{BASH_TEMP_DIR}/"):
        return "bash", workspace_edit_command(edit, prompts=prompts)
    return "write_artifact", WriteArtifactArgs(request=EditArtifact(**payload, operation="edit"))
