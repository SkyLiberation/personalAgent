from __future__ import annotations

from ..memory import MemoryFacade
from .formatter import DigestFormatter
from .models import ReviewDigest, ReviewDigestSection


class ReviewDigestUseCase:
    """Generate review digests from long-term memory."""

    def __init__(self, memory: MemoryFacade, formatter: DigestFormatter | None = None) -> None:
        self.memory = memory
        self.formatter = formatter or DigestFormatter()

    def generate(self, user_id: str, *, recent_limit: int = 5) -> ReviewDigest:
        recent_notes = self.memory.list_recent_notes(user_id, limit=recent_limit)
        due_cards = self.memory.due_reviews(user_id)
        sections: list[ReviewDigestSection] = []

        if recent_notes:
            sections.append(ReviewDigestSection(
                title="最近新增笔记：",
                items=[
                    f"{note.body.title}: {note.body.summary}"
                    for note in recent_notes
                ],
            ))

        if due_cards:
            sections.append(ReviewDigestSection(
                title="待复习内容：",
                items=[card.prompt for card in due_cards],
            ))

        empty_reason = ""
        if not recent_notes and not due_cards:
            empty_reason = "当前还没有知识记录。"

        return ReviewDigest(
            user_id=user_id,
            recent_notes=recent_notes,
            due_cards=due_cards,
            sections=sections,
            empty_reason=empty_reason,
        )

    def generate_text(self, user_id: str, *, recent_limit: int = 5) -> str:
        return self.formatter.to_text(self.generate(user_id, recent_limit=recent_limit))
