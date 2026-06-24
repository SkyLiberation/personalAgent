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

from personal_agent.kernel.config import Settings
from personal_agent.kernel.llm_schemas import strictify_schema
from personal_agent.kernel.llm_trace import log_llm_parse
from personal_agent.kernel.logging_utils import log_event
from personal_agent.memory.graphiti.ontology import ENTITY_TYPES

logger = logging.getLogger(__name__)


def _is_reasoning_model(model: str | None) -> bool:
    name = (model or "").lower()
    return name.startswith(("gpt-5", "o1", "o3"))


def _supports_thinking_control(model: str | None) -> bool:
    name = (model or "").lower()
    return name.startswith(("kimi", "moonshot", "qwen"))

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
    - summaries[].entity_name → summaries[].name
    - entity_resolutions[].entity_name → entity_resolutions[].name
    """
    _normalize_entities(payload)
    _normalize_edges(payload)
    _normalize_summaries(payload)
    _normalize_resolutions(payload)
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


def _normalize_summaries(payload: dict[str, Any]) -> None:
    """Map entity_name → name in summaries list for SummarizedEntities.

    Also handles LLM format variants:
    - {"entity_name": "summary_text", ...} → dict of name→summary pairs
    - {"summary": [...]} or {"entity_summaries": [...]} → wrong key name
    """
    raw = payload.get("summaries")

    # Try alternate key names
    if raw is None:
        for alt_key in ("entity_summaries", "summary"):
            if alt_key in payload:
                raw = payload.pop(alt_key)
                payload["summaries"] = raw
                break

    # Convert dict-of-name→summary to list format
    if isinstance(raw, dict):
        items = []
        for name, summary in raw.items():
            if isinstance(summary, str):
                items.append({"name": str(name).strip(), "summary": summary})
            elif isinstance(summary, dict):
                summary["name"] = summary.get("name") or str(name).strip()
                items.append(summary)
        payload["summaries"] = items
        raw = items

    if not isinstance(raw, list):
        return
    for item in raw:
        if isinstance(item, dict) and "name" not in item:
            name = item.pop("entity_name", None) or item.pop("entity", None)
            if name:
                item["name"] = str(name).strip()


def _normalize_resolutions(payload: dict[str, Any]) -> None:
    """Map entity_name → name in entity_resolutions for NodeResolutions.

    Also handles common LLM format variants:
    - {"0": "{...}", "1": "{...}"} → numeric-keyed dict of JSON strings
    - {"resolution_0": "{...}"} → prefixed keys
    - {"resolution": [...]} or {"resolutions": [...]} → wrong key name
    - {"entity_resolutions": {"0": ...}} → nested dict instead of list
    """
    raw = payload.get("entity_resolutions")

    # Try alternate key names first
    if raw is None:
        for alt_key in ("resolutions", "resolution", "entity_resolution"):
            if alt_key in payload:
                raw = payload.pop(alt_key)
                payload["entity_resolutions"] = raw
                break

    # Convert dict-of-items to list
    if isinstance(raw, dict):
        items = []
        for key, val in sorted(raw.items(), key=lambda kv: kv[0]):
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(val, dict):
                items.append(val)
            elif isinstance(val, list):
                items.extend(v for v in val if isinstance(v, dict))
        payload["entity_resolutions"] = items
        raw = items

    if not isinstance(raw, list):
        return
    for item in raw:
        if isinstance(item, dict) and "name" not in item:
            name = item.pop("entity_name", None) or item.pop("entity", None)
            if name:
                item["name"] = str(name).strip()


def _flatten_nested_maps(obj: Any) -> Any:
    """Recursively convert nested dicts to JSON strings for Neo4j compatibility.

    Only flattens dict-valued scalars (single nested objects). Lists of dicts
    are left intact because they are structural data consumed by graphiti_core's
    Pydantic models (ExtractedEntities, NodeResolutions, CombinedExtraction,
    etc.) before reaching Neo4j.
    """
    if isinstance(obj, dict):
        return {key: _flatten_value_for_neo4j(val) for key, val in obj.items()}
    if isinstance(obj, list):
        return [_flatten_nested_maps(item) for item in obj]
    return obj


def _flatten_value_for_neo4j(value: Any) -> Any:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    # Lists are left as-is: lists of dicts are Pydantic structural data,
    # lists of primitives are already Neo4j-compatible.
    return value


def _ensure_model_fields(parsed: dict[str, Any], response_model: type) -> dict[str, Any]:
    """Wrap a flat LLM response into the expected model structure when needed.

    When qwen3-coder-flash ignores json_schema constraints, it may return
    e.g. {"entity_name": "summary"} instead of {"summaries": [...]}.
    This detects missing required list fields and wraps the dict as items.
    """
    if not hasattr(response_model, "model_fields"):
        return parsed
    model_fields = response_model.model_fields
    for field_name, field_info in model_fields.items():
        if field_name in parsed:
            continue
        # Check if this is a required list field missing from parsed
        annotation = field_info.annotation
        origin = getattr(annotation, "__origin__", None)
        if origin is list and field_name not in parsed:
            # The entire parsed dict might BE the items in disguise
            # Convert dict-of-items to list wrapped under the field name
            if all(isinstance(v, (str, dict)) for v in parsed.values()):
                items = []
                for key, val in parsed.items():
                    if isinstance(val, str):
                        items.append({"name": str(key).strip(), "summary": val})
                    elif isinstance(val, dict):
                        val.setdefault("name", str(key).strip())
                        items.append(val)
                return {field_name: items}
    return parsed


def _ensure_json_keyword(messages: list[dict[str, str]]) -> None:
    """Append a JSON hint to the last message if no message mentions 'json'."""
    for msg in messages:
        if "json" in msg["content"].lower():
            return
    if messages:
        messages[-1]["content"] += "\nRespond with JSON."
    else:
        messages.append({"role": "system", "content": "Respond with JSON."})


def _traceable_graphiti_completion(fn):
    try:
        from langsmith import traceable
    except Exception:
        return fn
    return traceable(name="graphiti.llm_completion", run_type="llm")(fn)


class GraphitiOpenAIClient(OpenAIGenericClient):
    """OpenAI-compatible client with rate limiting and field normalization.

    Uses structured output schemas for Graphiti response models and disables
    Kimi thinking so extraction output remains machine-readable.
    """

    def __init__(self, *args, upload_inputs_outputs: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.upload_inputs_outputs = upload_inputs_outputs

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
                    "schema": strictify_schema(response_model.model_json_schema()),
                    "strict": True,
                },
            }

        await self._respect_min_interval()

        model = self.model or DEFAULT_MODEL
        response_model_name = (
            getattr(response_model, "__name__", "structured_response")
            if response_model is not None
            else "json_object"
        )
        start = time.monotonic()
        try:
            response = await self._create_completion(
                model=model,
                messages=openai_messages,
                temperature=0.6,
                max_tokens=self.max_tokens,
                response_format=response_format,
                extra_body=(
                    {"thinking": {"type": "disabled"}}
                    if _supports_thinking_control(model)
                    else {}
                ),
                response_model_name=response_model_name,
            )
        except openai.RateLimitError as exc:
            from graphiti_core.llm_client.errors import RateLimitError

            raise RateLimitError(
                "Rate limit exceeded. Please try again later."
            ) from exc

        raw = response.choices[0].message.content or "{}"
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        from personal_agent.kernel.llm_telemetry import record_llm_usage

        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        output_tokens = getattr(usage, "completion_tokens", None) if usage else None
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        record_llm_usage(
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )
        log_event(
            logger,
            logging.INFO,
            "llm.call",
            prompt_name="graphiti_extraction",
            prompt_version="v1",
            model=model,
            latency_ms=latency_ms,
            response_chars=len(raw),
            response_model=response_model_name,
            component="graphiti",
        )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            log_llm_parse(
                prompt_name="graphiti_extraction",
                model=model,
                parse_schema=response_model_name,
                parse_ok=False,
                parse_error="non-json response",
                latency_ms=latency_ms,
            )
            logger.warning(
                "LLM returned non-JSON content (len=%d): %s...", len(raw), raw[:200]
            )
            raise
        log_llm_parse(
            prompt_name="graphiti_extraction",
            model=model,
            parse_schema=response_model_name,
            parse_ok=True,
            latency_ms=latency_ms,
        )
        # When a response_model is specified, ensure the parsed dict contains
        # the model's required fields. If not, attempt to wrap the entire dict
        # as the value of the first required list field (handles cases where
        # qwen3-coder-flash returns {entity_name: summary} instead of
        # {"summaries": [{name, summary}]} or {"entity_resolutions": [...]}).
        if response_model is not None and isinstance(parsed, dict):
            parsed = _ensure_model_fields(parsed, response_model)
        # Normalize entity/edge field names for graphiti_core Pydantic models.
        normalized = _normalize_extraction(parsed)
        return _flatten_nested_maps(normalized)

    async def _create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
        extra_body: dict[str, Any],
        response_model_name: str,
    ):
        runner = (
            self._traced_create_completion
            if self.upload_inputs_outputs
            else self._create_completion_impl
        )
        return await runner(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
            response_model_name=response_model_name,
        )

    @_traceable_graphiti_completion
    async def _traced_create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
        extra_body: dict[str, Any],
        response_model_name: str,
    ):
        return await self._create_completion_impl(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
            response_model_name=response_model_name,
        )

    async def _create_completion_impl(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: dict[str, Any],
        extra_body: dict[str, Any],
        response_model_name: str,
    ):
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "response_format": response_format,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        if _is_reasoning_model(model):
            # GPT-5-compatible gateways fix sampling parameters at their
            # defaults and use max_completion_tokens.
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["temperature"] = temperature
            kwargs["max_tokens"] = max_tokens
        return await self.client.chat.completions.create(
            **kwargs,
        )

    async def _respect_min_interval(self) -> None:
        last_call: float = getattr(GraphitiOpenAIClient, "_last_api_call_ts", 0.0)
        elapsed = time.monotonic() - last_call
        if elapsed < 0.1:
            await asyncio.sleep(0.1 - elapsed)
        GraphitiOpenAIClient._last_api_call_ts = time.monotonic()


def build_graphiti_llm_client(settings: Settings) -> GraphitiOpenAIClient:
    return GraphitiOpenAIClient(
        config=LLMConfig(
            api_key=settings.graphiti.llm_api_key or settings.openai.api_key,
            base_url=settings.graphiti.llm_base_url or settings.openai.base_url,
            model=settings.graphiti.llm_model or settings.openai.model,
            small_model=settings.graphiti.llm_small_model
            or settings.openai.small_model,
        ),
        upload_inputs_outputs=settings.langsmith.upload_inputs,
    )
