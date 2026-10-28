from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptSpec


PROMPTS: dict[str, PromptSpec] = {
    "graphiti.custom_extraction": PromptSpec(
        name="graphiti.custom_extraction",
        version='v1-md1',
        output_contract="GraphitiExtractionInstructions",
        template=(
            """

## 提取任务
Extract entities and relationships for a personal knowledge graph.

## 优先内容
Prioritize:
- people, organizations, projects, systems, and technical concepts
- decisions, dependencies, causes, tradeoffs, and applications
- facts that connect a concept to a project, problem, strategy, or outcome

## 规范化
When possible:
- normalize the same concept under one stable name
- preserve directional relationships such as "depends on", "causes", "applies to", "belongs to"
- avoid vague entities like "this", "that", or generic pronouns"""
        ),
    ),
}
