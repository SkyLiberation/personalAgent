from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "graphiti.custom_extraction": PromptSpec(
        name="graphiti.custom_extraction",
        version="v1",
        output_contract="GraphitiExtractionInstructions",
        template=(
            "Extract entities and relationships for a personal knowledge graph.\n\n"
            "Prioritize:\n"
            "- people, organizations, projects, systems, and technical concepts\n"
            "- decisions, dependencies, causes, tradeoffs, and applications\n"
            "- facts that connect a concept to a project, problem, strategy, or outcome\n\n"
            "When possible:\n"
            "- normalize the same concept under one stable name\n"
            "- preserve directional relationships such as \"depends on\", \"causes\", \"applies to\", \"belongs to\"\n"
            "- avoid vague entities like \"this\", \"that\", or generic pronouns"
        ),
    ),
}
