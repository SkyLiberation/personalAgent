"""Pre-extraction service: text -> SectionMap.

LangExtract is a mandatory step in the capture pipeline. The only
short-circuits are:
  * docs shorter than ``min_doc_chars`` (extraction has nothing to learn from)
  * runtime errors when ``fallback_on_error`` is True (network / LLM hiccups)

Both branches return an empty SectionMap; the caller stamps the parent note
with ``preextract_status`` so the skip is observable.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.config import LangExtractConfig
from .langextract_client import run_extract
from .prompts import EXAMPLES, PROMPT_DESCRIPTION
from .schemas import SectionMap, SectionRecord

logger = logging.getLogger(__name__)


class PreExtractError(RuntimeError):
    """Raised when pre-extraction fails and fallback is disabled."""


class PreExtractService:
    """Lightweight pre-extraction over raw document text."""

    def __init__(
        self,
        config: LangExtractConfig,
        *,
        prompt: str = PROMPT_DESCRIPTION,
        examples: list | None = None,
    ) -> None:
        self.config = config
        self.prompt = prompt
        self.examples = examples if examples is not None else EXAMPLES

    def should_run(self, text: str) -> bool:
        return len(text) >= self.config.min_doc_chars

    def extract(self, text: str) -> SectionMap:
        """Run pre-extraction and return a SectionMap.

        Returns an empty SectionMap when the input is too short. On runtime
        errors, returns an empty SectionMap iff ``config.fallback_on_error``
        is True; otherwise re-raises as :class:`PreExtractError`.
        """
        if not self.should_run(text):
            logger.debug(
                "pre_extract.skip text_len=%d min=%d",
                len(text),
                self.config.min_doc_chars,
            )
            return SectionMap()

        try:
            annotated = run_extract(
                text,
                prompt=self.prompt,
                examples=self.examples,
                config=self.config,
            )
        except Exception as exc:  # noqa: BLE001 - boundary with third-party lib
            logger.warning("pre_extract.failed error=%s", exc, exc_info=True)
            if self.config.fallback_on_error:
                return SectionMap()
            raise PreExtractError(str(exc)) from exc

        return self._to_section_map(annotated, text)

    @staticmethod
    def _to_section_map(annotated: Any, source_text: str) -> SectionMap:
        sections: list[SectionRecord] = []
        for ext in getattr(annotated, "extractions", None) or []:
            attrs: dict[str, Any] = dict(getattr(ext, "attributes", None) or {})
            char_interval = getattr(ext, "char_interval", None)
            char_start = int(getattr(char_interval, "start_pos", 0) or 0)
            char_end = int(
                getattr(char_interval, "end_pos", 0) or len(source_text)
            )
            sections.append(
                SectionRecord(
                    title=str(attrs.get("title") or attrs.get("topic") or "")[:80],
                    char_start=char_start,
                    char_end=char_end,
                    topic=str(attrs.get("topic") or "")[:80],
                    summary=str(attrs.get("summary") or "")[:200],
                    contains_entities=_coerce_str_list(attrs.get("contains_entities")
                                                      or attrs.get("entities")),
                    contains_relations=bool(attrs.get("contains_relations", False)),
                    information_density=_coerce_density(
                        attrs.get("information_density")
                    ),
                    graph_worthy=bool(attrs.get("graph_worthy", False)),
                    reason=str(attrs.get("reason") or "")[:80],
                )
            )

        doc_topic = ""
        if sections:
            doc_topic = sections[0].topic
        return SectionMap(doc_topic=doc_topic, sections=sections)


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    return []


def _coerce_density(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    return "medium"
