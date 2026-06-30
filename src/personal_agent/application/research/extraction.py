"""Research event-frame extraction and same-event matching.

Research owns this module because event identity is a domain concept, not a
generic LangExtract concern. ``ResearchService`` depends on the
``ResearchEventExtractor`` port; LangExtract is only one implementation.
"""

from __future__ import annotations

import hashlib
import logging
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Protocol

import langextract as lx
from langextract.providers.schemas.openai import OpenAISchema
from pydantic import BaseModel, Field

from personal_agent.application.extract.langextract_client import run_extract
from personal_agent.infra.structured_model import (
    OpenAIModelClient,
    StructuredModelClient,
    StructuredModelRequest,
)
from personal_agent.kernel.config import LangExtractConfig, OpenAIConfig
from personal_agent.kernel.contracts.research import ResearchSource
from personal_agent.kernel.llm_schemas import strict_json_schema_response, strip_json_fence

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "new",
    "of",
    "on",
    "the",
    "to",
    "with",
}
_ACTION_CANONICAL = {
    "announce": "release",
    "announced": "release",
    "announces": "release",
    "launch": "release",
    "launched": "release",
    "launches": "release",
    "release": "release",
    "released": "release",
    "releases": "release",
    "ship": "release",
    "shipped": "release",
    "ships": "release",
    "patch": "patch",
    "patched": "patch",
    "patches": "patch",
    "fix": "patch",
    "fixed": "patch",
    "fixes": "patch",
    "improve": "improve",
    "improved": "improve",
    "improves": "improve",
    "update": "update",
    "updated": "update",
    "updates": "update",
}
_GENERIC_ACTIONS = {
    "",
    "coverage",
    "cover",
    "covered",
    "covers",
    "mention",
    "mentioned",
    "mentions",
    "report",
    "reported",
    "reporting",
    "reports",
    "say",
    "says",
}
_EVENT_TYPE_CANONICAL = {
    "announcement": "product_release",
    "launch": "product_release",
    "launch_announcement": "product_release",
    "product_announcement": "product_release",
    "product_launch": "product_release",
    "product_release": "product_release",
    "release": "product_release",
    "release_announcement": "product_release",
    "benchmark": "benchmark_release",
    "benchmark_release": "benchmark_release",
    "evaluation_release": "benchmark_release",
    "patch": "security_update",
    "security_fix": "security_update",
    "security_patch": "security_update",
    "security_update": "security_update",
    "vulnerability_fix": "security_update",
}
_GENERIC_EVENT_TYPES = {
    "",
    "media_report",
    "news",
    "news_report",
    "report",
    "reported_event",
    "unknown",
}
_GENERIC_ACTORS = {
    "media",
    "news",
    "publisher",
    "reporter",
    "reporters",
}


@dataclass(frozen=True)
class ResearchEventFrame:
    source_url: str
    title: str
    actor: str = ""
    action: str = ""
    object: str = ""
    event_type: str = "unknown"
    occurred_at: str = ""
    entities: list[str] = field(default_factory=list)
    confidence: float = 0.0

    @property
    def actor_tokens(self) -> set[str]:
        return {
            token for token in _tokens(self.actor)
            if token not in _GENERIC_ACTORS
        }

    @property
    def action_key(self) -> str:
        tokens = _tokens(self.action)
        if not tokens:
            return ""
        return _canonical_action(next(iter(tokens)))

    @property
    def object_tokens(self) -> set[str]:
        return _tokens(self.object or self.title)

    @property
    def event_type_key(self) -> str:
        return _canonical_event_type(self.event_type)


class ResearchEventExtractor(Protocol):
    def extract(
        self,
        sources: list[ResearchSource],
        *,
        topic: str,
        instructions: str = "",
    ) -> dict[str, ResearchEventFrame]:
        """Return event frames keyed by source canonical_url."""


class HeuristicResearchEventExtractor:
    """Deterministic fallback for event frames when model extraction is absent."""

    def extract(
        self,
        sources: list[ResearchSource],
        *,
        topic: str,
        instructions: str = "",
    ) -> dict[str, ResearchEventFrame]:
        return {
            source.canonical_url: heuristic_event_frame(source)
            for source in sources
        }


