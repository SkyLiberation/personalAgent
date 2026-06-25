from __future__ import annotations

from personal_agent.application.review.models import ReviewDigest


class DigestFormatter:
    """Render structured review digests for delivery channels."""

    def to_text(self, digest: ReviewDigest) -> str:
        lines = ["今日知识简报"]
        for section in digest.sections:
            if not section.items:
                continue
            lines.append(section.title)
            lines.extend(f"- {item}" for item in section.items)
        if len(lines) == 1:
            lines.append(digest.empty_reason or "当前还没有知识记录。")
        return "\n".join(lines)

    def to_feishu_text(self, digest: ReviewDigest) -> str:
        return self.to_text(digest)
