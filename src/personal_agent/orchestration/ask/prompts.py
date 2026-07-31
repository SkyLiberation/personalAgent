from __future__ import annotations

from personal_agent.kernel.evidence import ContextPack
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.kernel.prompts import get_prompt, render_prompt


class AskPromptMixin:
    def _dialogue_context_policy(self) -> str:
        return getattr(
            self,
            "dialogue_context_policy",
            get_prompt("answer.dialogue_context_policy").template,
        )

    def _build_unified_answer_prompt(
        self,
        question: str,
        context_pack: ContextPack,
        matches: list[KnowledgeNote],
        citations: list[Citation],
        working_context: str,
    ) -> str:
        context_block = working_context or "无"
        evidence_lines: list[str] = []
        for index, ranked_item in enumerate(context_pack.selected, 1):
            item = ranked_item.evidence
            source_label = {
                "graph_fact": "图谱事实",
                "episode": "图谱 episode",
                "note": "笔记",
                "chunk": "笔记片段",
                "web": "网页",
            }.get(item.source_type, item.source_type)
            title = item.title or item.metadata.get("source_node_name") or item.source_id or "无标题"
            content = item.fact or item.snippet or ""
            if item.fact and item.snippet:
                content = f"{item.fact}\n原文锚点：{item.snippet}"
            url_line = f"\nURL: {item.url}" if item.url else ""
            span_line = f"\n位置: {item.source_span}" if item.source_span else ""
            score_line = f"\nscore: {item.score:.3f}" if item.score else ""
            rank_line = (
                f"\nrank_score: {ranked_item.score:.3f}"
                f"\nrank_reason: {ranked_item.reason}"
            )
            evidence_lines.append(
                f"[E{index}] {source_label} | {title}{url_line}{span_line}{score_line}{rank_line}\n{content[:700]}"
            )
        evidence_block = "\n\n".join(evidence_lines) if evidence_lines else "无"

        selected_ids = {
            ranked.evidence.source_id
            for ranked in context_pack.selected
            if ranked.evidence.source_id
        }
        citation_hint = ""
        if citations and selected_ids:
            citation_hint = "\n".join(
                f"- {c.title}: {(c.relation_fact or c.snippet)[:160]}"
                for c in citations
                if c.note_id in selected_ids and (c.title or c.snippet or c.relation_fact)
            )
        if not citation_hint:
            citation_hint = "无"

        match_hint = ""
        if matches and selected_ids:
            match_hint = "\n".join(
                f"- {note.body.title}: {note.body.summary[:160]}"
                for note in matches
                if note.id in selected_ids
            )
        if not match_hint:
            match_hint = "无"

        return render_prompt(
            "ask.unified_answer.user",
            dialogue_context_policy=self._dialogue_context_policy(),
            question=question,
            context_block=context_block,
            selected_count=len(context_pack.selected),
            dropped_count=len(context_pack.dropped),
            used_chars=context_pack.used_chars,
            char_budget=context_pack.char_budget,
            evidence_block=evidence_block,
            citation_hint=citation_hint,
            match_hint=match_hint,
        )

    def _compose_unified_answer(
        self,
        question: str,
        context_pack: ContextPack,
        matches: list[KnowledgeNote],
        citations: list[Citation],
        working_context: str,
    ) -> str:
        if not context_pack.selected and not matches and not citations:
            return "我暂时无法从你的个人知识库或可用检索结果中找到足够依据来回答这个问题。"
        prompt = self._build_unified_answer_prompt(
            question, context_pack, matches, citations, working_context
        )
        prompt_spec = get_prompt("ask.unified_answer.user")
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="ask_unified_answer",
            prompt_version=prompt_spec.version,
        )
        if generated:
            return generated
        if context_pack.selected:
            first = context_pack.selected[0].evidence
            preview = first.fact or first.snippet or first.title
            return f"根据当前检索到的证据，最相关的信息是：{preview}"
        return "我暂时无法从你的个人知识库或可用检索结果中找到足够依据来回答这个问题。"
