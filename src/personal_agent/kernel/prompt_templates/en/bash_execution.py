"""English shell tool instructions."""
from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "bash_execution.description": PromptTranslation(
        "v1-workspace", "v1-workspace-en.1",
        "Run Bash in an isolated container. The default directory is the read-only /workspace. "
        "User attachments are under attachments/. Use ls or find to discover names. "
        "Read saved tool results at the relative paths from their tool receipts. "
        "You can use python and store temporary files in /tmp for this command. "
        "The result includes stdout, stderr, and exit status. Each command runs independently.",
    ),
    "bash_execution.shared_workspace": PromptTranslation(
        "v1-shared-workspace", "v1-shared-workspace-en.1",
        "Run Bash in an isolated container. The default working directory is the writable task directory "
        "{workspace_root}, shared with the connected MCP tools. Use ls to discover files and save and reread "
        "deliverables there. Resolve relative paths for read-only attachments and saved tool results from "
        "{inputs_root}. Use /tmp for temporary files within a command. The result includes stdout, stderr, and exit status.",
    ),
    "bash_execution.task_workspace": PromptTranslation(
        "v2-task-tmp", "v2-task-tmp-en.1",
        "Run Bash in an isolated container. The default directory is read-only /workspace, "
        "with user attachments under attachments/. Save scripts, extracted data, and intermediate results in "
        "{temp_dir}. These files are available to later commands and user turns in the same authorized "
        "analysis task. They are cleared when the task container is removed. Each command starts a fresh "
        "Bash process. The result includes stdout, stderr, and exit status.",
    ),
    "bash_execution.task_workspace_unavailable": PromptTranslation(
        "v2", "v2-en.1",
        "This command could not use the task's container workspace and did not run. Resume the original task "
        "or create a workspace in a new authorized conversation.",
    ),
    **{
        f"bash_execution.parameter.{name}": PromptTranslation(
            "v2" if name == "workdir" else "v1", "v2-en.1" if name == "workdir" else "v1-en.1", description,
        )
        for name, description in {
            "command": "Bash command to execute, including multiline commands. At most 128 KiB.",
            "description": "Brief purpose of this command.",
            "workdir": "Working directory relative to the workspace root. Defaults to the workspace root.",
        }.items()
    },
}
