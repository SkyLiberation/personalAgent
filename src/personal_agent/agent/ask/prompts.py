from __future__ import annotations

from personal_agent.kernel.evidence import ContextPack
from personal_agent.kernel.models import Citation, KnowledgeNote
from personal_agent.kernel.prompts import get_prompt, render_prompt
from personal_agent.memory.graphiti.store import GraphAskResult
from personal_agent.agent.runtime_helpers import (
    _evidence_content,
    _format_graph_relation,
    _top_sentences,
)


class AskPromptMixin:
    def _dialogue_context_policy(self) -> str:
        return getattr(
            self,
            "dialogue_context_policy",
            get_prompt("answer.dialogue_context_policy").template,
        )

    def _build_web_answer_prompt(
        self, question: str, web_results: list[dict], web_citations: list[Citation],
        working_context: str,
    ) -> str:
        context_block = working_context or "无"
        web_blocks: list[str] = []
        for i, citation in enumerate(web_citations[:5], 1):
            web_blocks.append(
                f"[来源{i}] {citation.title}\n"
                f"URL: {citation.url}\n"
                f"摘要: {citation.snippet[:200]}"
            )
        web_block = "\n\n".join(web_blocks) if web_blocks else "无"
        return render_prompt(
            "ask.web_answer.user",
            dialogue_context_policy=self._dialogue_context_policy(),
            question=question,
            context_block=context_block,
            web_block=web_block,
        )

    def _compose_web_answer(
        self, question: str, web_results: list[dict], web_citations: list[Citation],
        working_context: str,
    ) -> str:
        prompt = self._build_web_answer_prompt(question, web_results, web_citations, working_context)
        prompt_spec = get_prompt("ask.web_answer.user")
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="ask_web_answer",
            prompt_version=prompt_spec.version,
        )
        if web_citations:
            sources = "、".join(
                f"[{c.title}]({c.url})" for c in web_citations[:3] if c.url
            )
            return f"{generated}\n\n参考来源：{sources}" if generated and sources else generated
        return generated or "网络搜索未返回足够信息来回答这个问题。"

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

    def _build_graph_answer_prompt(
        self, question: str, graph_result: GraphAskResult,
        matches: list[KnowledgeNote], citations: list[Citation], working_context: str,
    ) -> str:
        if graph_result.node_refs:
            entity_lines = []
            for ref in graph_result.node_refs[:6]:
                line = ref.name
                if ref.summary:
                    line += f"（{ref.summary[:80]}）"
                entity_lines.append(line)
            focus_entities = "、".join(entity_lines) if entity_lines else "暂无"
        else:
            focus_entities = "、".join(graph_result.entity_names[:6]) if graph_result.entity_names else "暂无"
        graph_fact_blocks = self._build_graph_fact_blocks(graph_result, citations)
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        anchored_lines: list[str] = []
        for c in citations:
            label = c.title or c.note_id
            if c.relation_fact:
                label += f"  [事实: {c.relation_fact}]"
            if c.snippet:
                label += f"  [原文: {c.snippet[:120]}]"
            anchored_lines.append(f"- {label}")
        context_block = working_context or "无"
        graph_fact_block = "\n".join(graph_fact_blocks) if graph_fact_blocks else "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        anchored_block = "\n".join(anchored_lines) if anchored_lines else "无"

        return render_prompt(
            "ask.graph_answer.user",
            dialogue_context_policy=self._dialogue_context_policy(),
            question=question,
            context_block=context_block,
            focus_entities=focus_entities,
            graph_fact_block=graph_fact_block,
            anchored_block=anchored_block,
            notes_block=notes_block,
        )

    def _build_graph_fact_blocks(
        self, graph_result: GraphAskResult, citations: list[Citation], limit: int = 8
    ) -> list[str]:
        blocks: list[str] = []
        citation_snippets: dict[str, str] = {}
        for citation in citations:
            if citation.relation_fact and citation.snippet:
                citation_snippets.setdefault(citation.relation_fact, citation.snippet)

        seen: set[str] = set()
        focus_budget = max(1, limit - max(1, limit // 4))

        for hit in graph_result.citation_hits:
            fact = hit.relation_fact.strip()
            if not fact or fact in seen:
                continue
            source = hit.endpoint_names[0] if hit.endpoint_names else ""
            target = hit.endpoint_names[1] if len(hit.endpoint_names) > 1 else ""
            relation = _format_graph_relation(fact, source, target, citation_snippets.get(fact))
            blocks.append(f"- {relation}")
            seen.add(fact)
            if len(blocks) >= focus_budget:
                break

        for fact_ref in graph_result.fact_refs:
            if len(blocks) >= limit:
                break
            fact = fact_ref.fact.strip()
            if not fact or fact in seen:
                continue
            relation = _format_graph_relation(
                fact,
                fact_ref.source_node_name,
                fact_ref.target_node_name,
                citation_snippets.get(fact),
            )
            blocks.append(f"- {relation}")
            seen.add(fact)

        for edge_ref in graph_result.edge_refs:
            if len(blocks) >= limit:
                break
            fact = edge_ref.fact.strip()
            if not fact or fact in seen:
                continue
            relation = _format_graph_relation(
                fact,
                edge_ref.source_node_name,
                edge_ref.target_node_name,
                citation_snippets.get(fact),
            )
            blocks.append(f"- {relation}")
            seen.add(fact)

        for fact in graph_result.relation_facts:
            if len(blocks) >= limit:
                break
            if fact and fact not in seen:
                blocks.append(f"- {fact}")
                seen.add(fact)
        return blocks

    def _compose_graph_answer(
        self, question: str, graph_result: GraphAskResult,
        matches: list[KnowledgeNote], citations: list[Citation], working_context: str,
    ) -> str:
        prompt = self._build_graph_answer_prompt(
            question, graph_result, matches, citations, working_context,
        )
        prompt_spec = get_prompt("ask.graph_answer.user")
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="ask_graph_answer",
            prompt_version=prompt_spec.version,
        )
        if generated:
            facts = [c.relation_fact for c in citations if c.relation_fact]
            if facts and not any(fact in generated for fact in facts[:3]):
                generated += "\n\n相关图谱事实：" + "；".join(facts[:3])
            return generated
        if citations:
            facts = [c.relation_fact for c in citations if c.relation_fact]
            if facts:
                return "结合你已有的笔记和图谱信息，" + "；".join(facts[:4]) + "。"
        return graph_result.answer or "暂时没有生成答案。"

    def _build_local_answer_prompt(
        self, question: str, matches: list[KnowledgeNote],
        citations: list[Citation], working_context: str,
    ) -> str:
        evidence_blocks = self._build_note_evidence_blocks(matches, citations)
        context_block = working_context or "无"
        notes_block = "\n\n".join(evidence_blocks) if evidence_blocks else "无"
        return render_prompt(
            "ask.local_answer.user",
            dialogue_context_policy=self._dialogue_context_policy(),
            question=question,
            context_block=context_block,
            notes_block=notes_block,
        )

    def _compose_local_answer(
        self, question: str, matches: list[KnowledgeNote],
        citations: list[Citation], working_context: str,
    ) -> str:
        prompt = self._build_local_answer_prompt(question, matches, citations, working_context)
        prompt_spec = get_prompt("ask.local_answer.user")
        generated = self._llm.generate_answer(
            prompt,
            prompt_name="ask_local_answer",
            prompt_version=prompt_spec.version,
        )
        if generated:
            return generated
        if matches:
            return f"结合你前面的提问和当前笔记内容，我更倾向于认为：{matches[0].body.summary}"
        return "我暂时无法从你的个人知识库中找到足够依据来回答这个问题。"

    def _build_note_evidence_blocks(
        self, matches: list[KnowledgeNote], citations: list[Citation]
    ) -> list[str]:
        citation_map: dict[str, list[Citation]] = {}
        for citation in citations:
            citation_map.setdefault(citation.note_id, []).append(citation)

        blocks: list[str] = []
        for idx, note in enumerate(matches[:5], 1):
            candidate_snippets = [item.snippet for item in citation_map.get(note.id, []) if item.snippet]
            if not candidate_snippets:
                candidate_snippets = _top_sentences(_evidence_content(note), 3)
            excerpt = "\n".join(f"- {s}" for s in candidate_snippets[:3] if s.strip())
            if not excerpt:
                excerpt = f"- {note.body.summary or note.body.content[:160]}"
            blocks.append(f"[{idx}] {note.body.title}\n摘要: {note.body.summary}\n证据:\n{excerpt}")
        return blocks
