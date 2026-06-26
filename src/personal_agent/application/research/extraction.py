"""Research event-frame extraction and same-event matching.

Research owns this module because event identity is a domain concept, not a
generic LangExtract concern. ``ResearchService`` depends on the
``ResearchEventExtractor`` port; LangExtract is only one implementation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import langextract as lx
from langextract.providers.schemas.openai import OpenAISchema

from personal_agent.application.extract.langextract_client import run_extract
from personal_agent.kernel.config import LangExtractConfig
from personal_agent.kernel.contracts.research import ResearchSource

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
        return _tokens(self.actor)

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
        for source in sources:
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
            frames[source.canonical_url] = frame
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


__all__ = [
    "HeuristicResearchEventExtractor",
    "LangExtractResearchEventExtractor",
    "ResearchEventExtractor",
    "ResearchEventFrame",
    "build_research_event_openai_schema",
    "frames_describe_same_event",
    "heuristic_event_frame",
]
