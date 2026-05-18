from __future__ import annotations

import json
import logging
import re
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

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)

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
STRUCTURED_KEY_ALIASES = {
    "extracted_entities": ("entities", "items", "results"),
    "edges": ("facts", "relationships", "relations"),
    "summaries": ("entity_summaries", "entities", "items", "results"),
    "entity_resolutions": ("resolutions", "duplicates", "items", "results"),
}


_ENTITY_ITEM_FIELDS = {"name", "entity_type_id", "entity_type", "type", "episode_indices", "entity_name"}
_EDGE_ITEM_FIELDS = {"source_entity_name", "target_entity_name", "relation_type", "fact", "valid_at", "invalid_at", "episode_indices", "source", "target", "type", "description", "relationship", "summary", "source_entity", "target_entity"}
_SUMMARY_ITEM_FIELDS = {"name", "summary", "entity_name", "description"}
_RESOLUTION_ITEM_FIELDS = {"id", "name", "duplicate_candidate_id", "candidate_id"}


def _expand_json_strings_in_items(items: list[dict], item_field_names: set[str]) -> list[dict]:
    """Expand JSON strings nested inside structured collection items.

    When the LLM returns ``{"entities": ['{"name": "X", ...}'], ...}`` instead of
    ``{"name": "X", ...}``, this helper detects list-of-string values that look like
    serialised JSON objects and merges their keys into the parent item.
    """
    expanded: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            expanded.append(item)
            continue
        merged = dict(item)
        any_field_present = any(field in merged for field in item_field_names)
        if not any_field_present and merged:
            non_field_keys = {k: v for k, v in merged.items() if k not in item_field_names}
            if len(non_field_keys) == len(merged):
                for nfk, nfv in non_field_keys.items():
                    if isinstance(nfv, str):
                        try:
                            parsed = json.loads(nfv)
                            if isinstance(parsed, dict):
                                merged = {"name": nfk}
                                for pk, pv in parsed.items():
                                    merged.setdefault(pk, pv)
                                break
                        except json.JSONDecodeError:
                            pass
                if not any(field in merged for field in item_field_names):
                    merged = {"name": list(non_field_keys.keys())[0]}
                    raw_value = list(non_field_keys.values())[0]
                    if isinstance(raw_value, str):
                        merged["summary"] = raw_value
        for key, value in list(merged.items()):
            if not isinstance(value, list):
                continue
            parsed_dicts: list[dict] = []
            all_strings_parseable = True
            for element in value:
                if isinstance(element, dict):
                    parsed_dicts.append(element)
                elif isinstance(element, str):
                    try:
                        parsed = json.loads(element)
                        if isinstance(parsed, dict):
                            parsed_dicts.append(parsed)
                        else:
                            all_strings_parseable = False
                            break
                    except json.JSONDecodeError:
                        all_strings_parseable = False
                        break
                else:
                    all_strings_parseable = False
                    break
            if not parsed_dicts or not all_strings_parseable:
                continue
            merged.pop(key, None)
            for pd in parsed_dicts:
                for k, v in pd.items():
                    if k not in merged and k in item_field_names:
                        merged[k] = v
                    elif k not in merged:
                        merged[k] = v
        expanded.append(merged)
    return expanded


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
            timeout=300.0,
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


