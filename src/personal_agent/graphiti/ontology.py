from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("industry", mode="before")
    @classmethod
    def _normalize_industry(cls, value: Any) -> str | None:
        normalized = _coerce_to_text(value)
        return normalized or None


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


def _coerce_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ""
        if stripped[0] in {"[", "{"}:
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            return _coerce_to_text(parsed)
        return stripped
    if isinstance(value, list):
        parts = [_coerce_to_text(item) for item in value]
        joined = "；".join(part for part in parts if part)
        return joined
    if isinstance(value, dict):
        preferred_keys = ("industry", "name", "summary", "description", "entity_type")
        for key in preferred_keys:
            candidate = _coerce_to_text(value.get(key))
            if candidate:
                return candidate
        compact = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return compact
    return str(value).strip()
