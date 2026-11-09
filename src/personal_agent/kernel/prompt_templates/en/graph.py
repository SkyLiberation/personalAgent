"""English personal knowledge graph extraction instructions."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "graphiti.custom_extraction": PromptTranslation(
        'v1-md1', 'v1-en.1-md1',
        """

## Extraction task
Extract entities and relationships for a personal knowledge graph.

## Priorities
Prioritize:
- people, organizations, projects, systems, and technical concepts
- decisions, dependencies, causes, tradeoffs, and applications
- facts that connect a concept to a project, problem, strategy, or outcome

## Normalization
When possible:
- normalize the same concept under one stable name
- preserve directional relationships such as "depends on", "causes", "applies to", "belongs to"
- avoid vague entities like "this", "that", or generic pronouns""",
    ),
}
