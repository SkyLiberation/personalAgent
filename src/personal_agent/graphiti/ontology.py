from __future__ import annotations

from pydantic import BaseModel, Field


class PersonEntity(BaseModel):
    role: str | None = Field(default=None, description="The person's role, title, or responsibility.")


class ProjectEntity(BaseModel):
    objective: str | None = Field(default=None, description="The project's goal or business purpose.")
    status: str | None = Field(default=None, description="The current status or lifecycle stage.")


class ConceptEntity(BaseModel):
    definition: str | None = Field(default=None, description="A concise explanation of the concept.")
    domain: str | None = Field(default=None, description="The domain or discipline where the concept belongs.")


class OrganizationEntity(BaseModel):
    industry: str | None = Field(default=None, description="The organization's industry or area of work.")


class SourceEntity(BaseModel):
    source_kind: str | None = Field(default=None, description="The content format such as note, article, meeting, or book.")


ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": PersonEntity,
    "Project": ProjectEntity,
    "Concept": ConceptEntity,
    "Organization": OrganizationEntity,
    "Source": SourceEntity,
}


CUSTOM_EXTRACTION_INSTRUCTIONS = """
Extract entities and relationships for a personal knowledge graph.

Prioritize:
- people, organizations, projects, systems, and technical concepts
- decisions, dependencies, causes, tradeoffs, and applications
- facts that connect a concept to a project, problem, strategy, or outcome

When possible:
- normalize the same concept under one stable name
- preserve directional relationships such as "depends on", "causes", "applies to", "belongs to"
- avoid vague entities like "this", "that", or generic pronouns
""".strip()
