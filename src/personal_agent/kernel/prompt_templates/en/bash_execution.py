"""English shell tool instructions."""
from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "bash_execution.description": PromptTranslation(
        "v2-native-workspace", "v2-native-workspace-en.1",
        "Run Bash in a native Linux sandbox. The default directory is the read-only /workspace. "
        "User attachments are under attachments/. Use ls or find to discover names. "
        "Read saved tool results at the relative paths from their tool receipts. "
        "You can use python and store temporary files in /tmp for this command. "
        "The result includes stdout, stderr, and exit status. Each command runs independently.",
    ),
    "bash_execution.shared_workspace": PromptTranslation(
        "v3-native-workspace", "v3-native-workspace-en.1",
        "Run Bash in a native Linux sandbox. The default working directory is the writable task directory "
        "{workspace_root}, shared with the connected MCP tools. Use ls to discover files and save and reread "
        "deliverables there. User-uploaded attachments are read-only under {inputs_root}/attachments/. "
        "Use /tmp for temporary files within a command. The result includes stdout, stderr, and exit status.",
    ),
    "bash_execution.task_workspace": PromptTranslation(
        "v3-native-task-tmp", "v3-native-task-tmp-en.1",
        "Run Bash in a native Linux sandbox. The default directory is read-only /workspace, "
        "with user attachments under attachments/. Save scripts, extracted data, and intermediate results in "
        "{temp_dir}. These files are available to later commands and user turns in the same authorized "
        "analysis task. They are cleared when the task workspace closes. Each command starts a fresh "
        "Bash process. The result includes stdout, stderr, and exit status.",
    ),
    "bash_execution.persistent_bash": PromptTranslation(
        "v1", "v1-en.1",
        "Run commands in the persistent Bash sandbox for this authorized task. The initial directory /workspace "
        "is read-only, with attachments under attachments/. The working directory, shell state, and background "
        "processes are shared across commands and user turns. Use {temp_dir} for writable files. A command timeout "
        "or shell exit ends the shell and its background processes. The result includes stdout, stderr, and exit status.",
    ),
    "bash_execution.task_workspace_unavailable": PromptTranslation(
        "v3", "v3-en.1",
        "This command could not use the task's sandbox workspace and did not run. Resume the original task "
        "or create a workspace in a new authorized conversation.",
    ),
    **{
        f"bash_execution.parameter.{name}": PromptTranslation(
            "v3" if name == "workdir" else "v1", "v3-en.1" if name == "workdir" else "v1-en.1", description,
        )
        for name, description in {
            "command": "Bash command to execute, including multiline commands. At most 128 KiB.",
            "description": "Brief purpose of this command.",
            "workdir": "Working directory relative to the workspace root. If omitted, persistent Bash uses its current directory and per-command Bash starts at the workspace root.",
        }.items()
    },
}
