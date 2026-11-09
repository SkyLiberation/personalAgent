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
        version="v1",
        owner="artifacts",
        output_contract="CreateArtifact -> ArtifactWriteReceipt",
        template=(
            "新建 Python、JSON 或 Markdown 草稿。直接提交文件名、媒体类型和完整正文。"
            "成功后返回新草稿引用。编辑已有草稿时使用补丁工具。"
        ),
    ),
    "artifact.patch_action.description": PromptSpec(
        name="artifact.patch_action.description",
        version="v1",
        owner="artifacts",
        output_contract="ArtifactPatchArguments -> ArtifactWriteReceipt",
        template=(
            "修改当前可读草稿并返回新快照。使用实际读取或搜索得到的基稿 ID 和坐标。"
            "各项编辑均以同一基稿为准。起止坐标相同表示在该处插入。"
            "优先传正整数坐标，也接受无前导零的十进制数字字符串。\n\n"
            "插入示例。实际调用时替换示例中的基稿 ID 和坐标。\n\n"
            "```json\n"
            '{"base_resource_id":"draft_id","edits":'
            '[{"start_line":1,"start_column":1,"end_line":1,"end_column":1,"new_text":"插入的文字"}]}\n'
            "```"
        ),
    ),
}
