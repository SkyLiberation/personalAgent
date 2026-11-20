"""模型产物写入的版本化工具说明。"""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "artifact.write.description": PromptSpec(
        name="artifact.write.description",
        version="v6-canonical-write",
        owner="artifacts",
        output_contract="WriteArtifactArgs -> ArtifactWriteReceipt",
        template="保存本任务的 Python 程序、JSON 配置或 Markdown 草稿。创建或编辑后返回新快照。",
    ),
    "artifact.create_action.description": PromptSpec(
        name="artifact.create_action.description",
        version="v2-literal-edit",
        owner="artifacts",
        output_contract="CreateArtifact -> ArtifactWriteReceipt",
        template=(
            "新建 Python、JSON 或 Markdown 草稿。直接提交文件名、媒体类型和完整正文。"
            "成功后返回新草稿引用。编辑已有草稿时使用 tool_edit。"
        ),
    ),
    "artifact.edit_action.description": PromptSpec(
        name="artifact.edit_action.description",
        version="v3-literal-edit-newlines",
        owner="artifacts",
        output_contract="LiteralTextEdit -> ArtifactWriteReceipt | BashToolResult",
        template=(
            "精确编辑已有 UTF-8 文件。file_path 使用实际路径，当前可用前缀为 {paths}。"
            "从读取结果或当前会话刚完成的写入获取原文。匹配保留空格和缩进，统一 CRLF 和 LF。"
            "默认要求恰好一次匹配。replace_all 为 true 时替换全部匹配。"
            "Artifact 返回新快照路径。任务工作区文件原地更新。"
        ),
    ),
    "artifact.edit_action.workspace_guard": PromptSpec(
        name="artifact.edit_action.workspace_guard", version="v1", owner="artifacts",
        template=(
            "编辑 /tmp 文件前先用 tool_read_file 读取该路径。上一次成功编辑已记录新版本，可以继续编辑。"
            "通过 Bash 创建或改写文件后，先用 tool_read_file 取得当前版本。"
        ),
    ),
    "artifact.edit_action.workspace_read": PromptSpec(
        name="artifact.edit_action.workspace_read", version="v1", owner="artifacts",
        template="也可读取任务沙箱 /tmp 下的文件。此读取记录文件版本，供 tool_edit 使用。",
    ),
    **{
        f"artifact.edit_action.field.{name}": PromptSpec(
            name=f"artifact.edit_action.field.{name}", version="v1", owner="artifacts", template=description,
        )
        for name, description in {
            "file_path": "读取回执或 Artifact 写入回执所对应的实际文件路径。",
            "old_string": "要替换的非空原文，保留空格和缩进。",
            "new_string": "字面替换文本。空字符串删除匹配。",
            "replace_all": "替换所有匹配。默认 false，要求 old_string 恰好匹配一次。",
        }.items()
    },
}
