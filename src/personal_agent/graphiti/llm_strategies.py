from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import openai
from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig, ModelSize
from graphiti_core.llm_client.openai_generic_client import (
    DEFAULT_MODEL,
    OpenAIGenericClient,
)
from graphiti_core.prompts.models import Message

from ..core.config import Settings
from .ontology import ENTITY_TYPES

logger = logging.getLogger(__name__)

ENTITY_TYPE_IDS: dict[str, int] = {name: idx for idx, name in enumerate(ENTITY_TYPES)}
ENTITY_TYPE_NAME_LOOKUP: dict[str, int] = {
    name.lower(): idx for name, idx in ENTITY_TYPE_IDS.items()
}


def _normalize_extraction(payload: dict[str, Any]) -> dict[str, Any]:
    """Fix entity and edge fields from models that deviate from the expected schema.

    Entities:
    - ``entities`` → ``extracted_entities`` key mapping
    - ``entity_name`` / ``entity_type_name`` / ``entity_type`` field names
    - String → int ``entity_type_id`` conversion with case-insensitive lookup
    - String entity items (list of bare names)

    Edges:
    - ``facts`` → ``edges`` key mapping
    - ``source_entity`` → ``source_entity_name``, ``target_entity`` → ``target_entity_name``
    - ``relation`` → ``relation_type``
    """
    _normalize_entities(payload)
    _normalize_edges(payload)
    return payload


def _normalize_entities(payload: dict[str, Any]) -> None:
    raw_entities = payload.get("extracted_entities") or payload.get("entities")
    if not isinstance(raw_entities, list):
        return

    normalized: list[dict[str, Any]] = []
    for entity in raw_entities:
        if isinstance(entity, str):
            normalized.append(
                {
                    "name": entity.strip(),
                    "entity_type_id": ENTITY_TYPE_IDS.get("Entity", 0),
                    "episode_indices": [0],
                }
            )
            continue
        if not isinstance(entity, dict):
            continue

        item: dict[str, Any] = {}

        name = entity.get("name") or entity.get("entity_name") or entity.get("entity")
        if name:
            item["name"] = str(name).strip()

        type_id = entity.get("entity_type_id")
        if type_id is not None:
            try:
                item["entity_type_id"] = int(type_id)
            except (ValueError, TypeError):
                type_str = str(type_id).strip()
                mapped = ENTITY_TYPE_IDS.get(type_str) or ENTITY_TYPE_NAME_LOOKUP.get(
                    type_str.lower()
                )
                item["entity_type_id"] = (
                    mapped if mapped is not None else ENTITY_TYPE_IDS.get("Entity", 0)
                )
        else:
            type_val = (
                entity.get("entity_type")
                or entity.get("type")
                or entity.get("entity_type_name")
            )
            if type_val is not None:
                type_str = str(type_val).strip()
                mapped = ENTITY_TYPE_IDS.get(type_str) or ENTITY_TYPE_NAME_LOOKUP.get(
                    type_str.lower()
                )
                item["entity_type_id"] = (
                    mapped if mapped is not None else ENTITY_TYPE_IDS.get("Entity", 0)
                )
            else:
                item["entity_type_id"] = ENTITY_TYPE_IDS.get("Entity", 0)

        item["episode_indices"] = entity.get("episode_indices", [0])

        if item.get("name"):
            normalized.append(item)

    payload["extracted_entities"] = normalized
    payload.pop("entities", None)


