"""Unit tests for query planner (P2 retrieval optimization)."""
from __future__ import annotations

from personal_agent.core.config import LangExtractConfig, OpenAIConfig, Settings
from personal_agent.core.query_understanding import QueryUnderstanding, RetrievalFilters, RetrievalPlan
from personal_agent.agent.query_planner import _call_planner_llm, _derive_plan, _heuristic_filters


class TestQueryUnderstandingModel:
    def test_defaults(self) -> None:
        qu = QueryUnderstanding()
        assert qu.needs_freshness is False
        assert qu.needs_personal_memory is True
        assert qu.needs_graph_reasoning is False
        assert qu.query_rewrite == ""
        assert qu.sub_queries == []
        assert qu.filters.active() is False
        assert qu.answer_policy == "must_cite"

    def test_from_dict(self) -> None:
        data = {
            "needs_freshness": True,
            "needs_personal_memory": False,
            "needs_graph_reasoning": True,
            "query_rewrite": "FastAPI dependency injection mechanism",
            "sub_queries": ["What is FastAPI DI", "How does Depends work"],
            "answer_policy": "allow_web",
        }
        qu = QueryUnderstanding(**data)
        assert qu.needs_freshness is True
        assert qu.needs_graph_reasoning is True
        assert qu.sub_queries == ["What is FastAPI DI", "How does Depends work"]


class TestRetrievalPlanModel:
    def test_defaults(self) -> None:
        plan = RetrievalPlan(query="test")
        assert plan.sources == ["graph", "local"]
        assert plan.parallel is True
        assert plan.query == "test"
        assert plan.sub_queries == []
        assert plan.filters.active() is False


class TestDerivePlan:
    def test_personal_memory_question(self) -> None:
        qu = QueryUnderstanding(
            needs_personal_memory=True,
            query_rewrite="Redis caching strategy notes",
        )
        plan = _derive_plan("我之前记的 Redis 缓存策略", qu)
        assert "graph" in plan.sources
        assert "local" in plan.sources
        assert "web" not in plan.sources
        assert plan.parallel is True
        assert plan.query == "Redis caching strategy notes"

    def test_filters_are_carried_into_plan(self) -> None:
        qu = QueryUnderstanding(
            needs_personal_memory=True,
            query_rewrite="部署文档",
            filters=RetrievalFilters(source_types=["file"], source_ref_contains="deploy.md"),
        )
        plan = _derive_plan("只看 deploy.md 文件里的部署说明", qu)
        assert plan.filters.source_types == ["file"]
        assert plan.filters.source_ref_contains == "deploy.md"

    def test_freshness_question(self) -> None:
        qu = QueryUnderstanding(
            needs_freshness=True,
            needs_personal_memory=False,
            query_rewrite="LangGraph latest version 2024",
            answer_policy="allow_web",
        )
        plan = _derive_plan("LangGraph 最新版本是什么", qu)
        assert "web" in plan.sources
        assert plan.query == "LangGraph latest version 2024"

    def test_graph_reasoning_question(self) -> None:
        qu = QueryUnderstanding(
            needs_graph_reasoning=True,
            needs_personal_memory=True,
            query_rewrite="FastAPI Graphiti relationship",
            sub_queries=["What is FastAPI used for", "What is Graphiti used for"],
        )
        plan = _derive_plan("FastAPI 和 Graphiti 之间有什么联系", qu)
        assert "graph" in plan.sources
        assert "local" in plan.sources
        assert plan.parallel is True
        assert plan.sub_queries == ["What is FastAPI used for", "What is Graphiti used for"]

    def test_empty_understanding_defaults(self) -> None:
        qu = QueryUnderstanding(
            needs_freshness=False,
            needs_personal_memory=False,
            needs_graph_reasoning=False,
        )
        plan = _derive_plan("hello", qu)
        assert "graph" in plan.sources
        assert "local" in plan.sources

    def test_no_parallel_when_only_graph(self) -> None:
        qu = QueryUnderstanding(
            needs_personal_memory=False,
            needs_graph_reasoning=True,
            query_rewrite="entity connections",
        )
        plan = _derive_plan("实体间连接", qu)
        assert "graph" in plan.sources
        assert plan.parallel == ("local" in plan.sources)


class TestHeuristicFilters:
    def test_detects_file_reference(self) -> None:
        filters = _heuristic_filters("只看 deploy.md 文件里关于发布的内容")
        assert "file" in filters.source_types
        assert filters.source_ref_contains == "deploy.md"

    def test_detects_recent_time_window(self) -> None:
        filters = _heuristic_filters("最近保存的链接里有哪些 RAG 内容")
        assert "link" in filters.source_types
        assert filters.created_after
        assert filters.created_before


def test_call_planner_llm_prefers_langextract_json_schema(monkeypatch) -> None:
    request: dict = {}

    class FakeMessage:
        content = (
            '{"needs_freshness":false,"needs_personal_memory":true,'
            '"needs_graph_reasoning":false,"query_rewrite":"redis cache",'
            '"sub_queries":[],"filters":{"source_types":[],'
            '"source_ref_contains":"","tags":[],"created_after":"",'
            '"created_before":"","metadata_contains":"","parent_note_id":""},'
            '"answer_policy":"must_cite"}'
        )

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            request.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            request["client"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr("personal_agent.agent.query_planner.OpenAI", FakeOpenAI)
    settings = Settings(
        openai=OpenAIConfig(api_key="openai-k", base_url="https://openai.invalid", small_model="deepseek"),
        langextract=LangExtractConfig(
            api_key="extract-k",
            base_url="https://dashscope.invalid/compatible-mode/v1",
            model_id="qwen3-coder-flash",
        ),
    )

    understanding = _call_planner_llm("Redis 怎么缓存订单？", "", settings)

    assert understanding.query_rewrite == "redis cache"
    assert request["client"]["api_key"] == "extract-k"
    assert request["client"]["base_url"] == "https://dashscope.invalid/compatible-mode/v1"
    assert request["model"] == "qwen3-coder-flash"
    assert request["response_format"]["type"] == "json_schema"
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["response_format"]["json_schema"]["schema"]["required"] == [
        "needs_freshness",
        "needs_personal_memory",
        "needs_graph_reasoning",
        "query_rewrite",
        "sub_queries",
        "filters",
        "answer_policy",
    ]
