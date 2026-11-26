"""Shell commands in the authorized Conversation workspace."""
from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "bash_execution.description": PromptSpec(
        name="bash_execution.description", version="v2-native-workspace", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在 Linux 本机沙箱中执行 Bash 命令。默认目录是只读 /workspace，"
            "用户附件在 attachments/，可用 ls 或 find 确认文件名。"
            "会话工具原件可用回执提供的相对路径读取。"
            "可调用 python，使用 /tmp 保存本次命令的中间文件。"
            "输出包含 stdout、stderr 和退出状态。每次命令独立运行。"
        ),
    ),
    "bash_execution.shared_workspace": PromptSpec(
        name="bash_execution.shared_workspace", version="v3-native-workspace", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在 Linux 本机沙箱中执行 Bash 命令。默认工作目录是可写任务目录 {workspace_root}，"
            "其中的文件与接入的 MCP 工具共享。用 ls 查看现有文件，在该目录保存和回读交付文件。"
            "用户上传的只读附件位于 {inputs_root}/attachments/。"
            "可用 /tmp 保存单次命令的临时文件。输出包含 stdout、stderr 和退出状态。"
        ),
    ),
    "bash_execution.task_workspace": PromptSpec(
        name="bash_execution.task_workspace", version="v3-native-task-tmp", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在 Linux 本机沙箱中执行 Bash。默认目录是只读 /workspace，用户附件在 attachments/。"
            "脚本、解压数据和中间结果可保存在 {temp_dir}。同一授权分析任务内，"
            "这些文件可供后续命令和用户轮次使用，任务工作区关闭时清除。"
            "每次命令启动独立 Bash。"
            "输出包含 stdout、stderr 和退出状态。"
        ),
    ),
    "bash_execution.persistent_bash": PromptSpec(
        name="bash_execution.persistent_bash", version="v1", owner="bash_execution",
        output_contract="BashArgs -> BashToolResult",
        template=(
            "在同一授权任务的持久 Bash 沙箱中执行命令。初始目录 /workspace 只读，附件在 attachments/。"
            "工作目录、Shell 状态和后台进程可跨命令与用户轮次复用。"
            "使用 {temp_dir} 保存可写文件。命令超时或终端退出会结束该 Shell 和其中的后台进程。"
            "输出包含 stdout、stderr 和退出状态。"
        ),
    ),
    "bash_execution.task_workspace_unavailable": PromptSpec(
        name="bash_execution.task_workspace_unavailable", version="v3", owner="bash_execution",
        template="当前调用无法使用此任务的沙箱工作区，命令尚未执行。恢复原任务或在新的授权会话重建工作区。",
    ),
    **{
        f"bash_execution.parameter.{name}": PromptSpec(
            name=f"bash_execution.parameter.{name}", version="v3" if name == "workdir" else "v1",
            owner="bash_execution", template=description,
        )
        for name, description in {
            "command": "要运行的 Bash 命令，可包含多行。最多 128 KiB。",
            "description": "简述此次命令的用途。",
            "workdir": "相对于工作区根目录的工作目录。省略时，持久 Bash 使用当前目录，普通 Bash 从工作区根目录起步。",
        }.items()
    },
}