def _normalize_edges(payload: dict[str, Any]) -> None:
    raw_edges = payload.get("edges") or payload.get("facts")
    if not isinstance(raw_edges, list):
        return

    normalized: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue

        item: dict[str, Any] = {}

        src = (
            edge.get("source_entity_name")
            or edge.get("source_entity")
            or edge.get("source")
        )
        if src:
            item["source_entity_name"] = str(src).strip()

        tgt = (
            edge.get("target_entity_name")
            or edge.get("target_entity")
            or edge.get("target")
        )
        if tgt:
            item["target_entity_name"] = str(tgt).strip()

        rel = (
            edge.get("relation_type")
            or edge.get("relation")
            or edge.get("relationship")
        )
        if rel:
            item["relation_type"] = str(rel).strip()

        fact = edge.get("fact") or edge.get("description") or edge.get("text")
        if fact:
            item["fact"] = str(fact).strip()

        for optional_field in ("valid_at", "invalid_at", "episode_indices"):
            if optional_field in edge:
                item[optional_field] = edge[optional_field]

        if (
            item.get("source_entity_name")
            and item.get("target_entity_name")
            and item.get("relation_type")
        ):
            item.setdefault(
                "fact",
                f"{item['source_entity_name']} {item['relation_type']} {item['target_entity_name']}",
            )
            item.setdefault("episode_indices", [0])
            normalized.append(item)

    payload["edges"] = normalized
    payload.pop("facts", None)


def _flatten_nested_maps(obj: Any) -> Any:
    """Recursively convert nested dicts to JSON strings for Neo4j compatibility."""
    if isinstance(obj, dict):
        return {key: _flatten_value_for_neo4j(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_flatten_nested_maps(item) for item in obj]
    return obj


def _flatten_value_for_neo4j(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if any(isinstance(v, dict) for v in value):
            return [
                json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v
                for v in value
            ]
        return value
    return value


def _ensure_json_keyword(messages: list[dict[str, str]]) -> None:
    """Append a JSON hint to the last message if no message mentions 'json'."""
    for msg in messages:
        if "json" in msg["content"].lower():
            return
    if messages:
        messages[-1]["content"] += "\nRespond with JSON."
    else:
        messages.append({"role": "system", "content": "Respond with JSON."})


class GraphitiOpenAIClient(OpenAIGenericClient):
    """OpenAI-compatible client with rate limiting and field normalization.

    Uses structured output schemas for Graphiti response models and disables
    Kimi thinking so extraction output remains machine-readable.
    """

    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        model_size: ModelSize = ModelSize.medium,
    ) -> dict[str, Any]:
        openai_messages: list[dict[str, str]] = []
        for message in messages:
            message.content = self._clean_input(message.content)
            if message.role in {"user", "system"}:
                openai_messages.append(
                    {"role": message.role, "content": message.content}
                )

        # Keep untyped Graphiti calls constrained to JSON as well.
        _ensure_json_keyword(openai_messages)
        response_format: dict[str, Any] = {"type": "json_object"}
        if response_model is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": getattr(response_model, "__name__", "structured_response"),
                    "schema": response_model.model_json_schema(),
                },
            }

        await self._respect_min_interval()

        try:
            response = await self.client.chat.completions.create(
                model=self.model or DEFAULT_MODEL,
                messages=openai_messages,
                temperature=0.6,
                max_tokens=self.max_tokens,
                response_format=response_format,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except openai.RateLimitError as exc:
            from graphiti_core.llm_client.errors import RateLimitError

            raise RateLimitError(
                "Rate limit exceeded. Please try again later."
            ) from exc

        raw = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned non-JSON content (len=%d): %s...", len(raw), raw[:200]
            )
            raise
        # Normalize entity/edge field names, then flatten nested maps for Neo4j
        normalized = _normalize_extraction(parsed)
        return _flatten_nested_maps(normalized)

    async def _respect_min_interval(self) -> None:
        last_call: float = getattr(GraphitiOpenAIClient, "_last_api_call_ts", 0.0)
        elapsed = time.monotonic() - last_call
        if elapsed < 2.0:
            await asyncio.sleep(2.0 - elapsed)
        GraphitiOpenAIClient._last_api_call_ts = time.monotonic()


def build_graphiti_llm_client(settings: Settings) -> GraphitiOpenAIClient:
    return GraphitiOpenAIClient(
        config=LLMConfig(
            api_key=settings.graphiti_llm_api_key or settings.openai_api_key,
            base_url=settings.graphiti_llm_base_url or settings.openai_base_url,
            model=settings.graphiti_llm_model or settings.openai_model,
            small_model=settings.graphiti_llm_small_model
            or settings.openai_small_model,
        )
    )
