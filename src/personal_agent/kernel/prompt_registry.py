from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    version: str
    template: str
    output_contract: str = "free_text"
    owner: str = "personal_agent"

    def render(self, **variables: Any) -> str:
        return self.template.format(**variables)


@dataclass(frozen=True, slots=True)
class PromptTranslation:
    source_version: str
    version: str
    template: str


@dataclass(frozen=True, slots=True)
class PromptCatalog:
    """Instance-bound language resources; schema localization is a read-only projection."""

    language: str
    prompts: Mapping[str, PromptSpec]
    metadata_translations: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompts", MappingProxyType(dict(self.prompts)))
        object.__setattr__(self, "metadata_translations", MappingProxyType(dict(self.metadata_translations)))

    def get(self, name: str) -> PromptSpec:
        try:
            return self.prompts[name]
        except KeyError as exc:
            raise KeyError(f"Unknown prompt: {name}") from exc

    def render(self, name: str, **variables: Any) -> str:
        return self.get(name).render(**variables)

    def localize_metadata(self, text: str) -> str:
        if self.language == "zh" or not any("\u3400" <= ch <= "\u9fff" for ch in text):
            return text
        try:
            return self.metadata_translations[text]
        except KeyError as exc:
            raise ValueError(f"Missing {self.language} schema metadata translation: {text!r}") from exc

    def localize_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(schema)

        def visit(value: Any) -> None:
            if not isinstance(value, dict):
                return
            for key in ("description", "title"):
                if isinstance(value.get(key), str):
                    value[key] = self.localize_metadata(value[key])
            for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas", "dependencies"):
                children = value.get(key)
                if isinstance(children, dict):
                    for child in children.values():
                        visit(child)
            for key in ("items", "additionalItems", "contains", "additionalProperties",
                        "unevaluatedProperties", "unevaluatedItems", "propertyNames",
                        "not", "if", "then", "else", "contentSchema"):
                child = value.get(key)
                if isinstance(child, list) and key == "items":
                    for item in child:
                        visit(item)
                else:
                    visit(child)
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                children = value.get(key)
                if isinstance(children, list):
                    for child in children:
                        visit(child)

        visit(result)
        return result