def _extract_json_text(content: str) -> str:
    """Strip think blocks and extract JSON from raw LLM response text.

    Handles several MiniMax M2.7 response patterns:
    - ``<think>...</think>{"key": ...}``
    - `````json\\n{...}\\n``````
    - ``Explanation text...\\n\\n{"key": ...}``
    - ``{"key": ...}`` (pure JSON, pass-through)
    """
    content = _THINK_BLOCK_RE.sub("", content).strip()

    if not content:
        return "{}"

    # Try direct JSON parse first (most common case after think-block strip)
    try:
        json.loads(content)
        return content
    except json.JSONDecodeError:
        pass

    # Try markdown code-block extraction
    match = _JSON_BLOCK_RE.search(content)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    # Try bracket-boundary extraction: find the outermost { } or [ ] range
    # that parses as valid JSON — handles "text ... {json} ... more text"
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = content.find(open_ch)
        end = content.rfind(close_ch)
        if start >= 0 and end > start:
            candidate = content[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                # Try with closing bracket only (in case the JSON is at the end)
                for close_pos in range(len(content) - 1, start, -1):
                    if content[close_pos] == close_ch:
                        candidate = content[start : close_pos + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except json.JSONDecodeError:
                            continue
                continue

    return content or "{}"


def normalize_structured_payload(
    payload: dict[str, Any], response_model: type[BaseModel]
) -> dict[str, Any]:
    """Normalize a structured LLM response dict for Graphiti compatibility.

    Handles reasoning-model quirks: missing ``name`` fields, ``entity_id`` in
    place of ``entity_type_id``, aliased collection keys, nested JSON strings,
    and structural wrapping edge cases.
    """
    fields = set(response_model.model_fields.keys())
    single_field = next(iter(fields)) if len(fields) == 1 else None
    original_payload = payload

    # Resolve aliases FIRST, before any structural wrapping.
    if isinstance(payload, dict):
        for target_key, aliases in STRUCTURED_KEY_ALIASES.items():
            if target_key not in fields or target_key in payload:
                continue
            for alias in aliases:
                if alias not in payload:
                    continue
                alias_value = payload.get(alias)
                if isinstance(alias_value, list):
                    payload[target_key] = alias_value
                    if alias != target_key:
                        payload.pop(alias, None)
                    break

    if isinstance(payload, dict):
        if "extracted_entities" in fields and "extracted_entities" not in payload:
            if "entities" in payload:
                payload["extracted_entities"] = payload.pop("entities")
            else:
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
            elif "entities" in payload and isinstance(payload["entities"], list):
                payload["summaries"] = payload.pop("entities")
            else:
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
            else:
                candidate_edges = [
                    value
                    for value in payload.values()
                    if isinstance(value, list)
                    and all(isinstance(item, dict) for item in value)
                ]
                if len(candidate_edges) == 1:
                    payload = {"edges": candidate_edges[0]}

        if "entity_resolutions" in fields and "entity_resolutions" not in payload:
            if "resolutions" in payload:
                payload["entity_resolutions"] = payload.pop("resolutions")
            else:
                candidate_resolutions = [
                    value
                    for value in payload.values()
                    if isinstance(value, list)
                    and all(isinstance(item, dict) for item in value)
                ]
                if len(candidate_resolutions) == 1:
                    payload = {"entity_resolutions": candidate_resolutions[0]}

    # Structural wrapping — only when the target key is still missing after alias resolution.
    if isinstance(payload, list):
        if single_field is not None:
            payload = {single_field: payload}
        elif "extracted_entities" in fields:
            payload = {"extracted_entities": payload}
        elif "edges" in fields:
            payload = {"edges": payload}
        elif "summaries" in fields:
            payload = {"summaries": payload}
        elif "entity_resolutions" in fields:
            payload = {"entity_resolutions": payload}
        elif len(payload) == 1 and isinstance(payload[0], dict):
            # Unwrap single-element list of dicts (MiniMax quirk)
            payload = payload[0]
        elif fields:
            # Wrap list under the first model field name as a fallback
            first_field = next(iter(fields))
            payload = {first_field: payload}

    if isinstance(payload, dict) and single_field is not None and single_field not in payload:
        payload = {single_field: [payload]}

    # Handle dict-form extracted_entities (LLM returned entities keyed by name)
    if "extracted_entities" in fields and isinstance(payload.get("extracted_entities"), dict):
        dict_entities = payload["extracted_entities"]
        list_entities: list[dict] = []
        for name, value in dict_entities.items():
            if not isinstance(name, str):
                continue
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        parsed.setdefault("name", name)
                        list_entities.append(parsed)
                        continue
                except json.JSONDecodeError:
                    pass
            if isinstance(value, dict):
                value.setdefault("name", name)
                list_entities.append(value)
            else:
                list_entities.append({"name": name, "summary": str(value)})
        payload["extracted_entities"] = list_entities

    if "extracted_entities" in fields and isinstance(payload.get("extracted_entities"), list):
        payload["extracted_entities"] = _expand_json_strings_in_items(
            payload["extracted_entities"], _ENTITY_ITEM_FIELDS
        )
        normalized_entities = []
        for i, entity in enumerate(payload["extracted_entities"]):
            if isinstance(entity, str):
                normalized_entities.append({
                    "name": entity.strip(),
                    "entity_type_id": ENTITY_TYPE_IDS["Entity"],
                    "episode_indices": [0],
                })
                continue
            if not isinstance(entity, dict):
                logger.warning(
                    "Skipping non-dict/non-str extracted_entities[%d] of type %s: %s",
                    i, type(entity).__name__, str(entity)[:120],
                )
                continue
            item = dict(entity)
            if "entity" in item and "name" not in item:
                item["name"] = item.pop("entity")
            if "entity_name" in item and "name" not in item:
                item["name"] = item.pop("entity_name")
            if "entity_text" in item and "name" not in item:
                item["name"] = item.pop("entity_text")
            entity_type = str(item.pop("type", item.pop("entity_type", "Entity"))).strip()
            # Case-insensitive lookup (Kimi K2.5 returns lowercase like "person")
            type_id = ENTITY_TYPE_IDS.get(entity_type)
            if type_id is None:
                for known_name, known_id in ENTITY_TYPE_IDS.items():
                    if known_name.lower() == entity_type.lower():
                        type_id = known_id
                        break
            item["entity_type_id"] = type_id if type_id is not None else ENTITY_TYPE_IDS["Entity"]
            # Some reasoning models (MiniMax M2.7) may use "entity_id" as a local
            # numeric index without providing a name. Derive a label from summary or
            # entity_type + id so downstream Graphiti validation passes.
            if "name" not in item:
                summary = item.get("summary", "")
                if isinstance(summary, str) and summary.strip():
                    first_sentence = summary.split(".")[0].strip()
                    item["name"] = first_sentence[:80] if first_sentence else summary[:80]
                else:
                    entity_id = item.get("entity_id", item.get("id", "unknown"))
                    item["name"] = f"{entity_type}_{entity_id}"
            item.setdefault("episode_indices", [0])
            normalized_entities.append(item)
        payload["extracted_entities"] = normalized_entities

    if "edges" in fields and isinstance(payload.get("edges"), list):
        payload["edges"] = _expand_json_strings_in_items(
            payload["edges"], _EDGE_ITEM_FIELDS
        )
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
        payload["summaries"] = _expand_json_strings_in_items(
            payload["summaries"], _SUMMARY_ITEM_FIELDS
        )
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
                # Ensure required fields have at least a placeholder
                if "name" not in summary_item:
                    summary_item["name"] = "Entity_unknown"
                if "summary" not in summary_item:
                    summary_item["summary"] = summary_item.get("name", "Unknown entity")
                normalized_summaries.append(summary_item)
        payload["summaries"] = normalized_summaries

    if "entity_resolutions" in fields and isinstance(payload.get("entity_resolutions"), list):
        payload["entity_resolutions"] = _expand_json_strings_in_items(
            payload["entity_resolutions"], _RESOLUTION_ITEM_FIELDS
        )
        normalized_resolutions = []
        for item in payload["entity_resolutions"]:
            if not isinstance(item, dict):
                normalized_resolutions.append(item)
                continue
            resolution_item = dict(item)
            if "candidate_id" in resolution_item and "duplicate_candidate_id" not in resolution_item:
                resolution_item["duplicate_candidate_id"] = resolution_item.pop("candidate_id")
            normalized_resolutions.append(resolution_item)
        payload["entity_resolutions"] = normalized_resolutions

    if isinstance(payload, dict):
        payload = _coerce_field_types(payload, response_model)
        payload = {key: _sanitize_payload_value(value, preserve_structure=key in STRUCTURED_COLLECTION_KEYS) for key, value in payload.items()}

    if logger.isEnabledFor(logging.DEBUG) and payload != original_payload:
        logger.debug(
            "Normalized structured response for %s from %s to %s",
            response_model.__name__,
            json.dumps(original_payload, ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
        )

    return payload


def _coerce_field_types(payload: dict[str, Any], response_model: type[BaseModel]) -> dict[str, Any]:
    """Coerce field values to match the expected types from the response model.

    Reasoning models (MiniMax M2.7) sometimes return ``""`` for list fields
    or ``"5"`` for int fields.  This helper fixes those mismatches using the
    model's field annotations so downstream Pydantic validation passes.

    Also performs fuzzy field-name correction for misspellings (e.g.
    ``contrasted_facts`` → ``contradicted_facts``).
    """
    import typing

    result = dict(payload)
    model_field_names = set(response_model.model_fields.keys())

    # Fuzzy field-name correction: remap misspelled keys to the closest model field
    for key in list(result.keys()):
        if key in model_field_names:
            continue
        # Find the model field with the smallest edit distance
        best_match = None
        best_dist = 999
        for mf in model_field_names:
            dist = _edit_distance(key, mf)
            if dist < best_dist:
                best_dist = dist
                best_match = mf
        # Remap if the edit distance is small relative to the key length
        if best_match is not None and best_dist <= max(3, len(key) // 3):
            result[best_match] = result.pop(key)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Remapped misspelled field '%s' → '%s'", key, best_match)

    for field_name, field_info in response_model.model_fields.items():
        if field_name not in result:
            continue
        value = result[field_name]
        annotation = field_info.annotation

        # Resolve Optional[...] / Union types to find the inner type
        origin = typing.get_origin(annotation)
        args = typing.get_args(annotation)

        # Check if the expected type is a list
        is_list_type = origin is list or (origin is not None and issubclass(origin, list))
        if not is_list_type and args:
            # Handle Optional[list[...]] — look for list in Union args
            for arg in args:
                arg_origin = typing.get_origin(arg)
                if arg_origin is list or (arg_origin is not None and issubclass(arg_origin, list)):
                    is_list_type = True
                    break

        if is_list_type:
            if isinstance(value, str):
                if not value.strip():
                    result[field_name] = []
                else:
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, list):
                            result[field_name] = parsed
                    except json.JSONDecodeError:
                        result[field_name] = []

        # Reverse coercion: string field received a list
        is_str_type = origin is str or (args and any(a is str for a in args)) or annotation is str
        if not is_list_type and not is_str_type:
            # Handle Optional[str] — look for str in Union args
            if args:
                for arg in args:
                    if arg is str or arg is None:
                        is_str_type = True
                        break

        if is_str_type and isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], str):
                result[field_name] = value[0]
            else:
                result[field_name] = json.dumps(value, ensure_ascii=False)

        # Coerce string numbers for int/float fields
        is_int_type = origin is int or (args and any(a is int for a in args))
        is_float_type = origin is float or (args and any(a is float for a in args))

        if is_int_type and isinstance(value, str):
            try:
                result[field_name] = int(value.strip())
            except (ValueError, TypeError):
                pass
        elif is_float_type and isinstance(value, str):
            try:
                result[field_name] = float(value.strip())
            except (ValueError, TypeError):
                pass

    return result


def _normalize_json_content(content: str, response_model: type[BaseModel]) -> str:
    """Normalize raw LLM response text into a JSON string (legacy API for DeepSeekCompatibleClient)."""
    text = _extract_json_text(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return content
    normalized = normalize_structured_payload(payload, response_model)
    return json.dumps(normalized, ensure_ascii=False)


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
        if value and all(isinstance(item, str) for item in value):
            return "; ".join(value)
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


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings (case-insensitive)."""
    a, b = a.lower(), b.lower()
    if len(a) < len(b):
        a, b = b, a
    # a is the longer string
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (0 if ca == cb else 1),  # substitution
            ))
        prev = curr
    return prev[-1]
