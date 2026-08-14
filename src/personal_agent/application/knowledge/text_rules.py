"""Deterministic text, claim-shape, and relation rules for knowledge ingestion."""

from __future__ import annotations

import re

from personal_agent.application.evidence_engine import evidence_terms
from personal_agent.application.knowledge.models import Claim


def normalize_text(text: str) -> str:
    return "\n".join(
        line.strip() for line in str(text or "").splitlines() if line.strip()
    )


def split_blocks(text: str, *, max_chars: int = 1200) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    blocks: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            blocks.append(paragraph)
            continue
        for index in range(0, len(paragraph), max_chars):
            block = paragraph[index : index + max_chars].strip()
            if block:
                blocks.append(block)
    return blocks


def block_type(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2 and sum(1 for line in lines if "|" in line) >= 2:
        return "table"
    if any(line.lstrip().startswith(("-", "*", "1.", "2.")) for line in lines):
        return "list"
    if "```" in text:
        return "code"
    return "paragraph"


def split_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(r"[^。！？!?；;\n]+[。！？!?；;]?", text):
        sentence = match.group(0).strip()
        if len(sentence) < 8:
            continue
        spans.append((match.start(), match.end(), sentence))
    if not spans and text.strip():
        stripped = text.strip()
        spans.append((0, len(stripped), stripped))
    return spans


def span_type(text: str) -> str:
    if any(marker in text for marker in ("步骤", "先", "然后", "流程")):
        return "procedure"
    if any(marker in text for marker in ("必须", "不能", "禁止", "仅当", "如果")):
        return "constraint"
    if any(marker in text for marker in ("例如", "比如")):
        return "example"
    if "是" in text or "表示" in text:
        return "definition"
    return "factual_statement"


def normalize_meaning(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())[:240]


def semantic_tags(text: str) -> list[str]:
    tags: list[str] = []
    if any(marker in text for marker in ("默认开启", "默认关闭", "开启", "关闭")):
        tags.append("default_state")
    if any(marker in text for marker in ("每分钟", "rate limit", "limit", "限制")):
        tags.append("rate_limit")
    if any(marker in text for marker in ("部署", "发布", "回滚", "蓝绿")):
        tags.append("deployment")
    if any(marker in text for marker in ("规范", "scope", "版本")):
        tags.append("scope")
    return tags


def canonical(statement: str) -> str:
    return re.sub(r"\s+", " ", statement.strip().lower())


def semantic_claim_parts(
    statement: str,
) -> tuple[str, str, str, str, str, str | None]:
    text = statement.strip()
    scope = ""
    condition = ""
    valid_time: str | None = None
    scope_match = re.search(
        r"(规范\s*[A-ZＡ-ＺA-Za-z0-9]+|版本\s*[A-Za-z0-9_.-]+|服务端规范\s*[A-ZＡ-ＺA-Za-z0-9]+)",
        text,
    )
    if scope_match:
        scope = scope_match.group(1).replace(" ", "")
    time_match = re.search(
        r"(\d{4}[-/年]\d{1,2}(?:[-/月]\d{1,2})?|每周[一二三四五六日天]|周[一二三四五六日天]|上午十点|下午\d+点)",
        text,
    )
    if time_match:
        valid_time = time_match.group(1)
    condition_match = re.search(r"(如果|仅当|当)(.+?)(?:，|,|时)", text)
    if condition_match:
        condition = condition_match.group(0).strip("，,")
    subject = text
    predicate = "states"
    obj = ""
    patterns = [
        (r"(.+?)(默认开启|默认关闭)", "default_state"),
        (r"(.+?)(支持|不支持)(.+)", "support"),
        (r"(.+?)(是|为)(.+)", "is"),
        (r"(.+?)(使用|采用)(.+)", "uses"),
        (r"(.+?)(保留)(.+)", "keeps"),
        (r"(.+?)(切到|切换到)(.+)", "switches_to"),
    ]
    for pattern, pred in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        subject = match.group(1).strip(" ，,。")
        predicate = pred
        obj = "".join(match.groups()[1:]).strip(" ，,。")
        break
    return subject[:120], predicate, obj[:160], scope[:120], condition[:160], valid_time


def requires_scope(statement: str) -> bool:
    return any(marker in statement for marker in ("规范", "版本"))


def sensitivity_level(statement: str) -> str:
    lowered = statement.lower()
    high_markers = ("密码", "身份证", "银行卡", "token", "secret", "api key", "私钥")
    if any(marker in lowered or marker in statement for marker in high_markers):
        return "high"
    medium_markers = ("手机号", "地址", "住址", "健康", "收入")
    if any(marker in statement for marker in medium_markers):
        return "medium"
    return "low"


def confidence_for_support(status: str) -> float:
    return {
        "supported": 0.9,
        "user_asserted": 0.85,
        "partially_supported": 0.55,
        "unsupported": 0.2,
        "not_found": 0.1,
        "contradicted": 0.0,
    }.get(status, 0.0)


def relation_between_claims(
    new_claim: Claim,
    existing: Claim,
) -> tuple[str | None, float, str]:
    if new_claim.canonical_key and new_claim.canonical_key == existing.canonical_key:
        return "duplicate", 1.0, "same canonical key"
    new_text = new_claim.canonical_statement or canonical(new_claim.statement)
    old_text = existing.canonical_statement or canonical(existing.statement)
    if new_text == old_text:
        return "duplicate", 1.0, "same canonical statement"
    if new_claim.subject and existing.subject and new_claim.predicate == existing.predicate:
        subject_overlap = evidence_terms(new_claim.subject) & evidence_terms(
            existing.subject
        )
        if subject_overlap and looks_contradictory(
            " ".join([new_claim.object, new_claim.statement]),
            " ".join([existing.object, existing.statement]),
        ):
            return (
                "potential_conflict",
                0.82,
                "structured subject/predicate match with opposing polarity markers",
            )
    new_terms = evidence_terms(new_claim.statement)
    old_terms = evidence_terms(existing.statement)
    if not new_terms or not old_terms:
        return None, 0.0, ""
    overlap = len(new_terms & old_terms)
    overlap_ratio = overlap / max(min(len(new_terms), len(old_terms)), 1)
    if overlap_ratio < 0.35:
        return None, 0.0, ""
    if looks_contradictory(new_claim.statement, existing.statement):
        return (
            "potential_conflict",
            max(0.7, min(overlap_ratio, 1.0)),
            "opposing polarity markers on overlapping claims",
        )
    if overlap_ratio >= 0.8:
        return "duplicate", overlap_ratio, "high lexical overlap"
    if overlap_ratio >= 0.45:
        return "supplement", overlap_ratio, "overlapping but not equivalent claim"
    return None, 0.0, ""


def relation_write_allowed(
    new_claim: Claim,
    existing: Claim,
    *,
    confidence: float,
) -> bool:
    if confidence < 0.9:
        return False
    if (
        not new_claim.quality_gate.has_valid_evidence_ref
        and new_claim.support_status != "user_asserted"
    ):
        return False
    if (
        not existing.quality_gate.has_valid_evidence_ref
        and existing.support_status != "user_asserted"
    ):
        return False
    if new_claim.support_status in {"unsupported", "not_found"}:
        return False
    if existing.support_status in {"unsupported", "not_found"}:
        return False
    if new_claim.subject and existing.subject:
        subject_overlap = evidence_terms(new_claim.subject) & evidence_terms(
            existing.subject
        )
        if not subject_overlap:
            return False
    if new_claim.scope and existing.scope and new_claim.scope != existing.scope:
        return False
    if (
        new_claim.valid_time
        and existing.valid_time
        and new_claim.valid_time != existing.valid_time
    ):
        return False
    return True


def looks_contradictory(a: str, b: str) -> bool:
    pairs = (
        ("默认开启", "默认关闭"),
        ("开启", "关闭"),
        ("支持", "不支持"),
        ("可以", "不能"),
        ("必须", "禁止"),
        ("需要", "不需要"),
        ("true", "false"),
        ("enabled", "disabled"),
    )
    return any(
        (left in a and right in b) or (right in a and left in b)
        for left, right in pairs
    )


def extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    for token in re.findall(r"[A-Z][A-Za-z0-9_-]{1,}", text):
        if token not in entities:
            entities.append(token)
    for chunk in re.findall(r"[\u3400-\u9fffA-Za-z0-9_-]{2,}", text):
        normalized = chunk.strip("。！？!?；;，,：:")
        if len(normalized) >= 2 and normalized not in entities:
            entities.append(normalized)
        if len(entities) >= 8:
            break
    return entities[:8]


def knowledge_item_title(statement: str) -> str:
    title = statement.strip().splitlines()[0]
    return title[:48] if len(title) > 48 else title


__all__ = [
    "block_type",
    "canonical",
    "confidence_for_support",
    "extract_entities",
    "knowledge_item_title",
    "looks_contradictory",
    "normalize_meaning",
    "normalize_text",
    "relation_between_claims",
    "relation_write_allowed",
    "requires_scope",
    "semantic_claim_parts",
    "semantic_tags",
    "sensitivity_level",
    "span_type",
    "split_blocks",
    "split_spans",
]
