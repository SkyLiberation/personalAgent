"""模型产物写入的版本化工具说明。"""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "artifact.write.description": PromptSpec(
        name="artifact.write.description",
        version="v1",
        owner="artifacts",
        output_contract="WriteArtifactArgs -> ArtifactWriteReceipt",
        template="保存本任务的新 Python 程序或 JSON 配置；create 新建，patch 按确切 base_ref 的行列范围生成新快照。保存成功不代表执行或研究完成。",
    ),
}
