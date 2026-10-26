"""模型产物写入的版本化工具说明。"""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "artifact.write.description": PromptSpec(
        name="artifact.write.description",
        version="v2-artifact-id-selection",
        owner="artifacts",
        output_contract="WriteArtifactArgs -> ArtifactWriteReceipt",
        template="保存本任务的新 Python 程序或 JSON 配置；create 新建，patch 用 base_resource_id 选择当前可读草稿，按该快照的行列范围生成新快照。保存成功不代表执行或研究完成。",
    ),
}
