from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from graphiti_core.llm_client.config import DEFAULT_MAX_TOKENS, LLMConfig
from graphiti_core.llm_client.openai_base_client import (
    DEFAULT_REASONING,
    DEFAULT_VERBOSITY,
    BaseOpenAIClient,
)

ENTITY_TYPE_IDS = {
    "Entity": 0,
    "Person": 1,
    "Project": 2,
    "Concept": 3,
    "Organization": 4,
    "Source": 5,
}

logger = logging.getLogger(__name__)
STRUCTURED_COLLECTION_KEYS = {"extracted_entities", "edges", "summaries", "entity_resolutions"}


class DeepSeekCompatibleClient(BaseOpenAIClient):
    """
    OpenAI-compatible client for providers that implement chat completions
    but do not support the OpenAI Responses API.
    """

    def __init__(
        self,
        config: LLMConfig | None = None,
        cache: bool = False,
        client: Any = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        reasoning: str = DEFAULT_REASONING,
        verbosity: str = DEFAULT_VERBOSITY,
    ) -> None:
        super().__init__(config, cache, max_tokens, reasoning, verbosity)
        if config is None:
            config = LLMConfig()
        self.client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=1,
            timeout=60.0,
        )

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        normalized_messages = list(messages)
        if normalized_messages:
            first = dict(normalized_messages[0])
            content = first.get("content", "")
            if isinstance(content, str) and "json" not in content.lower():
                first["content"] = f"{content}\n\nReturn valid JSON only."
            normalized_messages[0] = first

        response = await self.client.chat.completions.create(
            model=model,
            messages=normalized_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        content = _normalize_json_content(content, response_model)
        usage = SimpleNamespace(
            input_tokens=getattr(response.usage, "prompt_tokens", 0) if response.usage else 0,
            output_tokens=getattr(response.usage, "completion_tokens", 0) if response.usage else 0,
        )
        return SimpleNamespace(output_text=content, usage=usage, refusal=None)

    async def _create_completion(
        self,
        model: str,
        messages: list[ChatCompletionMessageParam],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel] | None = None,
        reasoning: str | None = None,
        verbosity: str | None = None,
    ):
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )


