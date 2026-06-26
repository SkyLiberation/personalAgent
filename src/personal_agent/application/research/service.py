from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from personal_agent.application.research.models import (
    IntelligenceDigest,
    IntelligenceDigestItem,
    EvidenceGap,
    PersonalRelevance,
    ResearchBudget,
    ResearchDecision,
    ResearchEvent,
    ResearchFeedback,
    ResearchRun,
    ResearchSource,
    ResearchState,
    ResearchSubscription,
)
from personal_agent.application.research.extraction import (
    HeuristicResearchEventExtractor,
    ResearchEventExtractor,
    frames_describe_same_event,
)

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref"}
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_EVENT_STOPWORDS = {
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


class ResearchService:
    """Application service for one-shot and scheduled research.

    The workflow is deterministic at the topology level while query expansion,
    source selection and summarization can use the configured model. Every
    external/internal action still crosses ToolExecutor/ToolGateway.
    """

    def __init__(
        self,
        store,
        tool_executor: Any,
        *,
        generate_text: Callable[[str, str], str | None] | None = None,
        save_note: Callable[..., object] | None = None,
        event_extractor: ResearchEventExtractor | None = None,
    ) -> None:
        self.store = store
        self.tools = tool_executor
        self.generate_text = generate_text
        self.save_note = save_note
        self.event_extractor = event_extractor or HeuristicResearchEventExtractor()
        self.delivery_router = None

    def set_delivery_router(self, router) -> None:
        self.delivery_router = router

    def create_subscription(self, subscription: ResearchSubscription) -> ResearchSubscription:
        return self.store.upsert_subscription(subscription)

    def update_subscription(self, subscription: ResearchSubscription) -> ResearchSubscription:
        return self.store.upsert_subscription(subscription.model_copy(update={"updated_at": datetime.now(UTC)}))

    def get_subscription(self, subscription_id: str) -> ResearchSubscription | None:
        return self.store.get_subscription(subscription_id)

    def list_subscriptions(
        self,
        *,
        user_id: str,
        enabled_only: bool = True,
    ) -> list[ResearchSubscription]:
        return self.store.list_subscriptions(user_id=user_id, enabled_only=enabled_only)

    def list_runs(self, *, user_id: str, limit: int = 50) -> list[ResearchRun]:
        return self.store.list_runs(user_id=user_id, limit=limit)

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self.store.get_run(run_id)

    def get_digest(self, digest_id: str) -> IntelligenceDigest | None:
        return self.store.get_digest(digest_id)

    def initialize_state(self, run_id: str) -> ResearchState:
        run, subscription = self._load_run_context(run_id)
        queries = self._plan_queries(run, subscription)
        decisions = [
            ResearchDecision(
                iteration=index,
                action="search_web",
                query=query,
                purpose=_query_purpose(query),
                reason="initial strategy",
            )
            for index, query in enumerate(queries, 1)
        ]
        state = ResearchState(
            run_id=run.id,
            topic=run.topic,
            instructions=run.instructions,
            window_start=run.window_start,
            window_end=run.window_end,
            budget=run.budget,
            decisions=decisions,
        )
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "query_plan": queries,
            "research_state": state,
        }))
        return state

    def run_research_loop(self, run_id: str) -> ResearchState:
        run, subscription = self._load_run_context(run_id)
        state = run.research_state or self.initialize_state(run_id)
        sources = self.store.list_run_sources(run.id)
        events = self.store.list_run_events(run.id)

        while not state.stop_reason:
            if state.iteration_count >= state.budget.max_queries:
                state.stop_reason = "query budget exhausted"
                break
            decision = self._next_research_decision(state, events)
            if decision.action == "stop":
                decision.status = "executed"
                if decision not in state.decisions:
                    state.decisions.append(decision)
                state.stop_reason = decision.reason or "no useful next action"
                break
            if not self._decision_allowed(decision, state):
                decision.status = "skipped"
                if decision not in state.decisions:
                    state.decisions.append(decision)
                state.stop_reason = "no new allowed research action"
                break

            state.iteration_count += 1
            new_sources = self._execute_research_decision(run, subscription, decision)
            decision.status = "executed"
            decision.result_count = len(new_sources)
            state.query_history.append(decision.query)
            if decision not in state.decisions:
                state.decisions.append(decision)
            state.low_yield_rounds = state.low_yield_rounds + 1 if not new_sources else 0

            sources = _merge_sources(sources, new_sources)
            self.store.replace_run_sources(run.id, sources)
            events = self._cluster_sources(run, subscription, sources)
            events = self._personalize_and_rank(run, subscription, events)
            self.store.replace_run_events(run.id, events)
            state.evidence_gaps = self._evidence_gaps(events)

            run = run.model_copy(update={
                "status": "running",
                "source_count": len(sources),
                "event_count": len(events),
                "selected_count": min(len(events), subscription.max_items if subscription else 5),
                "research_state": state,
            })
            self.store.update_run(run)
            if self._should_stop_loop(state, events):
                break

        if not state.stop_reason:
            state.stop_reason = "research loop completed"
        self.store.update_run(run.model_copy(update={
            "research_state": state,
            "source_count": len(sources),
            "event_count": len(events),
        }))
        return state

    def synthesize_digest(
        self,
        run_id: str,
        *,
        max_items: int | None = None,
    ) -> ResearchRun:
        run, subscription = self._load_run_context(run_id)
        events = self.store.list_run_events(run_id)
        selected_limit = max_items or (subscription.max_items if subscription else 5)
        digest = self._compose_digest(run, events[:selected_limit])
        self.store.save_digest(digest)
        sources = self.store.list_run_sources(run.id)
        completed = run.model_copy(update={
            "status": "completed" if sources else "partial",
            "source_count": len(sources),
            "event_count": len(events),
            "selected_count": min(len(events), selected_limit),
            "digest_id": digest.id,
            "completed_at": datetime.now(UTC),
        })
        self.store.update_run(completed)
        if subscription is not None:
            self.store.upsert_subscription(subscription.model_copy(update={
                "last_window_end": run.window_end,
                "updated_at": datetime.now(UTC),
            }))
        return completed

    def verify_digest(self, run_id: str) -> IntelligenceDigest | None:
        run = self.store.get_run(run_id)
        if run is None or not run.digest_id:
            return None
        digest = self.store.get_digest(run.digest_id)
        if digest is None:
            return None
        verified_items: list[IntelligenceDigestItem] = []
        for item in digest.items:
            if not item.source_urls:
                continue
            verified_items.append(item)
        if len(verified_items) != len(digest.items):
            digest = digest.model_copy(update={
                "items": verified_items,
                "no_major_update": not verified_items,
                "executive_summary": (
                    digest.executive_summary
                    if verified_items else "本次时间窗口内未发现有来源支撑的重大更新。"
                ),
            })
            self.store.save_digest(digest)
        return digest

    def prepare_run(
        self,
        *,
        user_id: str,
        topic: str,
        instructions: str = "",
        max_items: int = 5,
        lookback_hours: int = 24,
        budget: ResearchBudget | None = None,
    ) -> ResearchRun:
        end = datetime.now(UTC)
        run = ResearchRun(
            user_id=user_id,
            topic=topic,
            instructions=instructions,
            window_start=end - timedelta(hours=lookback_hours),
            window_end=end,
            budget=budget or ResearchBudget(),
        )
        created = self.store.create_run(run)
        self.store.update_run(created.model_copy(update={"status": "running"}))
        return created

    def enqueue_subscription_run(
        self,
        subscription: ResearchSubscription,
        *,
        window_end: datetime | None = None,
        trigger_type: str = "scheduled",
    ) -> ResearchRun:
        run = ResearchRun.for_subscription(
            subscription,
            window_end=window_end or datetime.now(UTC),
            trigger_type="manual" if trigger_type == "manual" else "scheduled",
        )
        created = self.store.create_run(run)
        self.store.enqueue_run(created)
        return created

    def plan_queries(self, run_id: str) -> list[str]:
        run, subscription = self._load_run_context(run_id)
        queries = self._plan_queries(run, subscription)
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "query_plan": queries,
        }))
        return queries

    def collect_sources(self, run_id: str, queries: list[str] | None = None) -> list[ResearchSource]:
        run, subscription = self._load_run_context(run_id)
        query_plan = queries or run.query_plan or self.plan_queries(run_id)
        sources = self._collect(run, subscription, query_plan)
        self.store.replace_run_sources(run.id, sources)
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "query_plan": query_plan,
            "source_count": len(sources),
        }))
        return sources

    def cluster_events(self, run_id: str, sources: list[ResearchSource] | None = None) -> list[ResearchEvent]:
        run, subscription = self._load_run_context(run_id)
        source_items = sources or self.store.list_run_sources(run_id)
        events = self._cluster_sources(run, subscription, source_items)
        self.store.replace_run_events(run.id, events)
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "source_count": len(source_items),
            "event_count": len(events),
        }))
        return events

    def rank_events(
        self,
        run_id: str,
        events: list[ResearchEvent] | None = None,
        *,
        max_items: int | None = None,
    ) -> list[ResearchEvent]:
        run, subscription = self._load_run_context(run_id)
        event_items = events or self.store.list_run_events(run_id)
        selected_limit = max_items or (subscription.max_items if subscription else 5)
        ranked = self._personalize_and_rank(run, subscription, event_items)
        self.store.replace_run_events(run.id, ranked)
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "event_count": len(ranked),
            "selected_count": min(len(ranked), selected_limit),
        }))
        return ranked[:selected_limit]

    def compose_digest(
        self,
        run_id: str,
        events: list[ResearchEvent] | None = None,
        *,
        max_items: int | None = None,
    ) -> ResearchRun:
        run, subscription = self._load_run_context(run_id)
        if events is None:
            events = self.rank_events(run_id, max_items=max_items)
        selected = events[: (max_items or (subscription.max_items if subscription else 5))]
        digest = self._compose_digest(run, selected)
        self.store.save_digest(digest)
        sources = self.store.list_run_sources(run.id)
        completed = run.model_copy(update={
            "status": "completed" if sources else "partial",
            "source_count": len(sources),
            "event_count": len(self.store.list_run_events(run.id)),
            "selected_count": len(selected),
            "digest_id": digest.id,
            "completed_at": datetime.now(UTC),
        })
        self.store.update_run(completed)
        if subscription is not None:
            self.store.upsert_subscription(subscription.model_copy(update={
                "last_window_end": run.window_end,
                "updated_at": datetime.now(UTC),
            }))
        return completed

    def _next_research_decision(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
    ) -> ResearchDecision:
        if not state.query_history:
            for decision in state.decisions:
                if decision.status == "planned":
                    return decision
        for gap in state.evidence_gaps:
            if gap.status != "open":
                continue
            event = next((item for item in events if item.id == gap.event_id), None)
            if gap.type == "no_official_source" and event is not None:
                return ResearchDecision(
                    iteration=state.iteration_count + 1,
                    action="search_web",
                    query=f"{event.title} official announcement",
                    purpose="find official confirmation",
                    event_id=event.id,
                    reason="resolve no_official_source gap",
                )
        for decision in state.decisions:
            if decision.status == "planned":
                return decision
        return ResearchDecision(
            iteration=state.iteration_count + 1,
            action="stop",
            reason="no open research actions remain",
        )

    def _decision_allowed(
        self,
        decision: ResearchDecision,
        state: ResearchState,
    ) -> bool:
        if decision.action != "search_web":
            return True
        normalized = decision.query.strip().lower()
        if not normalized:
            return False
        return normalized not in {query.strip().lower() for query in state.query_history}

    def _execute_research_decision(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        decision: ResearchDecision,
    ) -> list[ResearchSource]:
        if decision.action == "search_web":
            remaining = max(1, min(10, run.budget.max_search_results))
            return self._collect(run, subscription, [decision.query])[:remaining]
        return []

    def _evidence_gaps(self, events: list[ResearchEvent]) -> list[EvidenceGap]:
        gaps: list[EvidenceGap] = []
        for event in events:
            independent_domains = {source.domain for source in event.sources}
            has_official = any(source.source_type == "official" for source in event.sources)
            if len(independent_domains) <= 1:
                gaps.append(EvidenceGap(
                    event_id=event.id,
                    type="single_source",
                    severity=0.7,
                    suggested_action="find independent source",
                    status="open" if event.status == "uncertain" else "accepted",
                ))
            if not has_official:
                gaps.append(EvidenceGap(
                    event_id=event.id,
                    type="no_official_source",
                    severity=0.6,
                    suggested_action="search official announcement",
                    status="open" if event.status != "verified" else "resolved",
                ))
            if event.personal_relevance.score <= 0:
                gaps.append(EvidenceGap(
                    event_id=event.id,
                    type="missing_personal_context",
                    severity=0.3,
                    suggested_action="search personal graph",
                    status="accepted",
                ))
        return gaps

    def _should_stop_loop(self, state: ResearchState, events: list[ResearchEvent]) -> bool:
        if state.low_yield_rounds >= 2:
            state.stop_reason = "two consecutive low-yield rounds"
            return True
        verified = [event for event in events if event.status in {"verified", "reported"}]
        if len(verified) >= 3:
            state.stop_reason = "enough supported events found"
            return True
        if state.iteration_count >= state.budget.max_queries:
            state.stop_reason = "query budget exhausted"
            return True
        return False

    def _load_run_context(
        self, run_id: str
    ) -> tuple[ResearchRun, ResearchSubscription | None]:
        run = self.store.get_run(run_id)
        if run is None:
            raise ValueError(f"Research run not found: {run_id}")
        subscription = (
            self.store.get_subscription(run.subscription_id)
            if run.subscription_id else None
        )
        return run, subscription

    def deliver_run(self, run_id: str) -> bool:
        run = self.store.get_run(run_id)
        if run is None or not run.digest_id or not run.subscription_id:
            return False
        subscription = self.store.get_subscription(run.subscription_id)
        digest = self.store.get_digest(run.digest_id)
        if subscription is None or digest is None or not subscription.delivery.target_id:
            return False
        if self.delivery_router is None:
            raise RuntimeError("Research delivery router is not configured.")
        reserved, delivery_id = self.store.reserve_delivery(digest, subscription)
        if not reserved:
            return True
        from personal_agent.application.review.models import DeliveryMessage, DeliveryTarget
        result = self.delivery_router.send(
            DeliveryTarget(**subscription.delivery.model_dump()),
            DeliveryMessage(
                title=digest.title,
                text=digest.to_text(),
                metadata={"user_id": run.user_id, "research_run_id": run.id},
            ),
        )
        self.store.complete_delivery(
            delivery_id,
            status="sent" if result.ok else "failed",
            provider_message_id=result.provider_message_id,
            error=result.error,
        )
        return bool(result.ok)

    def feedback(self, feedback: ResearchFeedback) -> ResearchFeedback:
        self.store.add_feedback(feedback)
        if feedback.subscription_id:
            subscription = self.store.get_subscription(feedback.subscription_id)
            event = (
                self.store.get_event(feedback.event_id, user_id=feedback.user_id)
                if feedback.event_id else None
            )
            if subscription is not None and event is not None:
                topics = event.topics or [event.title]
                prefs = subscription.content_preferences.model_copy(deep=True)
                if feedback.action == "not_interested":
                    for topic in topics:
                        if topic not in prefs.exclude_topics:
                            prefs.exclude_topics.append(topic)
                elif feedback.action == "useful":
                    for topic in topics:
                        if topic not in prefs.include_topics:
                            prefs.include_topics.append(topic)
                self.update_subscription(subscription.model_copy(update={
                    "content_preferences": prefs,
                }))
        return feedback

    def save_event(self, event_id: str, *, user_id: str):
        event = self.store.get_event(event_id, user_id=user_id)
        if event is None:
            raise ValueError("Research event not found.")
        if self.save_note is None:
            raise RuntimeError("Research note writer is not configured.")
        sources = "\n".join(f"- {source.url}" for source in event.sources)
        return self.save_note(
            text=(
                f"# {event.title}\n\n{event.summary}\n\n"
                f"可信度：{event.status}\n\n来源：\n{sources}"
            ),
            source_type="research",
            source_ref=f"research-event:{event.id}",
            user_id=user_id,
        )

    def _plan_queries(
        self, run: ResearchRun, subscription: ResearchSubscription | None
    ) -> list[str]:
        seeds = list(subscription.seed_queries if subscription else [])
        if not seeds:
            seeds = [
                f"{run.topic} latest news",
                f"{run.topic} official announcement",
                f"{run.topic} open source release",
            ]
        prompt = (
            "为定时情报收集生成搜索查询。只输出 JSON 字符串数组，不超过"
            f"{run.budget.max_queries}条。\n主题：{run.topic}\n要求：{run.instructions}\n"
            f"时间窗口：{run.window_start.isoformat()} 到 {run.window_end.isoformat()}\n"
            f"初始查询：{json.dumps(seeds, ensure_ascii=False)}"
        )
        if self.generate_text is not None:
            raw = self.generate_text(prompt, "research_query_plan")
            try:
                parsed = json.loads(raw or "")
                if isinstance(parsed, list):
                    seeds = [str(item).strip() for item in parsed if str(item).strip()]
            except json.JSONDecodeError:
                pass
        unique = list(dict.fromkeys(seeds))
        return unique[: run.budget.max_queries]

    def _collect(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        queries: list[str],
    ) -> list[ResearchSource]:
        sources: list[ResearchSource] = []
        seen: set[str] = set()
        remaining = run.budget.max_search_results
        for query in queries:
            if remaining <= 0:
                break
            outcome = self.tools.invoke_direct(
                "web_search",
                query=query,
                limit=min(10, remaining),
                scrape=False,
                user_id=run.user_id,
                run_id=run.id,
            )
            if not outcome.get("ok"):
                continue
            results = (outcome.get("data") or {}).get("results", [])
            for raw in results:
                url = str(raw.get("url") or "").strip()
                if not url:
                    continue
                canonical = canonicalize_url(url)
                if canonical in seen:
                    continue
                domain = urlsplit(canonical).hostname or ""
                if subscription and domain in subscription.source_preferences.excluded_domains:
                    continue
                source = ResearchSource(
                    url=url,
                    canonical_url=canonical,
                    domain=domain,
                    title=str(raw.get("title") or url),
                    snippet=str(raw.get("snippet") or raw.get("content") or ""),
                    published_at=_parse_datetime(raw.get("published_at")),
                    source_type=_source_type(domain, str(raw.get("title") or "")),
                    provider=str(raw.get("source") or ""),
                )
                source.content_fingerprint = _fingerprint(source.title + "\n" + source.snippet)
                sources.append(source)
                seen.add(canonical)
                remaining -= 1
                if remaining <= 0:
                    break
        fetches = 0
        for source in sorted(sources, key=_source_priority, reverse=True):
            if fetches >= run.budget.max_fulltext_fetches:
                break
            if "capture_url" not in self.tools:
                break
            outcome = self.tools.invoke_direct(
                "capture_url",
                url=source.url,
                user_id=run.user_id,
                run_id=run.id,
            )
            if outcome.get("ok"):
                source.content = str((outcome.get("data") or {}).get("text") or "")[:12000]
                if source.content:
                    source.content_fingerprint = _fingerprint(source.content)
                    fetches += 1
        return sources

    def _cluster_sources(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        sources: list[ResearchSource],
    ) -> list[ResearchEvent]:
        frames = self.event_extractor.extract(
            sources,
            topic=run.topic,
            instructions=run.instructions,
        )
        clusters: list[list[ResearchSource]] = []
        cluster_frames: list[object] = []
        for source in sources:
            frame = frames.get(source.canonical_url)
            target = next(
                (
                    index for index, cluster in enumerate(clusters)
                    if frame is not None
                    and cluster_frames[index] is not None
                    and frames_describe_same_event(frame, cluster_frames[index])
                ),
                None,
            )
            if target is None:
                clusters.append([source])
                cluster_frames.append(frame)
            else:
                clusters[target].append(source)
        events: list[ResearchEvent] = []
        previous_keys = self.store.list_recent_event_keys(run.user_id, run.window_start)
        for index, cluster in enumerate(clusters):
            primary = max(cluster, key=_source_priority)
            frame = cluster_frames[index]
            key = _fingerprint(_event_key_material(frame, primary))
            independent_domains = {item.domain for item in cluster}
            official = any(item.source_type == "official" for item in cluster)
            if official and len(independent_domains) >= 2:
                status, confidence = "verified", 0.9
            elif len(independent_domains) >= 2:
                status, confidence = "reported", 0.7
            else:
                status, confidence = "uncertain", 0.4
            novelty = 0.2 if key in previous_keys else 0.9
            summary = primary.content[:800] or primary.snippet[:800]
            events.append(ResearchEvent(
                canonical_key=key,
                title=primary.title,
                summary=summary,
                occurred_at=primary.published_at,
                topics=[run.topic],
                sources=cluster,
                importance_score=_importance(primary, subscription),
                novelty_score=novelty,
                confidence_score=confidence,
                status=status,
            ))
        return events

    def _personalize_and_rank(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        events: list[ResearchEvent],
    ) -> list[ResearchEvent]:
        for event in events:
            relevance = PersonalRelevance()
            outcome = self.tools.invoke_direct(
                "graph_search",
                question=event.title,
                user_id=run.user_id,
                run_id=run.id,
            )
            if outcome.get("ok"):
                data = outcome.get("data") or {}
                matches = (
                    data.get("relation_facts")
                    or data.get("fact_refs")
                    or data.get("node_refs")
                    or []
                )
                if matches:
                    relevance = PersonalRelevance(
                        score=min(1.0, 0.45 + len(matches) * 0.15),
                        related_note_ids=[
                            str(item.get("note_id") or item.get("id"))
                            for item in matches if isinstance(item, dict)
                        ],
                        relation="update",
                        explanation="与你已有的相关知识存在直接关联，建议关注其新增或变化部分。",
                    )
            event.personal_relevance = relevance
            novelty_w = (
                subscription.content_preferences.novelty_weight if subscription else 0.3
            )
            relevance_w = (
                subscription.content_preferences.personal_relevance_weight
                if subscription else 0.3
            )
            event.final_score = (
                event.importance_score * 0.25
                + event.confidence_score * 0.15
                + event.novelty_score * novelty_w
                + relevance.score * relevance_w
            )
        minimum = (
            subscription.content_preferences.minimum_importance if subscription else 0
        )
        return sorted(
            [event for event in events if event.importance_score >= minimum],
            key=lambda item: item.final_score,
            reverse=True,
        )

    def _compose_digest(
        self, run: ResearchRun, events: list[ResearchEvent]
    ) -> IntelligenceDigest:
        items = [
            IntelligenceDigestItem(
                short_id=f"N{index}",
                event_id=event.id,
                title=event.title,
                what_happened=event.summary[:500] or "来源仅提供标题，尚无足够正文。",
                why_it_matters=_why_it_matters(event),
                personal_relevance=event.personal_relevance.explanation,
                confidence_label={
                    "verified": "已验证",
                    "reported": "多方报道",
                    "uncertain": "信息不足",
                    "conflicted": "来源冲突",
                }[event.status],
                source_urls=[source.url for source in event.sources],
            )
            for index, event in enumerate(events, 1)
        ]
        title = f"{run.topic} 情报简报 · {run.window_end.date().isoformat()}"
        summary = (
            f"本次收集筛选出 {len(items)} 条值得关注的更新。"
            if items else "本次时间窗口内未发现达到阈值的重大更新。"
        )
        return IntelligenceDigest(
            run_id=run.id,
            user_id=run.user_id,
            title=title,
            executive_summary=summary,
            items=items,
            no_major_update=not items,
        )


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode([
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    ])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _merge_sources(
    existing: list[ResearchSource],
    incoming: list[ResearchSource],
) -> list[ResearchSource]:
    merged: list[ResearchSource] = []
    seen: set[str] = set()
    for source in [*existing, *incoming]:
        key = source.canonical_url
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)
    return merged


