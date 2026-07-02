from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from personal_agent.application.research.models import (
    DigestClaim,
    EventScoreBreakdown,
    IntelligenceDigest,
    IntelligenceDigestItem,
    EvidenceGap,
    PersonalRelevance,
    ResearchBudget,
    ResearchDecision,
    ResearchEvent,
    ResearchEventFrameSnapshot,
    ResearchFeedback,
    ResearchPolicy,
    ResearchQuery,
    ResearchRun,
    ResearchSatisfaction,
    ResearchStageTiming,
    ResearchSource,
    ResearchState,
    ResearchSubscription,
    ResearchToolCallTrace,
)
from personal_agent.application.research.extraction import (
    HeuristicResearchEventExtractor,
    ResearchEventExtractor,
    frames_describe_same_event,
)
from personal_agent.application.evidence_engine import EvidenceEngine
from personal_agent.kernel.llm_schemas import strip_json_fence

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


@dataclass(frozen=True)
class ResearchRequestUnderstanding:
    topic: str
    instructions: str
    max_items: int
    window_start: datetime
    window_end: datetime
    policy: ResearchPolicy = field(default_factory=ResearchPolicy)
    queries: list[ResearchQuery] = field(default_factory=list)


class ResearchPolicyResolver:
    _DEFAULTS = {
        "technical_product_update": {
            "source_preference": ["official", "docs", "github", "paper", "media"],
            "evidence_requirement": "official_or_multi_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "medium_high",
        },
        "academic_research": {
            "source_preference": ["paper", "github", "official", "docs", "media"],
            "evidence_requirement": "paper_or_primary_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "high",
        },
        "company_financials": {
            "source_preference": ["filing", "investor_relations", "transcript", "media"],
            "evidence_requirement": "primary_financial_source_required",
            "ranking_objective": "confidence_first",
            "verification_strictness": "high",
        },
        "general_news": {
            "source_preference": ["official", "paper", "media"],
            "evidence_requirement": "official_or_multi_source",
            "ranking_objective": "confidence_first",
            "verification_strictness": "medium_high",
        },
    }

    @classmethod
    def resolve(cls, raw_policy: object, *, topic: str, instructions: str) -> ResearchPolicy:
        raw = raw_policy if isinstance(raw_policy, dict) else {}
        inferred_type = str(raw.get("research_type") or "").strip()
        heuristic_type = cls._infer_type(topic, instructions)
        if inferred_type not in cls._DEFAULTS:
            inferred_type = cls._infer_type(topic, instructions)
        elif inferred_type == "general_news" and heuristic_type != "general_news":
            inferred_type = heuristic_type
        data = {"research_type": inferred_type, **cls._DEFAULTS[inferred_type]}
        if not raw.get("ranking_objective") and any(
            token in f"{topic} {instructions}".lower()
            for token in ("personal", "个人", "知识库", "相关")
        ):
            data["ranking_objective"] = "personal_relevance_first"
        for key in (
            "evidence_requirement",
            "ranking_objective",
            "verification_strictness",
        ):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                data[key] = value.strip()
        preferences = raw.get("source_preference")
        if isinstance(preferences, list):
            data["source_preference"] = [
                str(item).strip()
                for item in preferences
                if str(item).strip()
            ] or data["source_preference"]
        try:
            return ResearchPolicy.model_validate(cls._enforce_type_requirements(data))
        except Exception:
            return ResearchPolicy.model_validate({
                "research_type": inferred_type,
                **cls._DEFAULTS[inferred_type],
            })

    @classmethod
    def _enforce_type_requirements(cls, data: dict[str, object]) -> dict[str, object]:
        research_type = str(data.get("research_type") or "general_news")
        if research_type == "company_financials":
            data["evidence_requirement"] = "primary_financial_source_required"
        elif research_type == "academic_research":
            data["evidence_requirement"] = "paper_or_primary_source"
        return data

    @classmethod
    def _infer_type(cls, topic: str, instructions: str) -> str:
        text = f"{topic} {instructions}".lower()
        if any(token in text for token in ("earnings", "10-k", "10-q", "sec", "财报", "营收", "财务")):
            return "company_financials"
        if any(token in text for token in ("paper", "arxiv", "论文", "学术", "research paper")):
            return "academic_research"
        if any(token in text for token in ("sdk", "api", "github", "release", "runtime", "开源", "发布")):
            return "technical_product_update"
        return "general_news"


