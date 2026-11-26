"""Conversation skill discovery and loading metadata."""

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS = {
    "skills.load_description": PromptSpec(
        name="skills.load_description", version="v3", owner="skills",
        output_contract="LoadSkillArgs -> installed skill instructions",
        template=(
            "按当前步骤目录中的准确名称读取技能完整说明。用户点名某项技能，或任务明确匹配目录摘要时，"
            "先单独调用本工具读取说明，再按说明执行相关任务操作。"
        ),
    ),
    "skills.catalog": PromptSpec(
        name="skills.catalog", version="v1", owner="skills",
        template="## 当前会话可用技能\n<available_skills>\n{catalog}\n</available_skills>",
    ),
    "skills.loaded": PromptSpec(
        name="skills.loaded", version="v1", owner="skills",
        template=(
            "已加载技能 `{skill_name}`。执行时遵循下方完整说明。"
            "当规则给出默认做法和例外时，用用户的原话核对例外条件；证据不足时采用默认做法。"
            "\n\n<skill_instructions>\n{instructions}\n</skill_instructions>"
        ),
    ),
    "skills.repeat_notice": PromptSpec(
        name="skills.repeat_notice", version="skill-repeat-v1", owner="skills",
        template=(
            "[Runtime 重复调用提醒] 你已连续 {count} 次用相同参数加载技能 `{skill_name}`。"
            "请先查看最近一次回执。若还需要继续，选择能推进任务的下一步。已有足够信息时可以交付。"
        ),
    ),
    "skills.unknown": PromptSpec(
        name="skills.unknown", version="v2", owner="skills",
        template="该技能不可用。请核对当前会话技能目录中的准确名称。",
    ),
    "skills.resource_base": PromptSpec(
        name="skills.resource_base", version="skill-resources-v1", owner="skills",
        template=(
            "<skill_resources>\nBash 中的只读技能资源根目录为 `{path}`。"
            "用此目录解析说明中的 `scripts/` 相对路径。按任务需要另行调用 `tool_bash`。\n"
            "</skill_resources>"
        ),
    ),
    "skills.scripts_unavailable": PromptSpec(
        name="skills.scripts_unavailable", version="v1", owner="skills",
        template="当前 Bash 无法准备技能的随包脚本。请检查安装包的 scripts/ 路径、文件类型及输入大小。",
    ),
    "skills.scope_changed": PromptSpec(
        name="skills.scope_changed", version="v1", owner="skills",
        template="会话的技能作用域已变更，请开始新会话。",
    ),
}