def _query_purpose(query: str) -> str:
    lowered = query.lower()
    if "official" in lowered:
        return "find primary-source confirmation"
    if "open source" in lowered or "github" in lowered:
        return "find implementation or release evidence"
    return "find recent public reports"


def _tokens(text: str) -> set[str]:
    return {
        normalized
        for token in _TOKEN_RE.findall(text)
        if (normalized := _normalize_event_token(token))
    }


def _normalize_event_token(token: str) -> str:
    lowered = token.lower()
    if len(lowered) <= 1 or lowered in _EVENT_STOPWORDS:
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


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0


def _event_key_material(frame, fallback: ResearchSource) -> str:
    if frame is None:
        return " ".join(sorted(_tokens(fallback.title)))
    parts = [
        getattr(frame, "actor", ""),
        getattr(frame, "action", ""),
        getattr(frame, "object", ""),
        getattr(frame, "event_type", ""),
    ]
    material = " ".join(sorted(_tokens(" ".join(parts))))
    return material or " ".join(sorted(_tokens(fallback.title)))


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:32]


def _parse_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _source_type(domain: str, title: str) -> str:
    lowered = f"{domain} {title}".lower()
    if any(token in lowered for token in ("github.com", "official", "openai.com", "anthropic.com", "deepmind.google")):
        return "official"
    if any(token in lowered for token in ("arxiv.org", "paper", "proceedings")):
        return "paper"
    if any(token in lowered for token in ("twitter.com", "x.com", "weibo")):
        return "social"
    return "media"


def _source_priority(source: ResearchSource) -> float:
    base = {"official": 1.0, "paper": 0.9, "media": 0.7, "blog": 0.5, "social": 0.3, "unknown": 0.2}
    return base[source.source_type] + (0.1 if source.content else 0)


def _importance(source: ResearchSource, subscription: ResearchSubscription | None) -> float:
    text = f"{source.title} {source.snippet}".lower()
    score = 0.45
    if source.source_type in {"official", "paper"}:
        score += 0.2
    if any(token in text for token in ("release", "launch", "发布", "开源", "model", "模型", "policy", "安全")):
        score += 0.2
    if subscription:
        if any(token.lower() in text for token in subscription.content_preferences.exclude_topics):
            score -= 0.5
        if any(token.lower() in text for token in subscription.content_preferences.include_topics):
            score += 0.15
    return max(0, min(1, score))


def _why_it_matters(event: ResearchEvent) -> str:
    if event.status == "verified":
        return "该事件有一手或多个独立来源支持，且具有较高新颖性或个人相关性。"
    if event.status == "reported":
        return "多个来源正在报道该变化，值得继续关注后续官方确认与实际影响。"
    return "目前证据有限，暂不宜作为确定事实，但可能值得后续追踪。"
