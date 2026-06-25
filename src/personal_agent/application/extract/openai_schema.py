"""Schema construction for the LangExtract pre-extraction layer.

LangExtract's ``OpenAISchema.from_examples`` auto-derives a JSON schema from
the few-shot ExampleData but only infers types — it cannot lift Python literal
values into JSON-Schema ``enum`` constraints. This module overrides the
auto-derived schema for fields that benefit from stricter enforcement,
notably ``information_density`` (high/medium/low).

The resulting schema is hand-crafted to mirror what
``OpenAISchema.from_examples`` produces for our two ExampleData entries, with
``information_density`` upgraded from a free-form string to a constrained
enum. Other fields keep the auto-derived ``anyOf`` null-or-type form so the
strict-mode required-key rule is satisfied while letting the model omit a
field by emitting null.
"""
from __future__ import annotations

from typing import Any

from langextract.providers.schemas.openai import OpenAISchema


_INFORMATION_DENSITY_ENUM = ["high", "medium", "low"]

_REASON_ENUM = [
    "decision",       # contains decisions, choices, or recommendations
    "contrast",       # contains comparisons or alternatives
    "definition",     # contains definitions, specifications, or formal descriptions
    "dependency",     # contains causal chains, dependencies, or prerequisites
    "tradeoff",       # contains cost/benefit analysis or explicit tradeoffs
    "boilerplate",    # structural/navigational content (TOC, headers, acknowledgements)
    "enumeration",    # flat lists without reasoning (file paths, field names, bullet points)
]


def _nullable(inner: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [inner, {"type": "null"}]}


def _section_attribute_schema() -> dict[str, Any]:
    properties = {
        "topic": _nullable({"type": "string"}),
        "summary": _nullable({"type": "string"}),
        "contains_entities": _nullable({"type": "array", "items": {"type": "string"}}),
        "contains_relations": _nullable({"type": "boolean"}),
        # The one strict-mode upgrade: enum-locked enumeration.
        "information_density": _nullable(
            {"type": "string", "enum": _INFORMATION_DENSITY_ENUM}
        ),
        "graph_worthy": _nullable({"type": "boolean"}),
        "reason": _nullable({"type": "string", "enum": _REASON_ENUM}),
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _section_variant_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "section_attributes": _nullable(_section_attribute_schema()),
        },
        "required": ["section", "section_attributes"],
        "additionalProperties": False,
    }


def build_section_openai_schema() -> OpenAISchema:
    """Build the strict json_schema sent in OpenAI ``response_format``.

    Mirrors LangExtract's ``OpenAISchema.from_examples`` output shape for our
    two ExampleData entries, with ``information_density`` constrained to a
    closed enum.
    """
    schema_dict: dict[str, Any] = {
        "type": "object",
        "properties": {
            "extractions": {
                "type": "array",
                "items": {"anyOf": [_section_variant_schema()]},
            }
        },
        "required": ["extractions"],
        "additionalProperties": False,
    }
    return OpenAISchema(
        schema_dict=schema_dict,
        schema_name="langextract_section_extractions",
        strict=True,
    )