class QueryPlanner:
    _FALLBACKS = {
        "technical_product_update": [
            ("latest", "{topic} latest news", 0.96),
            ("official", "{topic} official announcement", 0.9),
            ("docs", "{topic} documentation release notes", 0.86),
            ("repo", "{topic} GitHub release", 0.82),
            ("technical", "{topic} technical report", 0.72),
        ],
        "academic_research": [
            ("paper", "{topic} paper arXiv", 0.95),
            ("repo", "{topic} GitHub code", 0.7),
            ("media", "{topic} latest research news", 0.45),
        ],
        "company_financials": [
            ("financial_filing", "{topic} SEC filing 10-Q 10-K", 0.95),
            ("transcript", "{topic} earnings call transcript", 0.82),
            ("official", "{topic} investor relations earnings release", 0.8),
            ("media", "{topic} financial results news", 0.45),
        ],
        "general_news": [
            ("latest", "{topic} latest news", 0.8),
            ("official", "{topic} official announcement", 0.7),
            ("media", "{topic} independent coverage", 0.45),
        ],
    }

    @classmethod
    def build(
        cls,
        *,
        topic: str,
        policy: ResearchPolicy,
        raw_queries: object,
        seed_queries: list[str],
        max_queries: int,
    ) -> list[ResearchQuery]:
        unique: dict[str, ResearchQuery] = {}
        for candidate in cls._parse_raw_queries(raw_queries):
            cls._add_query(unique, candidate, replace_with_higher_priority=True)
        for index, query in enumerate(seed_queries):
            cls._add_query(
                unique,
                ResearchQuery(query=query, intent="latest", priority=max(0.2, 0.6 - index * 0.05)),
                replace_with_higher_priority=False,
            )
        for intent, template, priority in cls._FALLBACKS.get(policy.research_type, cls._FALLBACKS["general_news"]):
            cls._add_query(
                unique,
                ResearchQuery(
                    query=template.format(topic=topic),
                    intent=intent,
                    priority=priority,
                ),
                replace_with_higher_priority=False,
            )
        return sorted(unique.values(), key=lambda item: item.priority, reverse=True)[:max_queries]

    @staticmethod
    def _add_query(
        unique: dict[str, ResearchQuery],
        candidate: ResearchQuery,
        *,
        replace_with_higher_priority: bool,
    ) -> None:
        query = " ".join(candidate.query.split())
        if not query:
            return
        key = query.lower()
        current = unique.get(key)
        normalized = candidate.model_copy(update={"query": query})
        if current is None or (
            replace_with_higher_priority and normalized.priority > current.priority
        ):
            unique[key] = normalized

    @staticmethod
    def _parse_raw_queries(raw_queries: object) -> list[ResearchQuery]:
        if not isinstance(raw_queries, list):
            return []
        parsed: list[ResearchQuery] = []
        for item in raw_queries:
            if isinstance(item, str):
                query = item.strip()
                if query:
                    parsed.append(ResearchQuery(query=query, intent=_query_intent(query), priority=0.7))
            elif isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                if not query:
                    continue
                try:
                    parsed.append(ResearchQuery.model_validate({
                        "query": query,
                        "intent": item.get("intent") or _query_intent(query),
                        "priority": item.get("priority", 0.7),
                    }))
                except Exception:
                    parsed.append(ResearchQuery(query=query, intent=_query_intent(query), priority=0.7))
        return parsed


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
        default_budget: ResearchBudget | None = None,
    ) -> None:
        self.store = store
        self.tools = tool_executor
        self.generate_text = generate_text
        self.save_note = save_note
        self.event_extractor = event_extractor or HeuristicResearchEventExtractor()
        self.default_budget = default_budget or ResearchBudget()
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
        understanding = self._understand_research_request(run, subscription)
        run = run.model_copy(update={
            "topic": understanding.topic,
            "instructions": understanding.instructions,
            "max_items": understanding.max_items,
            "window_start": understanding.window_start,
            "window_end": understanding.window_end,
            "policy": understanding.policy,
            "query_plan_details": understanding.queries,
            "query_plan": [query.query for query in understanding.queries],
        })
        queries = understanding.queries
        decisions = [
            ResearchDecision(
                iteration=index,
                action="search_web",
                query=query.query,
                purpose=query.intent,
                reason=f"initial {understanding.policy.research_type} policy query",
                query_phase="exploration",
            )
            for index, query in enumerate(queries, 1)
        ]
        state = ResearchState(
            run_id=run.id,
            topic=run.topic,
            instructions=run.instructions,
            max_items=run.max_items,
            window_start=run.window_start,
            window_end=run.window_end,
            budget=run.budget,
            decisions=decisions,
            policy=understanding.policy,
            query_plan=queries,
        )
        self.store.update_run(run.model_copy(update={
            "status": "running",
            "query_plan": [query.query for query in queries],
            "query_plan_details": queries,
            "policy": understanding.policy,
            "research_state": state,
            "topic": run.topic,
            "instructions": run.instructions,
            "max_items": run.max_items,
            "window_start": run.window_start,
            "window_end": run.window_end,
        }))
        return state

    def run_research_loop(self, run_id: str) -> ResearchState:
        run, subscription = self._load_run_context(run_id)
        if run.research_state is None:
            state = self.initialize_state(run_id)
            run, subscription = self._load_run_context(run_id)
        else:
            state = run.research_state
        sources = self.store.list_run_sources(run.id)
        events = self.store.list_run_events(run.id)

        while not state.stop_reason:
            if state.iteration_count >= state.budget.max_queries:
                state.stop_reason = "query budget exhausted"
                break
            stage_start = _timer_start()
            decision = self._next_research_decision(state, events)
            _record_stage_timing(
                state,
                "next_research_decision",
                stage_start,
                decision_id=decision.id,
            )
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
            if decision.query_phase == "verification":
                state.verification_query_count += 1
            else:
                state.exploration_query_count += 1
            decision_started = datetime.now(UTC)
            decision_timer = _timer_start()
            decision.started_at = decision_started
            new_sources = self._execute_research_decision(run, subscription, decision, state)
            decision.completed_at = datetime.now(UTC)
            decision.elapsed_ms = _elapsed_ms(decision_timer)
            _record_stage_timing(
                state,
                "execute_research_decision",
                decision_timer,
                decision_id=decision.id,
                item_count=len(new_sources),
            )
            decision.status = "executed"
            decision.result_count = len(new_sources)
            state.query_history.append(decision.query)
            if decision not in state.decisions:
                state.decisions.append(decision)
            state.low_yield_rounds = state.low_yield_rounds + 1 if not new_sources else 0

            stage_start = _timer_start()
            sources = _merge_sources(sources, new_sources)
            self.store.replace_run_sources(run.id, sources)
            _record_stage_timing(
                state,
                "merge_and_store_sources",
                stage_start,
                decision_id=decision.id,
                item_count=len(sources),
            )
            stage_start = _timer_start()
            events = self._cluster_sources(run, subscription, sources)
            _record_stage_timing(
                state,
                "cluster_sources",
                stage_start,
                decision_id=decision.id,
                item_count=len(events),
            )
            stage_start = _timer_start()
            events = self._personalize_and_rank(run, subscription, events, state)
            _record_stage_timing(
                state,
                "personalize_and_rank",
                stage_start,
                decision_id=decision.id,
                item_count=len(events),
            )
            stage_start = _timer_start()
            self.store.replace_run_events(run.id, events)
            state.evidence_gaps = self._evidence_gaps(events, state.policy)
            _record_stage_timing(
                state,
                "store_events_and_detect_gaps",
                stage_start,
                decision_id=decision.id,
                item_count=len(state.evidence_gaps),
            )

            run = run.model_copy(update={
                "status": "running",
                "source_count": len(sources),
                "event_count": len(events),
                "selected_count": min(len(events), subscription.max_items if subscription else run.max_items),
                "research_state": state,
            })
            self.store.update_run(run)
            stage_start = _timer_start()
            if self._should_stop_loop(state, events):
                _record_stage_timing(
                    state,
                    "evaluate_research_satisfaction",
                    stage_start,
                    decision_id=decision.id,
                )
                break
            _record_stage_timing(
                state,
                "evaluate_research_satisfaction",
                stage_start,
                decision_id=decision.id,
            )

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
        selected_limit = max_items or (subscription.max_items if subscription else run.max_items)
        digest = self._compose_digest(run, events[:selected_limit])
        self.store.save_digest(digest)
        sources = self.store.list_run_sources(run.id)
        completed = run.model_copy(update={
            "status": "completed_with_limitations" if sources else "partial_no_supported_claims",
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
        events_by_id = {
            event.id: event for event in self.store.list_run_events(run_id)
        }
        verified_items: list[IntelligenceDigestItem] = []
        for item in digest.items:
            if not item.source_urls:
                continue
            event = events_by_id.get(item.event_id)
            if event is None:
                continue
            checked = _verify_digest_item_claims(item, event)
            if _digest_item_has_supported_fact(checked):
                verified_items.append(checked)
        if verified_items != digest.items:
            digest = digest.model_copy(update={
                "items": verified_items,
                "no_major_update": not verified_items,
                "executive_summary": (
                    digest.executive_summary
                    if verified_items else "本次时间窗口内未发现有来源支撑的重大更新。"
                ),
            })
            self.store.save_digest(digest)
        self.store.update_run(run.model_copy(update={
            "status": _verified_run_status(run, digest),
            "selected_count": len(digest.items),
            "completed_at": datetime.now(UTC),
        }))
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
            max_items=max_items,
            window_start=end - timedelta(hours=lookback_hours),
            window_end=end,
            budget=budget or self.default_budget.model_copy(deep=True),
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
        understanding = self._understand_research_request(run, subscription)
        updated = run.model_copy(update={
            "topic": understanding.topic,
            "instructions": understanding.instructions,
            "max_items": understanding.max_items,
            "window_start": understanding.window_start,
            "window_end": understanding.window_end,
            "status": "running",
            "policy": understanding.policy,
            "query_plan": [query.query for query in understanding.queries],
            "query_plan_details": understanding.queries,
        })
        self.store.update_run(updated)
        return [query.query for query in understanding.queries]

    def collect_sources(self, run_id: str, queries: list[str] | None = None) -> list[ResearchSource]:
        run, subscription = self._load_run_context(run_id)
        query_plan = queries or run.query_plan
        if not query_plan:
            query_plan = self.plan_queries(run_id)
            run, subscription = self._load_run_context(run_id)
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
        selected_limit = max_items or (subscription.max_items if subscription else run.max_items)
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
        selected = events[: (max_items or (subscription.max_items if subscription else run.max_items))]
        digest = self._compose_digest(run, selected)
        self.store.save_digest(digest)
        sources = self.store.list_run_sources(run.id)
        completed = run.model_copy(update={
            "status": "completed_with_limitations" if sources else "partial_no_supported_claims",
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
                if decision.status == "planned" and self._decision_allowed(decision, state):
                    return decision
        raw_gap_decisions = self._gap_research_decisions(state, events)
        policy_decision = self._select_research_policy_decision(
            state,
            events,
            raw_gap_decisions,
        )
        if policy_decision is not None:
            return policy_decision
        gap_decisions = [
            decision for decision in raw_gap_decisions
            if self._decision_allowed(decision, state)
        ]
        if gap_decisions:
            if self._should_use_gap_selector(state, gap_decisions):
                return self._select_gap_research_decision(
                    state,
                    events,
                    gap_decisions,
                ) or gap_decisions[0]
            return gap_decisions[0]
        for decision in state.decisions:
            if decision.status == "planned" and self._decision_allowed(decision, state):
                return decision
        return ResearchDecision(
            iteration=state.iteration_count + 1,
            action="stop",
            reason="no open research actions remain",
        )

    def _gap_research_decisions(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
    ) -> list[ResearchDecision]:
        by_event_id = {event.id: event for event in events}
        decisions: list[ResearchDecision] = []
        for gap in sorted(
            (gap for gap in state.evidence_gaps if gap.status == "open"),
            key=lambda item: (_gap_action_priority(item), -item.severity),
        ):
            event = by_event_id.get(gap.event_id or "")
            if event is None:
                continue
            if gap.type == "missing_primary_source":
                for query in _gap_queries(event.title, state.policy):
                    decisions.append(ResearchDecision(
                        iteration=state.iteration_count + 1,
                        action="search_web",
                        query=query,
                        purpose=_primary_source_action(state.policy),
                        event_id=event.id,
                        gap_id=gap.id,
                        reason="resolve missing_primary_source gap",
                        query_phase="verification",
                    ))
            elif gap.type == "single_source":
                decisions.append(ResearchDecision(
                    iteration=state.iteration_count + 1,
                    action="search_web",
                    query=f"{event.title} independent coverage",
                    purpose="find independent source",
                    event_id=event.id,
                    gap_id=gap.id,
                    reason="resolve single_source gap",
                    query_phase="verification",
                ))
        return decisions

    def _select_research_policy_decision(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
        suggested_actions: list[ResearchDecision],
    ) -> ResearchDecision | None:
        if self.generate_text is None or not events:
            return None
        event_ids = {event.id for event in events}
        open_gaps = [
            {
                "type": gap.type,
                "severity": gap.severity,
                "suggested_action": gap.suggested_action,
                "event_id": gap.event_id,
            }
            for gap in state.evidence_gaps
            if gap.status == "open"
        ]
        action_hints = [
            {
                "action": decision.action,
                "query": decision.query,
                "purpose": decision.purpose,
                "event_id": decision.event_id,
                "reason": decision.reason,
            }
            for decision in suggested_actions
            if self._decision_allowed(decision, state)
        ]
        event_payload = [
            {
                "id": event.id,
                "title": event.title,
                "status": event.status,
                "source_count": len(event.sources),
                "source_types": [source.source_type for source in event.sources],
                "domains": [source.domain for source in event.sources],
                "confidence_score": event.confidence_score,
                "personal_relevance": event.personal_relevance.score,
                "final_score": event.final_score,
            }
            for event in events[:10]
        ]
        prompt = (
            "你是 research agent 的下一步策略决策器。你可以自己提出更有信息增益的 "
            "search_web query，也可以在证据已经足够或预算不值得继续消耗时 stop。"
            "只能输出 JSON，不能输出解释性正文。\n"
            "允许 action：search_web, stop。\n"
            "JSON schema：{\"action\":\"search_web|stop\",\"query\":\"...\","
            "\"purpose\":\"...\",\"event_id\":\"...\",\"expected_gain\":\"official_confirmation|"
            "independent_source|disambiguation|personal_relevance|recency|stop\","
            "\"cost_level\":\"low|medium|high\",\"reason\":\"...\"}。\n"
            "约束：search_web 的 query 必须具体、不能重复已执行查询；event_id 必须来自事件列表或为空；"
            "不要为了补低价值信息消耗预算。\n"
            f"主题：{state.topic}\n要求：{state.instructions}\n"
            f"研究策略：{json.dumps(state.policy.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"初始查询计划：{json.dumps([query.model_dump(mode='json') for query in state.query_plan], ensure_ascii=False)}\n"
            f"已执行查询：{json.dumps(state.query_history, ensure_ascii=False)}\n"
            f"剩余查询预算：{max(0, state.budget.max_queries - state.iteration_count)}\n"
            f"剩余探索查询预算：{max(0, state.budget.max_exploration_queries - state.exploration_query_count)}\n"
            f"剩余验证查询预算：{max(0, state.budget.max_verification_queries - state.verification_query_count)}\n"
            f"剩余工具预算：{max(0, state.budget.max_tool_calls - state.tool_call_count)}\n"
            f"事件：{json.dumps(event_payload, ensure_ascii=False)}\n"
            f"证据缺口：{json.dumps(open_gaps, ensure_ascii=False)}\n"
            f"可参考动作：{json.dumps(action_hints, ensure_ascii=False)}"
        )
        raw = self.generate_text(prompt, "research_policy_decision")
        parsed = _parse_llm_json_object(raw)
        if parsed is None:
            return None
        if not isinstance(parsed, dict):
            return None
        action = str(parsed.get("action") or "").strip()
        reason = str(parsed.get("reason") or "").strip()
        if action == "stop":
            return ResearchDecision(
                iteration=state.iteration_count + 1,
                action="stop",
                reason=reason or "research policy selected stop",
            )
        if action != "search_web":
            return None
        query = " ".join(str(parsed.get("query") or "").split())
        if not query or len(query) > 240:
            return None
        event_id = str(parsed.get("event_id") or "").strip() or None
        if event_id is not None and event_id not in event_ids:
            return None
        decision = ResearchDecision(
            iteration=state.iteration_count + 1,
            action="search_web",
            query=query,
            purpose=str(parsed.get("purpose") or parsed.get("expected_gain") or "policy-directed search"),
            event_id=event_id,
            reason=reason or "research policy selected search_web",
            query_phase=_policy_query_phase(str(parsed.get("expected_gain") or parsed.get("purpose") or "")),
        )
        if not self._decision_allowed(decision, state):
            return None
        return decision

    def _should_use_gap_selector(
        self,
        state: ResearchState,
        candidates: list[ResearchDecision],
    ) -> bool:
        if self.generate_text is None or len(candidates) < 3:
            return False
        if state.verification_query_count >= state.budget.max_verification_queries:
            return False
        return state.policy.verification_strictness == "high"

    def _select_gap_research_decision(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
        candidates: list[ResearchDecision],
    ) -> ResearchDecision | None:
        if self.generate_text is None or len(candidates) <= 1:
            return None
        candidate_payload = [
            {
                "id": f"candidate_{index}",
                "action": candidate.action,
                "query": candidate.query,
                "purpose": candidate.purpose,
                "event_id": candidate.event_id,
                "reason": candidate.reason,
            }
            for index, candidate in enumerate(candidates)
        ]
        event_payload = [
            {
                "id": event.id,
                "title": event.title,
                "status": event.status,
                "source_count": len(event.sources),
                "source_types": [source.source_type for source in event.sources],
                "confidence_score": event.confidence_score,
                "personal_relevance": event.personal_relevance.score,
            }
            for event in events[:10]
        ]
        prompt = (
            "你是研究循环的下一步动作选择器。只能从候选 candidates 中选择一个，"
            "不能发明新 action 或 query。目标是在有限预算内优先提升事件可信度，"
            "尤其是补齐官方来源或独立来源。若候选都没有价值，选择 stop。\n"
            "只输出 JSON：{\"candidate_id\":\"candidate_0\",\"reason\":\"...\"} "
            "或 {\"candidate_id\":\"stop\",\"reason\":\"...\"}。\n"
            f"主题：{state.topic}\n要求：{state.instructions}\n"
            f"研究策略：{json.dumps(state.policy.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"已执行查询：{json.dumps(state.query_history, ensure_ascii=False)}\n"
            f"剩余查询预算：{max(0, state.budget.max_queries - state.iteration_count)}\n"
            f"剩余验证查询预算：{max(0, state.budget.max_verification_queries - state.verification_query_count)}\n"
            f"事件：{json.dumps(event_payload, ensure_ascii=False)}\n"
            f"候选：{json.dumps(candidate_payload, ensure_ascii=False)}"
        )
        raw = self.generate_text(prompt, "research_next_action")
        parsed = _parse_llm_json_object(raw)
        if parsed is None:
            return None
        if not isinstance(parsed, dict):
            return None
        candidate_id = str(parsed.get("candidate_id") or "").strip()
        if candidate_id == "stop":
            return ResearchDecision(
                iteration=state.iteration_count + 1,
                action="stop",
                reason=str(parsed.get("reason") or "model selected stop"),
            )
        if not candidate_id.startswith("candidate_"):
            return None
        try:
            index = int(candidate_id.removeprefix("candidate_"))
        except ValueError:
            return None
        if index < 0 or index >= len(candidates):
            return None
        selected = candidates[index]
        reason = str(parsed.get("reason") or "").strip()
        if reason:
            selected = selected.model_copy(update={
                "reason": f"{selected.reason}; model: {reason}",
            })
        return selected

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
        if normalized in {query.strip().lower() for query in state.query_history}:
            return False
        if state.iteration_count >= state.budget.max_queries:
            return False
        if (
            decision.query_phase == "exploration"
            and state.exploration_query_count >= state.budget.max_exploration_queries
        ):
            return False
        if (
            decision.query_phase == "verification"
            and state.verification_query_count >= state.budget.max_verification_queries
        ):
            return False
        return True

    def _execute_research_decision(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        decision: ResearchDecision,
        state: ResearchState | None = None,
    ) -> list[ResearchSource]:
        if decision.action == "search_web":
            remaining = max(1, min(10, run.budget.max_search_results))
            return self._collect(run, subscription, [decision.query], state=state, decision=decision)[:remaining]
        return []

    def _evidence_gaps(
        self,
        events: list[ResearchEvent],
        policy: ResearchPolicy | None = None,
    ) -> list[EvidenceGap]:
        resolved = policy or ResearchPolicy()
        gaps: list[EvidenceGap] = []
        for event in events:
            independent_domains = {source.domain for source in event.sources}
            has_primary = _has_required_primary_source(event.sources, resolved)
            if len(independent_domains) <= 1:
                gaps.append(EvidenceGap(
                    event_id=event.id,
                    type="single_source",
                    severity=0.7,
                    suggested_action="find independent source",
                    status="open" if event.status == "uncertain" and not has_primary else "accepted",
                ))
            if not has_primary:
                gaps.append(EvidenceGap(
                    event_id=event.id,
                    type="missing_primary_source",
                    severity=0.6,
                    suggested_action=_primary_source_action(resolved),
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
        satisfaction = self._evaluate_research_satisfaction(state, events)
        state.satisfaction = satisfaction
        if satisfaction.should_continue:
            return False
        state.stop_reason = satisfaction.reason or "research target satisfaction reached"
        return True

    def _evaluate_research_satisfaction(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
    ) -> ResearchSatisfaction:
        fallback = self._default_research_satisfaction(state, events)
        if not self._should_call_satisfaction_model(state, events, fallback):
            return fallback
        gap_payload = [
            {
                "id": gap.id,
                "event_id": gap.event_id,
                "type": gap.type,
                "severity": gap.severity,
                "status": gap.status,
                "suggested_action": gap.suggested_action,
            }
            for gap in state.evidence_gaps
        ]
        event_payload = [
            {
                "id": event.id,
                "title": event.title,
                "status": event.status,
                "source_count": len(event.sources),
                "source_types": [source.source_type for source in event.sources],
                "confidence_score": event.confidence_score,
                "personal_relevance": event.personal_relevance.score,
                "final_score": event.final_score,
            }
            for event in events[:10]
        ]
        prompt = (
            "评估当前 research 是否已经满足用户目标。只输出 JSON，不要输出 Markdown。\n"
            "JSON schema：{\"coverage_score\":0.0,\"confidence_score\":0.0,"
            "\"remaining_critical_gap_ids\":[\"...\"],\"marginal_gain\":0.0,"
            "\"should_continue\":true,\"reason\":\"...\"}。\n"
            "coverage_score 衡量是否已找到足够数量且覆盖主题的候选事件；"
            "confidence_score 衡量来源支撑是否达到用户可信度目标；"
            "marginal_gain 衡量继续搜索预计新增价值；"
            "remaining_critical_gap_ids 只能引用给定 gaps 中仍阻碍目标满足的 gap id。"
            "在预算有限时，如果继续搜索只能低收益重复，应 should_continue=false。\n"
            f"主题：{state.topic}\n要求：{state.instructions}\n目标条数：{state.max_items}\n"
            f"研究策略：{json.dumps(state.policy.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"迭代次数：{state.iteration_count}/{state.budget.max_queries}\n"
            f"探索查询：{state.exploration_query_count}/{state.budget.max_exploration_queries}\n"
            f"验证查询：{state.verification_query_count}/{state.budget.max_verification_queries}\n"
            f"工具调用：{state.tool_call_count}/{state.budget.max_tool_calls}\n"
            f"连续低收益轮次：{state.low_yield_rounds}\n"
            f"已执行查询：{json.dumps(state.query_history, ensure_ascii=False)}\n"
            f"事件：{json.dumps(event_payload, ensure_ascii=False)}\n"
            f"证据缺口：{json.dumps(gap_payload, ensure_ascii=False)}"
        )
        stage_start = _timer_start()
        state.satisfaction_model_call_count += 1
        raw = self.generate_text(prompt, "research_satisfaction")
        _record_stage_timing(
            state,
            "llm_research_satisfaction",
            stage_start,
        )
        parsed = _parse_llm_json_object(raw)
        if parsed is None:
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        gaps_by_id = {gap.id: gap for gap in state.evidence_gaps}
        critical_gap_ids = [
            str(item)
            for item in (parsed.get("remaining_critical_gap_ids") or [])
            if str(item) in gaps_by_id
        ]
        satisfaction = ResearchSatisfaction(
            coverage_score=_coerce_float(
                parsed.get("coverage_score"),
                default=fallback.coverage_score,
            ),
            confidence_score=_coerce_float(
                parsed.get("confidence_score"),
                default=fallback.confidence_score,
            ),
            remaining_critical_gaps=[gaps_by_id[item] for item in critical_gap_ids],
            marginal_gain=_coerce_float(
                parsed.get("marginal_gain"),
                default=fallback.marginal_gain,
            ),
            should_continue=_coerce_bool(
                parsed.get("should_continue"),
                default=fallback.should_continue,
            ),
            reason=str(parsed.get("reason") or fallback.reason),
        )
        if state.iteration_count >= state.budget.max_queries:
            return satisfaction.model_copy(update={
                "should_continue": False,
                "reason": "query budget exhausted",
            })
        if (
            satisfaction.remaining_critical_gaps
            and state.verification_query_count >= state.budget.max_verification_queries
        ):
            return satisfaction.model_copy(update={
                "should_continue": False,
                "reason": "verification query budget exhausted",
            })
        if state.tool_call_count >= state.budget.max_tool_calls:
            return satisfaction.model_copy(update={
                "should_continue": False,
                "reason": "tool budget exhausted",
            })
        return satisfaction

    def _should_call_satisfaction_model(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
        fallback: ResearchSatisfaction,
    ) -> bool:
        if self.generate_text is None or not events:
            return False
        if not fallback.should_continue:
            return False
        if state.satisfaction_model_call_count >= state.budget.max_satisfaction_model_calls:
            return False
        if state.tool_call_count >= state.budget.max_tool_calls:
            return False
        if state.iteration_count >= state.budget.max_queries:
            return False
        if state.low_yield_rounds > 0:
            return True
        if fallback.remaining_critical_gaps:
            return True
        return state.iteration_count >= 2

    def _default_research_satisfaction(
        self,
        state: ResearchState,
        events: list[ResearchEvent],
    ) -> ResearchSatisfaction:
        target_count = max(1, state.max_items)
        selected = events[:target_count]
        supported = [
            event for event in selected
            if _event_satisfies_policy(event, state.policy)
        ]
        coverage_score = min(1.0, len(selected) / target_count)
        confidence_score = (
            sum(event.confidence_score for event in selected) / len(selected)
            if selected else 0.0
        )
        critical_gaps = [
            gap for gap in state.evidence_gaps
            if gap.status == "open"
            and gap.type in {"missing_primary_source", "single_source"}
            and any(event.id == gap.event_id for event in selected)
        ]
        if state.tool_call_count >= state.budget.max_tool_calls:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.0,
                should_continue=False,
                reason="tool budget exhausted",
            )
        if state.iteration_count >= state.budget.max_queries:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.0,
                should_continue=False,
                reason="query budget exhausted",
            )
        if critical_gaps and state.verification_query_count >= state.budget.max_verification_queries:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.0,
                should_continue=False,
                reason="verification query budget exhausted",
            )
        if state.low_yield_rounds >= 2:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.0,
                should_continue=False,
                reason="low-yield marginal gain exhausted",
            )
        if len(supported) >= target_count and not critical_gaps:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=[],
                marginal_gain=0.1,
                should_continue=False,
                reason="research target satisfaction reached",
            )
        if not supported:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.5 if critical_gaps else 0.25,
                should_continue=True,
                reason="supported target events not found yet",
            )
        if len(supported) < target_count:
            return ResearchSatisfaction(
                coverage_score=coverage_score,
                confidence_score=confidence_score,
                remaining_critical_gaps=critical_gaps,
                marginal_gain=0.5 if critical_gaps else 0.25,
                should_continue=True,
                reason="more supported target events needed",
            )
        return ResearchSatisfaction(
            coverage_score=coverage_score,
            confidence_score=confidence_score,
            remaining_critical_gaps=critical_gaps,
            marginal_gain=0.6 if critical_gaps else 0.25,
            should_continue=bool(critical_gaps),
            reason="critical evidence gaps remain" if critical_gaps else "no critical evidence gaps remain",
        )

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

    def _understand_research_request(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
    ) -> ResearchRequestUnderstanding:
        fallback = self._default_research_understanding(run, subscription)
        if self.generate_text is None:
            return fallback
        prompt = (
            "将一次研究请求解析成规范化 research run，并生成初始搜索策略。"
            "只输出 JSON，不要输出 Markdown 或解释。\n"
            "JSON schema：{\"topic\":\"...\",\"instructions\":\"...\","
            "\"max_items\":1,\"lookback_hours\":24,"
            "\"policy\":{\"research_type\":\"technical_product_update|academic_research|company_financials|general_news\","
            "\"source_preference\":[\"official\",\"docs\",\"github\",\"paper\",\"media\"],"
            "\"evidence_requirement\":\"official_or_multi_source|official_required|paper_or_primary_source|primary_financial_source_required|multi_source\","
            "\"ranking_objective\":\"confidence_first|personal_relevance_first|novelty_first|impact_first\","
            "\"verification_strictness\":\"low|medium|medium_high|high\"},"
            "\"query_plan\":[{\"query\":\"...\",\"intent\":\"official|docs|repo|paper|technical|media|latest|financial_filing|transcript\","
            "\"priority\":0.9}]}。\n"
            "要求：topic 只保留研究对象，不要包含“调研/最多几条/高可信”等控制语；"
            "instructions 保留可信度、来源偏好、个人相关性、语言、排除项等约束；"
            "policy 根据研究类型决定证据要求和排序目标；"
            "max_items 取 1 到 20；lookback_hours 取 1 到 720；query_plan 最多使用剩余查询预算，"
            "覆盖 primary source、repo/docs/paper/media 等不同证据角度。"
            "如果用户没有指定某项，使用默认值。\n"
            f"原始 topic/request：{run.topic}\n"
            f"已有 instructions：{run.instructions}\n"
            f"默认 max_items：{run.max_items}\n"
            f"默认时间窗口小时数：{max(1, int((run.window_end - run.window_start).total_seconds() // 3600))}\n"
            f"总查询预算：{run.budget.max_queries}\n"
            f"初始探索查询预算：{run.budget.max_exploration_queries}\n"
            f"证据验证查询预算：{run.budget.max_verification_queries}\n"
            f"订阅 seed queries：{json.dumps(subscription.seed_queries if subscription else [], ensure_ascii=False)}"
        )
        raw = self.generate_text(prompt, "research_request_understanding")
        parsed = _parse_llm_json_object(raw)
        if parsed is None:
            return fallback
        if not isinstance(parsed, dict):
            return fallback
        topic = str(parsed.get("topic") or fallback.topic).strip() or fallback.topic
        instructions = str(parsed.get("instructions") or fallback.instructions).strip()
        max_items = _coerce_int(
            parsed.get("max_items"),
            default=fallback.max_items,
            lower=1,
            upper=20,
        )
        lookback_hours = _coerce_int(
            parsed.get("lookback_hours"),
            default=max(1, int((fallback.window_end - fallback.window_start).total_seconds() // 3600)),
            lower=1,
            upper=720,
        )
        policy = ResearchPolicyResolver.resolve(
            parsed.get("policy"),
            topic=topic,
            instructions=instructions,
        )
        queries = QueryPlanner.build(
            topic=topic,
            policy=policy,
            raw_queries=parsed.get("query_plan", parsed.get("queries")),
            seed_queries=subscription.seed_queries if subscription else [],
            max_queries=min(run.budget.max_queries, run.budget.max_exploration_queries),
        )
        if not queries:
            queries = fallback.queries
        window_end = run.window_end
        return ResearchRequestUnderstanding(
            topic=topic,
            instructions=instructions,
            max_items=max_items,
            window_start=window_end - timedelta(hours=lookback_hours),
            window_end=window_end,
            policy=policy,
            queries=queries,
        )

    def _default_research_understanding(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
    ) -> ResearchRequestUnderstanding:
        policy = ResearchPolicyResolver.resolve(
            {},
            topic=run.topic,
            instructions=run.instructions,
        )
        return ResearchRequestUnderstanding(
            topic=run.topic,
            instructions=run.instructions,
            max_items=subscription.max_items if subscription else run.max_items,
            window_start=run.window_start,
            window_end=run.window_end,
            policy=policy,
            queries=self._plan_queries(run, subscription, policy),
        )

    def _plan_queries(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        policy: ResearchPolicy | None = None,
    ) -> list[ResearchQuery]:
        resolved = policy or ResearchPolicyResolver.resolve(
            run.policy.model_dump(mode="json") if run.policy else {},
            topic=run.topic,
            instructions=run.instructions,
        )
        return QueryPlanner.build(
            topic=run.topic,
            policy=resolved,
            raw_queries=run.query_plan_details or run.query_plan,
            seed_queries=list(subscription.seed_queries if subscription else []),
            max_queries=min(run.budget.max_queries, run.budget.max_exploration_queries),
        )

    def _collect(
        self,
        run: ResearchRun,
        subscription: ResearchSubscription | None,
        queries: list[str],
        *,
        state: ResearchState | None = None,
        decision: ResearchDecision | None = None,
    ) -> list[ResearchSource]:
        sources: list[ResearchSource] = []
        seen: set[str] = set()
        remaining = run.budget.max_search_results
        for query in queries:
            if remaining <= 0:
                break
            outcome = self._invoke_research_tool(
                state,
                "web_search",
                query=query,
                limit=min(10, remaining),
                scrape=False,
                user_id=run.user_id,
                run_id=run.id,
                _trace_decision_id=decision.id if decision is not None else None,
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
                    decision_id=decision.id if decision is not None else None,
                    query=query,
                    query_phase=decision.query_phase if decision is not None else "exploration",
                    url=url,
                    canonical_url=canonical,
                    domain=domain,
                    title=str(raw.get("title") or url),
                    snippet=str(raw.get("snippet") or raw.get("content") or ""),
                    published_at=_parse_datetime(raw.get("published_at")),
                    source_type=_source_type(domain, f"{url} {raw.get('title') or ''}"),
                    provider=str(raw.get("source") or ""),
                )
                source.content_fingerprint = _fingerprint(source.title + "\n" + source.snippet)
                sources.append(source)
                seen.add(canonical)
                remaining -= 1
                if remaining <= 0:
                    break
        fetches = 0
        policy = state.policy if state is not None else run.policy
        for source in sorted(sources, key=lambda item: _source_priority(item, policy), reverse=True):
            if state is not None and state.stop_reason:
                break
            if fetches >= run.budget.max_fulltext_fetches:
                break
            if "capture_url" not in self.tools:
                break
            outcome = self._invoke_research_tool(
                state,
                "capture_url",
                url=source.url,
                user_id=run.user_id,
                run_id=run.id,
                _trace_decision_id=decision.id if decision is not None else None,
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
            primary = max(cluster, key=lambda item: _source_priority(item, run.policy))
            frame = cluster_frames[index]
            key = _fingerprint(_event_key_material(frame, primary))
            independent_domains = {item.domain for item in cluster}
            status, confidence = _event_status_for_policy(
                cluster,
                run.policy,
                independent_domain_count=len(independent_domains),
            )
            novelty = 0.2 if key in previous_keys else 0.9
            summary = primary.content[:800] or primary.snippet[:800]
            events.append(ResearchEvent(
                canonical_key=key,
                title=primary.title,
                summary=summary,
                occurred_at=primary.published_at,
                entities=list(getattr(frame, "entities", []) or []),
                topics=[run.topic],
                event_type=str(getattr(frame, "event_type", "") or "news"),
                source_ids=[source.id for source in cluster],
                frame=_frame_snapshot(frame),
                sources=cluster,
                importance_score=_importance(primary, subscription, run.policy),
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
        state: ResearchState | None = None,
    ) -> list[ResearchEvent]:
        enrich_personal_relevance = _should_enrich_personal_relevance(run)
        for event in events:
            relevance_cache_key = _personal_relevance_cache_key(event)
            if state is not None and relevance_cache_key in state.personal_relevance_cache:
                event.personal_relevance = state.personal_relevance_cache[relevance_cache_key]
                novelty_w = subscription.content_preferences.novelty_weight if subscription else 0.3
                relevance_w = (
                    subscription.content_preferences.personal_relevance_weight if subscription else 0.3
                )
                weights = _ranking_weights(run.policy, novelty_w=novelty_w, relevance_w=relevance_w)
                breakdown = _event_score_breakdown(event, run.policy, weights)
                event.score_breakdown = breakdown
                event.final_score = breakdown.final_score
                continue
            relevance = PersonalRelevance()
            relevance_matches: list[object] = []
            decision_id = _event_decision_ids(event)[0] if _event_decision_ids(event) else None
            if enrich_personal_relevance and "graph_search" in self.tools:
                outcome = self._invoke_research_tool(
                    state,
                    "graph_search",
                    question=_personal_relevance_question(event),
                    structured_context=_personal_relevance_context(event),
                    user_id=run.user_id,
                    run_id=run.id,
                    _trace_decision_id=decision_id,
                    _count_budget=False,
                )
                relevance_matches.extend(_personal_relevance_matches_from_tool_outcome(outcome))
            if enrich_personal_relevance and "enterprise_knowledge_search" in self.tools:
                outcome = self._invoke_research_tool(
                    state,
                    "enterprise_knowledge_search",
                    query=_personal_relevance_question(event),
                    limit=5,
                    user_id=run.user_id,
                    run_id=run.id,
                    _trace_decision_id=decision_id,
                    _count_budget=False,
                )
                relevance_matches.extend(
                    _enterprise_relevance_matches_from_tool_outcome(outcome)
                )
            if relevance_matches:
                relation, score, explanation = _personal_relevance_from_matches(
                    event,
                    relevance_matches,
                )
                relevance = PersonalRelevance(
                    score=score,
                    related_note_ids=[
                        str(item.get("note_id") or item.get("id") or item.get("artifact_id"))
                        for item in relevance_matches if isinstance(item, dict)
                    ],
                    relation=relation,
                    explanation=explanation,
                )
            event.personal_relevance = relevance
            if state is not None:
                state.personal_relevance_cache[relevance_cache_key] = relevance
            novelty_w = subscription.content_preferences.novelty_weight if subscription else 0.3
            relevance_w = (
                subscription.content_preferences.personal_relevance_weight if subscription else 0.3
            )
            weights = _ranking_weights(run.policy, novelty_w=novelty_w, relevance_w=relevance_w)
            breakdown = _event_score_breakdown(event, run.policy, weights)
            event.score_breakdown = breakdown
            event.final_score = breakdown.final_score
        minimum = (
            subscription.content_preferences.minimum_importance if subscription else 0
        )
        return sorted(
            [event for event in events if event.importance_score >= minimum],
            key=lambda item: item.final_score,
            reverse=True,
        )

    def _invoke_research_tool(
        self,
        state: ResearchState | None,
        name: str,
        **kwargs,
    ) -> dict:
        trace_decision_id = str(kwargs.pop("_trace_decision_id", "") or "") or None
        count_budget = bool(kwargs.pop("_count_budget", True))
        if state is not None and not count_budget and state.stop_reason == "tool budget exhausted":
            return {
                "ok": False,
                "error_kind": "budget_exhausted",
                "error": "Research tool-call budget exhausted.",
            }
        if state is not None and count_budget:
            if state.tool_call_count >= state.budget.max_tool_calls:
                state.stop_reason = "tool budget exhausted"
                return {
                    "ok": False,
                    "error_kind": "budget_exhausted",
                    "error": "Research tool-call budget exhausted.",
                }
            state.tool_call_count += 1
        started = _timer_start()
        outcome = self.tools.invoke_direct(name, **kwargs)
        if state is not None:
            state.tool_call_traces.append(ResearchToolCallTrace(
                tool_name=name,
                decision_id=trace_decision_id,
                elapsed_ms=_elapsed_ms(started),
                ok=bool(outcome.get("ok")),
                result_count=_tool_result_count(outcome),
                error_kind=str(outcome.get("error_kind") or ""),
            ))
        return outcome

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
                source_ids=[source.id for source in event.sources],
                decision_ids=_event_decision_ids(event),
                claims=_initial_digest_claims(event),
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


def _parse_llm_json_object(raw: str | None) -> dict | None:
    text = strip_json_fence(raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _timer_start() -> float:
    return time.perf_counter()


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _record_stage_timing(
    state: ResearchState,
    stage: str,
    started: float,
    *,
    decision_id: str | None = None,
    item_count: int = 0,
) -> None:
    state.stage_timings.append(ResearchStageTiming(
        stage=stage,
        decision_id=decision_id,
        elapsed_ms=_elapsed_ms(started),
        item_count=item_count,
    ))


def _tool_result_count(outcome: dict) -> int:
    data = outcome.get("data")
    if not isinstance(data, dict):
        return 0
    results = data.get("results")
    if isinstance(results, list):
        return len(results)
    structured = data.get("structured_content")
    if isinstance(structured, dict):
        structured_results = structured.get("results") or structured.get("items") or structured.get("matches")
        if isinstance(structured_results, list):
            return len(structured_results)
    for key in ("relation_facts", "fact_refs", "node_refs"):
        items = data.get(key)
        if isinstance(items, list):
            return len(items)
    text = data.get("text")
    if isinstance(text, str) and text:
        return 1
    return 0


def _personal_relevance_matches_from_tool_outcome(outcome: dict) -> list[object]:
    if not outcome.get("ok"):
        return []
    data = outcome.get("data") or {}
    if not isinstance(data, dict):
        return []
    matches = (
        data.get("relation_facts")
        or data.get("fact_refs")
        or data.get("node_refs")
        or []
    )
    return matches if isinstance(matches, list) else []


def _enterprise_relevance_matches_from_tool_outcome(outcome: dict) -> list[object]:
    if not outcome.get("ok"):
        return []
    data = outcome.get("data") or {}
    if not isinstance(data, dict):
        return []
    candidates: list[object] = []
    for key in ("results", "items", "matches", "documents"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(value)
            break
    text = data.get("text")
    if isinstance(text, str) and text.strip():
        candidates.append({
            "id": "enterprise_knowledge_search:text",
            "source": "enterprise_knowledge_search",
            "content": text[:2000],
        })
    normalized: list[object] = []
    for item in candidates:
        if isinstance(item, dict):
            normalized.append({"source": "enterprise_knowledge_search", **item})
        else:
            normalized.append({"source": "enterprise_knowledge_search", "content": str(item)})
    return normalized


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


def _coerce_int(value: object, *, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, lower), upper)


def _coerce_float(value: object, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 0.0), 1.0)


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    return default


def _coerce_query_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    queries = [
        str(item).strip()
        for item in value
        if str(item).strip()
    ]
    return list(dict.fromkeys(queries))[:limit]


def _query_purpose(query: str) -> str:
    lowered = query.lower()
    if "official" in lowered:
        return "find primary-source confirmation"
    if "open source" in lowered or "github" in lowered:
        return "find implementation or release evidence"
    return "find recent public reports"


def _query_intent(query: str) -> str:
    lowered = query.lower()
    if any(token in lowered for token in ("sec", "10-k", "10-q", "filing")):
        return "financial_filing"
    if "transcript" in lowered:
        return "transcript"
    if any(token in lowered for token in ("github", "repo", "open source")):
        return "repo"
    if any(token in lowered for token in ("docs", "documentation", "release notes")):
        return "docs"
    if any(token in lowered for token in ("paper", "arxiv", "technical report")):
        return "paper"
    if "official" in lowered:
        return "official"
    if any(token in lowered for token in ("news", "coverage", "report")):
        return "media"
    return "latest"


def _policy_query_phase(expected_gain: str) -> str:
    lowered = expected_gain.lower()
    if any(token in lowered for token in ("official", "confirmation", "source", "evidence", "verify", "independent")):
        return "verification"
    return "exploration"


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
    if "github.com" in lowered:
        return "github"
    if any(token in lowered for token in ("docs.", "/docs", "documentation", "developer.", "learn.")):
        return "docs"
    if any(token in lowered for token in ("sec.gov", "edgar", "10-k", "10-q", "8-k", "filing")):
        return "filing"
    if any(token in lowered for token in ("investor", "ir.", "earnings release")):
        return "investor_relations"
    if "transcript" in lowered:
        return "transcript"
    if any(token in lowered for token in ("official", "openai.com", "anthropic.com", "deepmind.google")):
        return "official"
    if any(token in lowered for token in ("arxiv.org", "paper", "proceedings")):
        return "paper"
    if any(token in lowered for token in ("twitter.com", "x.com", "weibo")):
        return "social"
    return "media"


def _gap_action_priority(gap: EvidenceGap) -> int:
    if gap.type == "missing_primary_source":
        return 0
    if gap.type == "single_source":
        return 1
    return 10


def _source_priority(source: ResearchSource, policy: ResearchPolicy | None = None) -> float:
    base = {
        "official": 1.0,
        "filing": 1.0,
        "investor_relations": 0.98,
        "docs": 0.96,
        "github": 0.94,
        "paper": 0.9,
        "transcript": 0.86,
        "media": 0.7,
        "blog": 0.5,
        "social": 0.3,
        "unknown": 0.2,
    }
    score = base.get(source.source_type, 0.2)
    if policy and source.source_type in policy.source_preference:
        rank = policy.source_preference.index(source.source_type)
        score += max(0.0, 0.2 - rank * 0.03)
    return score + (0.1 if source.content else 0)


def _importance(
    source: ResearchSource,
    subscription: ResearchSubscription | None,
    policy: ResearchPolicy | None = None,
) -> float:
    text = f"{source.title} {source.snippet}".lower()
    score = 0.45
    if source.source_type in _primary_source_types(policy or ResearchPolicy()):
        score += 0.2
    if any(token in text for token in ("release", "launch", "发布", "开源", "model", "模型", "policy", "安全")):
        score += 0.2
    if subscription:
        if any(token.lower() in text for token in subscription.content_preferences.exclude_topics):
            score -= 0.5
        if any(token.lower() in text for token in subscription.content_preferences.include_topics):
            score += 0.15
    return max(0, min(1, score))


def _primary_source_types(policy: ResearchPolicy) -> set[str]:
    if policy.evidence_requirement == "primary_financial_source_required":
        return {"filing", "investor_relations", "transcript"}
    if policy.evidence_requirement == "paper_or_primary_source":
        return {"paper", "official", "docs", "github"}
    if policy.evidence_requirement == "official_required":
        return {"official", "docs", "github", "filing", "investor_relations"}
    return {"official", "docs", "github", "paper", "filing", "investor_relations", "transcript"}


def _has_required_primary_source(
    sources: list[ResearchSource],
    policy: ResearchPolicy,
) -> bool:
    accepted = _primary_source_types(policy)
    return any(source.source_type in accepted for source in sources)


def _event_satisfies_policy(event: ResearchEvent, policy: ResearchPolicy) -> bool:
    independent_domains = {source.domain for source in event.sources}
    has_primary = _has_required_primary_source(event.sources, policy)
    if policy.evidence_requirement == "multi_source":
        return len(independent_domains) >= 2
    if policy.evidence_requirement in {
        "official_required",
        "paper_or_primary_source",
        "primary_financial_source_required",
    }:
        return has_primary
    return has_primary or len(independent_domains) >= 2


def _event_status_for_policy(
    sources: list[ResearchSource],
    policy: ResearchPolicy,
    *,
    independent_domain_count: int,
) -> tuple[str, float]:
    has_primary = _has_required_primary_source(sources, policy)
    strict = policy.verification_strictness in {"medium_high", "high"}
    if policy.evidence_requirement == "multi_source":
        if independent_domain_count >= 2:
            return "verified", 0.85
        return "uncertain", 0.35
    if policy.evidence_requirement in {
        "official_required",
        "paper_or_primary_source",
        "primary_financial_source_required",
    }:
        if has_primary and (independent_domain_count >= 2 or not strict):
            return "verified", 0.9
        if has_primary:
            return "uncertain", 0.4
        return "uncertain", 0.35
    if has_primary and independent_domain_count >= 2:
        return "verified", 0.9
    if independent_domain_count >= 2:
        return "reported", 0.7
    if has_primary:
        return ("uncertain", 0.4) if strict else ("reported", 0.7)
    return "uncertain", 0.4


def _primary_source_action(policy: ResearchPolicy) -> str:
    if policy.evidence_requirement == "primary_financial_source_required":
        return "find SEC filing, investor relations release, or transcript"
    if policy.evidence_requirement == "paper_or_primary_source":
        return "find paper, repository, or primary technical source"
    if policy.evidence_requirement == "multi_source":
        return "find independent source"
    return "find official or primary-source confirmation"


def _gap_queries(title: str, policy: ResearchPolicy) -> list[str]:
    if policy.evidence_requirement == "primary_financial_source_required":
        return [
            f"{title} SEC filing",
            f"{title} investor relations earnings release",
            f"{title} earnings call transcript",
        ]
    if policy.evidence_requirement == "paper_or_primary_source":
        return [
            f"{title} paper",
            f"{title} GitHub release",
            f"{title} official documentation",
        ]
    templates = {
        "official": f"{title} official announcement",
        "docs": f"{title} documentation release notes",
        "github": f"{title} GitHub release",
        "paper": f"{title} technical report paper",
        "filing": f"{title} SEC filing",
        "investor_relations": f"{title} investor relations release",
        "transcript": f"{title} transcript",
        "media": f"{title} independent coverage",
    }
    queries = [
        templates[source_type]
        for source_type in policy.source_preference
        if source_type in templates
    ]
    if not queries:
        queries = [f"{title} official announcement"]
    return list(dict.fromkeys(queries))


def _ranking_weights(
    policy: ResearchPolicy,
    *,
    novelty_w: float,
    relevance_w: float,
) -> dict[str, float]:
    if policy.ranking_objective == "personal_relevance_first":
        return {"importance": 0.2, "confidence": 0.2, "novelty": 0.15, "relevance": max(0.45, relevance_w)}
    if policy.ranking_objective == "novelty_first":
        return {"importance": 0.2, "confidence": 0.2, "novelty": max(0.4, novelty_w), "relevance": 0.2}
    if policy.ranking_objective == "impact_first":
        return {"importance": 0.4, "confidence": 0.25, "novelty": max(0.2, novelty_w), "relevance": 0.15}
    return {"importance": 0.2, "confidence": 0.4, "novelty": min(0.2, novelty_w), "relevance": min(0.25, relevance_w)}


def _personal_relevance_question(event: ResearchEvent) -> str:
    context = _personal_relevance_context(event)
    return " ".join(
        str(context[key])
        for key in ("title", "event_type", "entities", "source_domains", "summary")
        if context.get(key)
    )


def _personal_relevance_cache_key(event: ResearchEvent) -> str:
    return _fingerprint(json.dumps(
        {
            "canonical_key": event.canonical_key,
            "title": event.title,
            "event_type": event.event_type,
            "entities": sorted(event.entities),
        },
        ensure_ascii=False,
        sort_keys=True,
    ))


def _should_enrich_personal_relevance(run: ResearchRun) -> bool:
    if run.policy.ranking_objective == "personal_relevance_first":
        return True
    intent_text = f"{run.topic} {run.instructions}".lower()
    return any(token in intent_text for token in ("personal", "个人", "知识库", "相关"))


def _personal_relevance_context(event: ResearchEvent) -> dict[str, object]:
    domains = ", ".join(sorted({source.domain for source in event.sources})[:4])
    return {
        "title": event.title,
        "event_type": event.event_type,
        "entities": event.entities[:8],
        "source_domains": domains,
        "summary": event.summary[:500],
    }


def _personal_relevance_from_matches(
    event: ResearchEvent,
    matches: list[object],
) -> tuple[str, float, str]:
    match_text = " ".join(
        " ".join(str(value) for value in item.values() if isinstance(value, str))
        if isinstance(item, dict) else str(item)
        for item in matches
    ).lower()
    event_terms = _tokens(" ".join([
        event.title,
        event.event_type,
        " ".join(event.entities),
        event.summary,
    ]))
    match_terms = _tokens(match_text)
    overlap = len(event_terms & match_terms)
    if overlap >= 4 or any(entity.lower() in match_text for entity in event.entities if entity):
        return (
            "direct_update",
            min(1.0, 0.65 + len(matches) * 0.08),
            "事件的实体或事件类型与你已有知识直接重合，适合作为已有主题的更新追踪。",
        )
    if overlap >= 2:
        return (
            "related_update",
            min(1.0, 0.5 + len(matches) * 0.08),
            "事件与已有知识存在相关主题重合，可能补充现有背景或后续变化。",
        )
    if matches:
        return (
            "background_context",
            min(1.0, 0.4 + len(matches) * 0.05),
            "事件与已有知识有弱关联，可作为背景信息参考。",
        )
    return "not_relevant", 0.0, ""


def _event_score_breakdown(
    event: ResearchEvent,
    policy: ResearchPolicy,
    weights: dict[str, float],
) -> EventScoreBreakdown:
    source_quality = max((_source_priority(source, policy) for source in event.sources), default=0.0)
    source_quality = min(1.0, source_quality)
    independent_domains = {source.domain for source in event.sources}
    source_independence = min(1.0, len(independent_domains) / 3)
    uncertainty_penalty = {
        "verified": 0.0,
        "reported": 0.08,
        "uncertain": 0.25,
        "conflicted": 0.6,
    }.get(event.status, 0.25)
    raw = (
        event.importance_score * weights["importance"]
        + event.confidence_score * weights["confidence"]
        + event.novelty_score * weights["novelty"]
        + event.personal_relevance.score * weights["relevance"]
    )
    final_score = max(0.0, min(1.0, raw - uncertainty_penalty * 0.15))
    return EventScoreBreakdown(
        source_quality=source_quality,
        evidence_support=event.confidence_score,
        source_independence=source_independence,
        novelty=event.novelty_score,
        impact=event.importance_score,
        personal_relevance=event.personal_relevance.score,
        uncertainty_penalty=uncertainty_penalty,
        final_score=final_score,
    )


def _why_it_matters(event: ResearchEvent) -> str:
    if event.status == "verified":
        return "该事件有一手或多个独立来源支持，且具有较高新颖性或个人相关性。"
    if event.status == "reported":
        return "多个来源正在报道该变化，值得继续关注后续官方确认与实际影响。"
    return "目前证据有限，暂不宜作为确定事实，但可能值得后续追踪。"


def _frame_snapshot(frame: object | None) -> ResearchEventFrameSnapshot | None:
    if frame is None:
        return None
    confidence = float(getattr(frame, "confidence", 0) or 0)
    return ResearchEventFrameSnapshot(
        source_url=str(getattr(frame, "source_url", "") or ""),
        title=str(getattr(frame, "title", "") or ""),
        actor=str(getattr(frame, "actor", "") or ""),
        action=str(getattr(frame, "action", "") or ""),
        object=str(getattr(frame, "object", "") or ""),
        event_type=str(getattr(frame, "event_type", "") or "news"),
        occurred_at=str(getattr(frame, "occurred_at", "") or "") or None,
        entities=list(getattr(frame, "entities", []) or []),
        confidence=max(0.0, min(1.0, confidence)),
    )


def _event_decision_ids(event: ResearchEvent) -> list[str]:
    ids: list[str] = []
    for source in event.sources:
        if source.decision_id and source.decision_id not in ids:
            ids.append(source.decision_id)
    return ids


def _initial_digest_claims(event: ResearchEvent) -> list[DigestClaim]:
    texts: list[str] = []
    for text in (event.title, _first_sentence(event.summary)):
        normalized = " ".join(str(text or "").split())
        if normalized and normalized not in texts:
            texts.append(normalized)
    source_ids = [source.id for source in event.sources]
    decision_ids = _event_decision_ids(event)
    return [
        DigestClaim(
            text=text,
            event_id=event.id,
            claim_importance="core" if index == 0 else "supporting",
            source_ids=source_ids,
            decision_ids=decision_ids,
            support_level="unsupported",
        )
        for index, text in enumerate(texts)
    ]


def _verify_digest_item_claims(
    item: IntelligenceDigestItem,
    event: ResearchEvent,
) -> IntelligenceDigestItem:
    claims = item.claims or _initial_digest_claims(event)
    checked_claims = [
        _verify_digest_claim(claim, event.sources)
        for claim in claims
        if claim.text.strip()
    ]
    removed_non_core_unsupported = any(
        claim.support_level == "unsupported"
        and claim.claim_importance in {"supporting", "context"}
        for claim in checked_claims
    )
    verified_claims = [
        claim for claim in checked_claims
        if not (
            claim.support_level == "unsupported"
            and claim.claim_importance in {"supporting", "context"}
        )
    ]
    return item.model_copy(update={
        "claims": verified_claims,
        "confidence_label": _verified_digest_confidence_label(
            event,
            verified_claims,
            removed_non_core_unsupported=removed_non_core_unsupported,
        ),
    })


def _verify_digest_claim(
    claim: DigestClaim,
    sources: list[ResearchSource],
) -> DigestClaim:
    engine = EvidenceEngine()
    checks = engine.verify_claims(
        claim.text,
        engine.research_sources_to_evidence(sources),
        limit=1,
    )
    if not checks:
        return claim.model_copy(update={
            "source_ids": [],
            "evidence_spans": [],
            "support_level": "unsupported",
        })
    check = checks[0]
    decision_ids = _decision_ids_for_evidence(check.supporting_evidence_ids, sources)
    if check.status == "contradicted":
        support_level = "contradicted"
    elif check.status == "supported":
        support_level = "supported"
    elif check.status == "partially_supported":
        support_level = "partially_supported"
    else:
        support_level = "unsupported"
        check.supporting_evidence_ids = []
        check.evidence_spans = []
        decision_ids = []
    return claim.model_copy(update={
        "source_ids": check.supporting_evidence_ids[:3],
        "decision_ids": decision_ids[:3],
        "evidence_spans": check.evidence_spans[:3],
        "support_level": support_level,
    })


def _digest_item_has_supported_fact(item: IntelligenceDigestItem) -> bool:
    if not item.claims:
        return False
    if any(claim.support_level == "contradicted" for claim in item.claims):
        return False
    if any(
        claim.claim_importance == "core"
        and claim.support_level == "unsupported"
        for claim in item.claims
    ):
        return False
    return any(
        claim.support_level in {"supported", "partially_supported"}
        for claim in item.claims
    )


def _verified_digest_confidence_label(
    event: ResearchEvent,
    claims: list[DigestClaim],
    *,
    removed_non_core_unsupported: bool = False,
) -> str:
    levels = [claim.support_level for claim in claims]
    if not levels or any(level == "contradicted" for level in levels):
        return "来源冲突"
    if removed_non_core_unsupported or any(level == "unsupported" for level in levels):
        return "信息不足"
    if event.status == "verified" and all(level == "supported" for level in levels):
        return "已验证"
    if event.status in {"verified", "reported"}:
        return "多方报道"
    return "信息不足"


def _verified_run_status(run: ResearchRun, digest: IntelligenceDigest) -> str:
    stop_reason = (run.research_state.stop_reason if run.research_state else "") or ""
    if not digest.items:
        if "budget exhausted" in stop_reason:
            return "partial_budget_exhausted"
        if "low-yield" in stop_reason:
            return "partial_low_yield"
        return "partial_no_supported_claims"
    claim_levels = [
        claim.support_level
        for item in digest.items
        for claim in item.claims
    ]
    confidence_labels = {item.confidence_label for item in digest.items}
    if (
        claim_levels
        and all(level == "supported" for level in claim_levels)
        and confidence_labels == {"已验证"}
    ):
        return "completed_verified"
    return "completed_with_limitations"


def _first_sentence(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    parts = re.split(r"[。！？!?；;\n]+", cleaned, maxsplit=1)
    return parts[0][:240]


def _decision_ids_for_evidence(evidence_ids: list[str], sources: list[ResearchSource]) -> list[str]:
    by_source_id = {source.id: source for source in sources}
    decision_ids: list[str] = []
    for evidence_id in evidence_ids:
        source = by_source_id.get(evidence_id)
        if source is not None and source.decision_id and source.decision_id not in decision_ids:
            decision_ids.append(source.decision_id)
    return decision_ids