def _normalize_json_content(content: str, response_model: type[BaseModel]) -> str:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content

    fields = set(response_model.model_fields.keys())
    single_field = next(iter(fields)) if len(fields) == 1 else None
    original_payload = payload

    if isinstance(payload, list):
        if single_field is not None:
            payload = {single_field: payload}
        elif "extracted_entities" in fields:
            payload = {"extracted_entities": payload}
        elif "edges" in fields:
            payload = {"edges": payload}
        elif "summaries" in fields:
            payload = {"summaries": payload}

    if "extracted_entities" in fields and "extracted_entities" not in payload:
        if "entities" in payload:
            payload["extracted_entities"] = payload.pop("entities")
        elif isinstance(payload, dict):
            candidate_entities = [
                value
                for value in payload.values()
                if isinstance(value, list)
                and all(isinstance(item, dict) for item in value)
            ]
            if len(candidate_entities) == 1:
                payload = {"extracted_entities": candidate_entities[0]}

    if "summaries" in fields and "summaries" not in payload:
        if "entity_summaries" in payload:
            payload["summaries"] = payload.pop("entity_summaries")
        elif isinstance(payload, dict):
            summary_items = [
                {"name": key, "summary": value}
                for key, value in payload.items()
                if isinstance(value, str)
            ]
            if summary_items:
                payload = {"summaries": summary_items}
    if "edges" in fields and "edges" not in payload:
        if "facts" in payload:
            payload["edges"] = payload.pop("facts")
        elif isinstance(payload, dict):
            candidate_edges = [
                value
                for value in payload.values()
                if isinstance(value, list)
                and all(isinstance(item, dict) for item in value)
            ]
            if len(candidate_edges) == 1:
                payload = {"edges": candidate_edges[0]}

    if "extracted_entities" in fields and isinstance(payload.get("extracted_entities"), list):
        normalized_entities = []
        for entity in payload["extracted_entities"]:
            if not isinstance(entity, dict):
                normalized_entities.append(entity)
                continue
            item = dict(entity)
            if "entity" in item and "name" not in item:
                item["name"] = item.pop("entity")
            if "entity_name" in item and "name" not in item:
                item["name"] = item.pop("entity_name")
            entity_type = str(item.pop("type", item.pop("entity_type", "Entity"))).strip()
            item["entity_type_id"] = ENTITY_TYPE_IDS.get(entity_type, ENTITY_TYPE_IDS["Entity"])
            item.setdefault("episode_indices", [0])
            normalized_entities.append(item)
        payload["extracted_entities"] = normalized_entities

    if "edges" in fields and isinstance(payload.get("edges"), list):
        normalized_edges = []
        for edge in payload["edges"]:
            if not isinstance(edge, dict):
                normalized_edges.append(edge)
                continue
            item = dict(edge)
            if "type" in item and "relation_type" not in item:
                item["relation_type"] = item.pop("type")
            if "source_entity" in item and "source_entity_name" not in item:
                item["source_entity_name"] = item.pop("source_entity")
            if "target_entity" in item and "target_entity_name" not in item:
                item["target_entity_name"] = item.pop("target_entity")
            if "description" in item and "fact" not in item:
                item["fact"] = item.pop("description")
            if "summary" in item and "fact" not in item:
                item["fact"] = item.pop("summary")
            if "relationship" in item and "fact" not in item:
                item["fact"] = item.pop("relationship")
            if "source" in item and "source_entity_name" not in item:
                item["source_entity_name"] = item.pop("source")
            if "target" in item and "target_entity_name" not in item:
                item["target_entity_name"] = item.pop("target")
            if "fact" not in item:
                source_name = item.get("source_entity_name", "Unknown")
                target_name = item.get("target_entity_name", "Unknown")
                relation_name = item.get("relation_type", "RELATED_TO")
                item["fact"] = f"{source_name} {relation_name} {target_name}"
            item.setdefault("episode_indices", [0])
            normalized_edges.append(item)
        payload["edges"] = normalized_edges

    if "summaries" in fields and isinstance(payload.get("summaries"), list):
        normalized_summaries = []
        for item in payload["summaries"]:
            if isinstance(item, dict):
                summary_item = dict(item)
                if "entity" in summary_item and "name" not in summary_item:
                    summary_item["name"] = summary_item.pop("entity")
                if "entity_name" in summary_item and "name" not in summary_item:
                    summary_item["name"] = summary_item.pop("entity_name")
                if "description" in summary_item and "summary" not in summary_item:
                    summary_item["summary"] = summary_item.pop("description")
                normalized_summaries.append(summary_item)
        payload["summaries"] = normalized_summaries

    if isinstance(payload, dict):
        payload = {key: _sanitize_payload_value(value, preserve_structure=key in STRUCTURED_COLLECTION_KEYS) for key, value in payload.items()}

    if logger.isEnabledFor(logging.DEBUG) and payload != original_payload:
        logger.debug(
            "Normalized structured response for %s from %s to %s",
            response_model.__name__,
            json.dumps(original_payload, ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
        )

    return json.dumps(payload, ensure_ascii=False)


def _sanitize_payload_value(value: Any, preserve_structure: bool = False) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        if preserve_structure:
            sanitized_items = []
            for item in value:
                if isinstance(item, dict):
                    sanitized_items.append(
                        {key: _sanitize_payload_value(child, preserve_structure=False) for key, child in item.items()}
                    )
                else:
                    sanitized_items.append(_sanitize_payload_value(item, preserve_structure=False))
            return sanitized_items
        return [_sanitize_scalar_list_item(item) for item in value]

    if isinstance(value, dict):
        if preserve_structure:
            return {key: _sanitize_payload_value(child, preserve_structure=False) for key, child in value.items()}
        return json.dumps(value, ensure_ascii=False)

    return str(value)


def _sanitize_scalar_list_item(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