class StructuredEventFrameItem(BaseModel):
    source_url: str = ""
    actor: str = ""
    action: str = ""
    object: str = ""
    event_type: str = "unknown"
    occurred_at: str = ""
    entities: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class StructuredEventFrameBatch(BaseModel):
    frames: list[StructuredEventFrameItem] = Field(default_factory=list)


class StructuredResearchEventExtractor:
    """Batch structured-LLM Research event-frame extractor."""

    def __init__(
        self,
        config: LangExtractConfig,
        *,
        model_client: StructuredModelClient | None = None,
        fallback: ResearchEventExtractor | None = None,
        batch_size: int = 8,
    ) -> None:
        self.config = config
        self.model_client = model_client or _build_structured_event_model_client(config)
        self.fallback = fallback or HeuristicResearchEventExtractor()
        self.batch_size = max(1, batch_size)
        self._structured_frame_cache: dict[str, ResearchEventFrame] = {}

    def extract(
        self,
        sources: list[ResearchSource],
        *,
        topic: str,
        instructions: str = "",
    ) -> dict[str, ResearchEventFrame]:
        if not sources:
            return {}
        fallback_frames = self.fallback.extract(
            sources,
            topic=topic,
            instructions=instructions,
        )
        if self.model_client is None:
            return fallback_frames
        cached_structured_frames = {
            source.canonical_url: self._structured_frame_cache[cache_key]
            for source in sources
            if (cache_key := _structured_frame_cache_key(source, topic, instructions))
            in self._structured_frame_cache
        }
        fallback_frames.update(cached_structured_frames)
        structured_sources = _sources_requiring_structured_frames(
            sources,
            fallback_frames,
        )
        uncached_structured_sources = [
            source for source in structured_sources
            if _structured_frame_cache_key(source, topic, instructions)
            not in self._structured_frame_cache
        ]
        if not structured_sources:
            logger.info(
                "structured_research_event_extract.skipped source_count=%d reason=heuristic_frames_sufficient",
                len(sources),
            )
            return fallback_frames
        if not uncached_structured_sources:
            logger.info(
                "structured_research_event_extract.cache_hit source_count=%d structured_source_count=%d",
                len(sources),
                len(structured_sources),
            )
            return fallback_frames

        started = time.perf_counter()
        frames = dict(fallback_frames)
        try:
            for batch in _chunks(uncached_structured_sources, self.batch_size):
                for key, frame in self._extract_batch(
                    batch,
                    topic=topic,
                    instructions=instructions,
                ).items():
                    frames[key] = frame
                    source = next(
                        (
                            source for source in batch
                            if source.canonical_url == key
                        ),
                        None,
                    )
                    if source is not None:
                        self._structured_frame_cache[
                            _structured_frame_cache_key(source, topic, instructions)
                        ] = frame
        except Exception as exc:  # noqa: BLE001 - provider boundary
            logger.warning(
                "structured_research_event_extract.failed error=%s",
                exc,
                exc_info=True,
            )
            if not self.config.fallback_on_error:
                raise
        logger.info(
            "structured_research_event_extract.completed source_count=%d structured_source_count=%d uncached_source_count=%d duration_ms=%.2f model=%s",
            len(sources),
            len(structured_sources),
            len(uncached_structured_sources),
            (time.perf_counter() - started) * 1000,
            self.config.model_id,
        )
        return frames

    def _extract_batch(
        self,
        sources: list[ResearchSource],
        *,
        topic: str,
        instructions: str,
    ) -> dict[str, ResearchEventFrame]:
        payload = [
            {
                "source_url": source.canonical_url,
                "title": source.title,
                "snippet": source.snippet,
                "url": source.url,
                "published_at": (
                    source.published_at.isoformat() if source.published_at else ""
                ),
                "content": source.content[:1200],
            }
            for source in sources
        ]
        if self.model_client is None:
            return {}
        response = self.model_client.generate(
            StructuredModelRequest(
                operation="research_event_frame",
                version="v1",
                kind="text",
                output_type=StructuredEventFrameBatch,
                max_tokens=1600,
                temperature=0,
                response_format=strict_json_schema_response(
                    "research_event_frames",
                    StructuredEventFrameBatch.model_json_schema(),
                ),
                metadata={"model": self.config.model_id, "component": "research"},
                messages=[
                    {
                        "role": "system",
                        "content": STRUCTURED_RESEARCH_EVENT_SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "topic": topic,
                                "instructions": instructions,
                                "sources": payload,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
        )
        content = strip_json_fence(response.content)
        parsed = _parse_structured_event_batch(content)
        by_url = {source.canonical_url: source for source in sources}
        frames: dict[str, ResearchEventFrame] = {}
        for item in parsed.frames:
            source = by_url.get(item.source_url)
            if source is None:
                continue
            action = _normalize_action(item.action) or _infer_action(source)
            object_text = _normalize_object(item.object, action) or source.title
            actor = item.actor.strip() or _infer_actor(source)
            event_type = _canonical_event_type(item.event_type) or _infer_event_type(
                f"{source.title} {source.snippet} {object_text}"
            )
            entities = _coerce_str_list(item.entities)
            for entity in (actor, object_text):
                if entity and entity not in entities:
                    entities.append(entity)
            frames[source.canonical_url] = ResearchEventFrame(
                source_url=source.canonical_url,
                title=source.title,
                actor=actor,
                action=action,
                object=object_text,
                event_type=event_type or "unknown",
                occurred_at=item.occurred_at,
                entities=entities,
                confidence=_coerce_confidence(item.confidence),
            )
        return frames


class LangExtractResearchEventExtractor:
    """LangExtract-backed Research event-frame extractor."""

    def __init__(
        self,
        config: LangExtractConfig,
        *,
        fallback: ResearchEventExtractor | None = None,
    ) -> None:
        self.config = config
        self.fallback = fallback or HeuristicResearchEventExtractor()

    def extract(
        self,
        sources: list[ResearchSource],
        *,
        topic: str,
        instructions: str = "",
    ) -> dict[str, ResearchEventFrame]:
        frames: dict[str, ResearchEventFrame] = {}
        started = time.perf_counter()
        if not sources:
            return frames
        worker_count = max(1, min(len(sources), self.config.max_workers))

        def extract_one(source: ResearchSource) -> tuple[str, ResearchEventFrame]:
            text = _source_text(source, topic=topic, instructions=instructions)
            try:
                annotated = run_extract(
                    text,
                    prompt=RESEARCH_EVENT_PROMPT,
                    examples=RESEARCH_EVENT_EXAMPLES,
                    config=self.config,
                    openai_schema=build_research_event_openai_schema(),
                )
                frame = self._to_frame(annotated, source)
            except Exception as exc:  # noqa: BLE001 - provider boundary
                logger.warning(
                    "research_event_extract.failed url=%s error=%s",
                    source.canonical_url,
                    exc,
                    exc_info=True,
                )
                if not self.config.fallback_on_error:
                    raise
                frame = heuristic_event_frame(source)
            return source.canonical_url, frame

        if worker_count == 1:
            for source in sources:
                key, frame = extract_one(source)
                frames[key] = frame
        else:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(extract_one, source) for source in sources]
                for future in as_completed(futures):
                    key, frame = future.result()
                    frames[key] = frame
        logger.info(
            "research_event_extract.completed source_count=%d duration_ms=%.2f workers=%d",
            len(sources),
            (time.perf_counter() - started) * 1000,
            worker_count,
        )
        return frames

    @staticmethod
    def _to_frame(annotated: Any, source: ResearchSource) -> ResearchEventFrame:
        for ext in getattr(annotated, "extractions", None) or []:
            attrs = dict(getattr(ext, "attributes", None) or {})
            if getattr(ext, "extraction_class", "") != "research_event":
                continue
            return ResearchEventFrame(
                source_url=source.canonical_url,
                title=source.title,
                actor=str(attrs.get("actor") or ""),
                action=str(attrs.get("action") or ""),
                object=str(attrs.get("object") or ""),
                event_type=str(attrs.get("event_type") or "unknown"),
                occurred_at=str(attrs.get("occurred_at") or ""),
                entities=_coerce_str_list(attrs.get("entities")),
                confidence=_coerce_confidence(attrs.get("confidence")),
            )
        return heuristic_event_frame(source)


def frames_describe_same_event(
    left: ResearchEventFrame,
    right: ResearchEventFrame,
) -> bool:
    left_object = left.object_tokens
    right_object = right.object_tokens
    if not left_object or not right_object:
        return False
    object_overlap = _jaccard(left_object, right_object)
    object_containment = (
        len(left_object & right_object) / max(1, min(len(left_object), len(right_object)))
    )
    if object_overlap < 0.35 and object_containment < 0.75:
        return False

    left_actor = left.actor_tokens
    right_actor = right.actor_tokens
    if left_actor and right_actor and not (left_actor & right_actor):
        return False

    left_action = left.action_key
    right_action = right.action_key
    if left_action and right_action and left_action != right_action:
        return False

    left_type = left.event_type_key
    right_type = right.event_type_key
    if left_type and right_type:
        if left_type != right_type:
            return False

    return True


def heuristic_event_frame(source: ResearchSource) -> ResearchEventFrame:
    text = f"{source.title} {source.snippet}"
    tokens = _tokens(text)
    action = next(
        (_canonical_action(token) for token in tokens if _canonical_action(token) != token),
        "",
    )
    actor = _infer_actor(source)
    object_tokens = [
        token
        for token in _ordered_tokens(source.title)
        if token not in _tokens(actor)
        and token != action
        and _canonical_action(token) == token
    ]
    return ResearchEventFrame(
        source_url=source.canonical_url,
        title=source.title,
        actor=actor,
        action=action,
        object=" ".join(object_tokens) or source.title,
        event_type=_infer_event_type(text),
        occurred_at=source.published_at.isoformat() if source.published_at else "",
        entities=[actor] if actor else [],
        confidence=0.45,
    )


def build_research_event_openai_schema() -> OpenAISchema:
    attrs = {
        "actor": _nullable({"type": "string"}),
        "action": _nullable({"type": "string"}),
        "object": _nullable({"type": "string"}),
        "event_type": _nullable({"type": "string"}),
        "occurred_at": _nullable({"type": "string"}),
        "entities": _nullable({"type": "array", "items": {"type": "string"}}),
        "confidence": _nullable({"type": "number"}),
    }
    event_attrs = {
        "type": "object",
        "properties": attrs,
        "required": list(attrs),
        "additionalProperties": False,
    }
    event_variant = {
        "type": "object",
        "properties": {
            "research_event": {"type": "string"},
            "research_event_attributes": _nullable(event_attrs),
        },
        "required": ["research_event", "research_event_attributes"],
        "additionalProperties": False,
    }
    return OpenAISchema(
        schema_dict={
            "type": "object",
            "properties": {
                "extractions": {
                    "type": "array",
                    "items": {"anyOf": [event_variant]},
                }
            },
            "required": ["extractions"],
            "additionalProperties": False,
        },
        schema_name="langextract_research_event_extractions",
        strict=True,
    )


RESEARCH_EVENT_PROMPT = (
    "Extract exactly one event frame from the source. Fill actor, action, "
    "object, event_type, occurred_at, entities, confidence. The frame should "
    "capture what happened, not merely copy the title. Use exact source spans "
    "for extraction_text and respond as JSON."
)

RESEARCH_EVENT_EXAMPLES: list[lx.data.ExampleData] = [
    lx.data.ExampleData(
        text=(
            "Title: OpenAI launches Agent Runtime SDK\n"
            "Snippet: OpenAI launches an SDK for agent runtime orchestration."
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="research_event",
                extraction_text="OpenAI launches Agent Runtime SDK",
                attributes={
                    "actor": "OpenAI",
                    "action": "release",
                    "object": "Agent Runtime SDK",
                    "event_type": "product_release",
                    "occurred_at": "",
                    "entities": ["OpenAI", "Agent Runtime SDK"],
                    "confidence": 0.9,
                },
            )
        ],
    ),
    lx.data.ExampleData(
        text=(
            "Title: OpenAI patches Agent Runtime SDK security issue\n"
            "Snippet: OpenAI fixes a security issue in the SDK."
        ),
        extractions=[
            lx.data.Extraction(
                extraction_class="research_event",
                extraction_text="OpenAI patches Agent Runtime SDK security issue",
                attributes={
                    "actor": "OpenAI",
                    "action": "patch",
                    "object": "Agent Runtime SDK security issue",
                    "event_type": "security_update",
                    "occurred_at": "",
                    "entities": ["OpenAI", "Agent Runtime SDK"],
                    "confidence": 0.86,
                },
            )
        ],
    ),
]

STRUCTURED_RESEARCH_EVENT_SYSTEM_PROMPT = (
    "You normalize news/search sources into event identity frames for clustering. "
    "Return exactly one frame for every input source_url. Use the source_url unchanged. "
    "The frame must describe the real event, not publication coverage. "
    "Prefer canonical actions: release, patch, update, improve, announce, report, other. "
    "Prefer event_type values: product_release, security_update, benchmark_release, "
    "research_publication, funding, policy, unknown. If no clear event exists, keep "
    "object close to the title and use confidence <= 0.45. Make actor/object/entity "
    "names stable across sources that describe the same event."
)


def _source_text(
    source: ResearchSource,
    *,
    topic: str,
    instructions: str,
) -> str:
    return "\n".join([
        f"Topic: {topic}",
        f"Instructions: {instructions}",
        f"Title: {source.title}",
        f"Snippet: {source.snippet}",
        f"URL: {source.url}",
        f"Published at: {source.published_at.isoformat() if source.published_at else ''}",
        f"Content: {source.content[:3000]}",
    ])


def _infer_actor(source: ResearchSource) -> str:
    lowered = f"{source.domain} {source.title}".lower()
    if "openai" in lowered:
        return "OpenAI"
    if "github" in lowered:
        return "GitHub"
    first = next(iter(_ordered_tokens(source.title)), "")
    return first


def _infer_event_type(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("security", "vulnerability", "patch")):
        return "security_update"
    if any(token in lowered for token in ("launch", "release", "announce", "ship")):
        return "product_release"
    if any(token in lowered for token in ("benchmark", "evaluation")):
        return "benchmark_release"
    return "unknown"


def _infer_action(source: ResearchSource) -> str:
    text = f"{source.title} {source.snippet}"
    for token in _ordered_tokens(text):
        action = _canonical_action(token)
        if action != token:
            return action
    return ""


def _normalize_action(value: str) -> str:
    tokens = _ordered_tokens(value)
    if not tokens:
        return ""
    return _canonical_action(tokens[0])


def _normalize_object(value: str, action: str) -> str:
    text = value.strip()
    if not text:
        return ""
    tokens = _ordered_tokens(text)
    if tokens and action and _canonical_action(tokens[0]) == action:
        raw_parts = text.split(maxsplit=1)
        if len(raw_parts) == 2:
            text = raw_parts[1].strip()
    return text


def _tokens(text: str) -> set[str]:
    return set(_ordered_tokens(text))


def _ordered_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(text):
        normalized = _normalize_token(token)
        if normalized:
            tokens.append(normalized)
    return tokens


def _normalize_token(token: str) -> str:
    lowered = token.lower()
    if len(lowered) <= 1 or lowered in _STOPWORDS:
        return ""
    if len(lowered) > 5 and lowered.endswith("ies"):
        lowered = lowered[:-3] + "y"
    elif len(lowered) > 5 and lowered.endswith("ches"):
        lowered = lowered[:-2]
    elif len(lowered) > 5 and lowered.endswith("shes"):
        lowered = lowered[:-2]
    elif len(lowered) > 4 and lowered.endswith("ed"):
        lowered = lowered[:-1] if lowered.endswith("eed") else lowered[:-2]
    elif len(lowered) > 4 and lowered.endswith("s") and not lowered.endswith("ss"):
        lowered = lowered[:-1]
    return lowered


def _canonical_action(token: str) -> str:
    if token in _GENERIC_ACTIONS:
        return ""
    return _ACTION_CANONICAL.get(token, token)


def _canonical_event_type(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _GENERIC_EVENT_TYPES:
        return ""
    return _EVENT_TYPE_CANONICAL.get(normalized, normalized)


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _nullable(inner: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [inner, {"type": "null"}]}


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _structured_frame_cache_key(
    source: ResearchSource,
    topic: str,
    instructions: str,
) -> str:
    material = json.dumps(
        {
            "topic": topic,
            "instructions": instructions,
            "canonical_url": source.canonical_url,
            "title": source.title,
            "snippet": source.snippet,
            "content_fingerprint": source.content_fingerprint,
            "content_preview": source.content[:1200] if source.content else "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _sources_requiring_structured_frames(
    sources: list[ResearchSource],
    fallback_frames: dict[str, ResearchEventFrame],
) -> list[ResearchSource]:
    if len(sources) <= 1:
        return []
    required: dict[str, ResearchSource] = {}
    for source in sources:
        frame = fallback_frames.get(source.canonical_url)
        if frame is None:
            required[source.canonical_url] = source
            continue
        if _frame_is_underspecified(frame) and _has_related_source(source, sources):
            required[source.canonical_url] = source
    for left_index, left in enumerate(sources):
        left_frame = fallback_frames.get(left.canonical_url)
        if left_frame is None:
            continue
        for right in sources[left_index + 1:]:
            right_frame = fallback_frames.get(right.canonical_url)
            if right_frame is None:
                continue
            if _pair_needs_semantic_frame(left, right, left_frame, right_frame):
                required[left.canonical_url] = left
                required[right.canonical_url] = right
    return list(required.values())


def _frame_is_underspecified(frame: ResearchEventFrame) -> bool:
    return not frame.action_key or not frame.event_type_key or len(frame.object_tokens) <= 1


def _has_related_source(source: ResearchSource, sources: list[ResearchSource]) -> bool:
    source_tokens = _tokens(source.title)
    for other in sources:
        if other.canonical_url == source.canonical_url:
            continue
        other_tokens = _tokens(other.title)
        if _jaccard(source_tokens, other_tokens) >= 0.2:
            return True
    return False


def _pair_needs_semantic_frame(
    left: ResearchSource,
    right: ResearchSource,
    left_frame: ResearchEventFrame,
    right_frame: ResearchEventFrame,
) -> bool:
    left_tokens = _tokens(left.title)
    right_tokens = _tokens(right.title)
    title_overlap = _jaccard(left_tokens, right_tokens)
    if title_overlap >= 0.75 or title_overlap < 0.2:
        return False
    left_object = left_frame.object_tokens
    right_object = right_frame.object_tokens
    object_containment = (
        len(left_object & right_object) / max(1, min(len(left_object), len(right_object)))
    )
    same_actor = bool(left_frame.actor_tokens & right_frame.actor_tokens)
    if same_actor and object_containment >= 0.45:
        return True
    if title_overlap >= 0.35 and object_containment >= 0.35:
        return True
    return _frame_is_underspecified(left_frame) or _frame_is_underspecified(right_frame)


def _chunks(values: list[ResearchSource], size: int) -> list[list[ResearchSource]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _build_structured_event_model_client(
    config: LangExtractConfig,
) -> StructuredModelClient | None:
    if not (config.api_key and config.base_url and config.model_id):
        return None
    return OpenAIModelClient(
        OpenAIConfig(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model_id,
            timeout_seconds=60.0,
            max_retries=1,
        )
    )


def _parse_structured_event_batch(content: str) -> StructuredEventFrameBatch:
    try:
        return StructuredEventFrameBatch.model_validate_json(content)
    except Exception:
        data = _extract_json_value(content)
        if isinstance(data, list):
            data = {"frames": data}
        return StructuredEventFrameBatch.model_validate(data)


def _extract_json_value(content: str) -> Any:
    text = strip_json_fence(content).strip()
    decoder = json.JSONDecoder()
    starts = [
        index
        for index, char in enumerate(text)
        if char in ("{", "[")
    ]
    last_error: Exception | None = None
    for start in starts:
        try:
            value, _ = decoder.raw_decode(text[start:])
            return value
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return json.loads(text)


__all__ = [
    "HeuristicResearchEventExtractor",
    "LangExtractResearchEventExtractor",
    "ResearchEventExtractor",
    "ResearchEventFrame",
    "StructuredResearchEventExtractor",
    "build_research_event_openai_schema",
    "frames_describe_same_event",
    "heuristic_event_frame",
]
