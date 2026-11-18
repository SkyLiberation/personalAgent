"""Shell commands in the authorized Conversation workspace."""
from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "bash_execution.description": PromptSpec(
        name="bash_execution.description", version="v1-workspace", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在隔离容器中执行 Bash 命令。默认目录是只读 /workspace，"
            "用户附件在 attachments/，可用 ls 或 find 确认文件名。"
            "会话工具原件可用回执提供的相对路径读取。"
            "可调用 python，使用 /tmp 保存本次命令的中间文件。"
            "输出包含 stdout、stderr 和退出状态。每次命令独立运行。"
        ),
    ),
    "bash_execution.shared_workspace": PromptSpec(
        name="bash_execution.shared_workspace", version="v1-shared-workspace", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在隔离容器中执行 Bash 命令。默认工作目录是可写任务目录 {workspace_root}，"
            "其中的文件与接入的 MCP 工具共享。用 ls 查看现有文件，在该目录保存和回读交付文件。"
            "只读附件和工具回执文件的相对路径以 {inputs_root} 为基准。"
            "可用 /tmp 保存单次命令的临时文件。输出包含 stdout、stderr 和退出状态。"
        ),
    ),
    **{
        f"bash_execution.parameter.{name}": PromptSpec(
            name=f"bash_execution.parameter.{name}", version="v2" if name == "workdir" else "v1",
            owner="bash_execution", template=description,
        )
        for name, description in {
            "command": "要运行的 Bash 命令，可包含多行。最多 128 KiB。",
            "description": "简述此次命令的用途。",
            "workdir": "相对于当前工作区根目录的工作目录，默认为工作区根目录。",
        }.items()
    },
}
