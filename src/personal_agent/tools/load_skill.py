"""Expose an installed skill catalog and a read-only named loading action."""

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict

from personal_agent.application.conversation.skills import (
    LOAD_SKILL_CAPABILITY, LoadedSkill, SkillCatalog, SkillName,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.tools.base import (
    governance_extras, require_gateway_context, tool_failure, tool_response, tool_success,
)


class LoadSkillArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: SkillName


def build_load_skill_tool(catalog: SkillCatalog, *, prompts: PromptCatalog) -> BaseTool:
    @tool(
        LOAD_SKILL_CAPABILITY,
        description=prompts.get("skills.load_description").template,
        args_schema=LoadSkillArgs,
        response_format="content_and_artifact",
        extras=governance_extras(side_effects=("read_local",), permission_scope="skills:read"),
    )
    def load_skill(name: str, config: RunnableConfig):
        context = require_gateway_context(config, prompts=prompts)
        scope = context.execution_scope
        skill = catalog.visible(scope.principal, scope.thread_id, source_platform=context.source_platform).get(name)
        if skill is None:
            return tool_response(tool_failure(prompts.render("skills.unknown")), prompts=prompts)
        result = LoadedSkill(name=skill.name, instructions=skill.instructions, source=skill.source)
        return tool_response(tool_success(result.model_dump(mode="json")), prompts=prompts)

    return load_skill
