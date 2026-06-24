from __future__ import annotations

import pytest

from personal_agent.agent.workflow import (
    EDGE_ABORT,
    EDGE_CLARIFY,
    WORKFLOW_REGISTRY,
    WorkflowConditionalEdge,
    WorkflowSpec,
    WorkflowStepSpec,
    WorkflowRegistry,
)
from personal_agent.agent.workflow_validator import (
    WorkflowSpecValidator,
    validate_registry_against_capabilities,
)


def _spec(*steps: WorkflowStepSpec, **kwargs) -> WorkflowSpec:
    return WorkflowSpec(
        workflow_id=kwargs.pop("workflow_id", "wf-test"),
        version="v1",
        intent=kwargs.pop("intent", "unknown"),
        steps=tuple(steps),
        **kwargs,
    )


class TestWorkflowSpecValidatorRegistry:
    def test_registered_registry_is_self_consistent(self):
        result = WorkflowSpecValidator().validate_registry(WORKFLOW_REGISTRY)
        assert result.valid, f"registry invalid: {result.issues}"

    def test_delete_workflow_declares_branch_policies(self):
        spec = WORKFLOW_REGISTRY.select("delete_knowledge")
        by_id = {s.step_id: s for s in spec.steps}
        assert by_id["del-2"].branch_policy == "human_select"
        assert by_id["del-3"].branch_policy == "abort"
        # del-3 rejection routes to an abort sentinel.
        targets = {e.target for e in by_id["del-3"].conditional_edges}
        assert EDGE_ABORT in targets
        # del-2 ambiguity routes to clarify.
        targets = {e.target for e in by_id["del-2"].conditional_edges}
        assert EDGE_CLARIFY in targets


class TestWorkflowSpecValidatorStructural:
    def test_unknown_action_type_is_blocking(self):
        spec = _spec(
            WorkflowStepSpec("s1", "frobnicate", "bad action"),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("无法被执行器分发" in i for i in result.issues)

    def test_missing_dependency_is_blocking(self):
        spec = _spec(
            WorkflowStepSpec("s1", "compose", "ok", depends_on=("ghost",)),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("不存在的 step_id" in i for i in result.issues)

    def test_dependency_cycle_is_blocking(self):
        spec = _spec(
            WorkflowStepSpec("a", "retrieve", "a", depends_on=("b",)),
            WorkflowStepSpec("b", "compose", "b", depends_on=("a",)),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("循环" in i for i in result.issues)

    def test_conditional_edge_unknown_target_is_blocking(self):
        spec = _spec(
            WorkflowStepSpec(
                "s1",
                "resolve",
                "ok",
                conditional_edges=(WorkflowConditionalEdge("oops", "nowhere"),),
            ),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("条件边" in i for i in result.issues)

    def test_conditional_edge_sentinel_target_is_allowed(self):
        spec = _spec(
            WorkflowStepSpec(
                "s1",
                "resolve",
                "ok",
                conditional_edges=(WorkflowConditionalEdge("ambiguous", EDGE_CLARIFY),),
            ),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert result.valid, result.issues

    def test_invalid_branch_policy_is_blocking(self):
        spec = _spec(WorkflowStepSpec("s1", "compose", "ok", branch_policy="teleport"))
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("branch_policy" in i for i in result.issues)


class TestWorkflowSpecValidatorSemantics:
    def test_delete_side_effect_requires_high_risk_and_confirmation(self):
        spec = _spec(
            WorkflowStepSpec(
                "s1",
                "tool_call",
                "delete",
                tool_name="delete_note",
                side_effects=("delete_longterm",),
                # deliberately under-declared:
                risk_level="low",
                requires_confirmation=False,
                hitl_policy="none",
            ),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("risk_level='high'" in i for i in result.issues)
        assert any("requires_confirmation=True" in i for i in result.issues)
        assert any("hitl_policy" in i for i in result.issues)

    def test_high_risk_requires_confirmation(self):
        spec = _spec(
            WorkflowStepSpec("s1", "compose", "ok", risk_level="high", requires_confirmation=False),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid

    def test_react_step_cannot_be_high_risk(self):
        spec = _spec(
            WorkflowStepSpec(
                "s1", "retrieve", "ok", execution_mode="react", risk_level="high",
                requires_confirmation=True,
            ),
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("react" in i for i in result.issues)

    def test_human_select_on_non_resolve_warns(self):
        spec = _spec(WorkflowStepSpec("s1", "compose", "ok", branch_policy="human_select"))
        result = WorkflowSpecValidator().validate_spec(spec)
        assert result.valid  # warning, not blocking
        assert any("human_select" in w for w in result.warnings)

    def test_projection_policy_requires_projectable_step(self):
        spec = _spec(
            WorkflowStepSpec("s1", "compose", "ok", project_to_plan=False),
            projection_policy="step_projection",
        )
        result = WorkflowSpecValidator().validate_spec(spec)
        assert not result.valid
        assert any("投影结果为空" in i for i in result.issues)


class TestRegistryCapabilityConsistency:
    @pytest.fixture
    def executor(self):
        from langchain_core.tools import tool
        from personal_agent.tools import (
            ToolExecutor,
            governance_extras,
            tool_response,
            tool_success,
        )

        @tool(
            "graph_search",
            description="search",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("read_longterm",)),
        )
        def graph_search(query: str):
            return tool_response(tool_success(query))

        @tool(
            "web_search",
            description="web",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("external_network",)),
        )
        def web_search(query: str):
            return tool_response(tool_success(query))

        @tool(
            "capture_text",
            description="capture",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("write_longterm",)),
        )
        def capture_text(text: str):
            return tool_response(tool_success(text))

        @tool(
            "capture_url",
            description="capture url",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="low", side_effects=("external_network", "write_longterm")
            ),
        )
        def capture_url(url: str):
            return tool_response(tool_success(url))

        @tool(
            "capture_upload",
            description="capture upload",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("write_longterm",)),
        )
        def capture_upload(path: str):
            return tool_response(tool_success(path))

        @tool(
            "delete_note",
            description="delete",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="high",
                requires_confirmation=True,
                side_effects=("delete_longterm",),
            ),
        )
        def delete_note(note_id: str):
            return tool_response(tool_success(note_id))

        @tool(
            "review_digest",
            description="digest",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("read_longterm",)),
        )
        def review_digest(user_id: str = "default"):
            return tool_response(tool_success(user_id))

        @tool(
            "consolidate_knowledge",
            description="consolidate",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("write_longterm",)),
        )
        def consolidate_knowledge(topic: str, user_id: str = "default"):
            return tool_response(tool_success(topic))

        @tool(
            "inspect_knowledge_gaps",
            description="gaps",
            response_format="content_and_artifact",
            extras=governance_extras(risk_level="low", side_effects=("read_longterm",)),
        )
        def inspect_knowledge_gaps(user_id: str = "default"):
            return tool_response(tool_success(user_id))

        @tool(
            "research_once",
            description="research",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="low",
                side_effects=("external_network", "read_longterm"),
            ),
        )
        def research_once(topic: str, user_id: str = "default"):
            return tool_response(tool_success(topic))

        @tool(
            "create_research_subscription",
            description="subscribe",
            response_format="content_and_artifact",
            extras=governance_extras(
                risk_level="medium",
                side_effects=("write_longterm",),
            ),
        )
        def create_research_subscription(request: str, user_id: str = "default"):
            return tool_response(tool_success(request))

        def _low_risk_tool(name: str):
            @tool(
                name,
                description=name,
                response_format="content_and_artifact",
                extras=governance_extras(risk_level="low", side_effects=("read_longterm",)),
            )
            def generic_tool(value: str = "", user_id: str = "default"):
                return tool_response(tool_success({"value": value, "user_id": user_id}))

            return generic_tool

        def _medium_risk_tool(name: str):
            @tool(
                name,
                description=name,
                response_format="content_and_artifact",
                extras=governance_extras(risk_level="medium", side_effects=("write_longterm",)),
            )
            def generic_tool(value: str = "", user_id: str = "default"):
                return tool_response(tool_success({"value": value, "user_id": user_id}))

            return generic_tool

        management_tools = [
            _medium_risk_tool("research_prepare_run"),
            _medium_risk_tool("research_plan_queries"),
            _medium_risk_tool("research_collect_sources"),
            _medium_risk_tool("research_cluster_events"),
            _medium_risk_tool("research_rank_events"),
            _medium_risk_tool("research_compose_digest"),
            _low_risk_tool("list_research_subscriptions"),
            _medium_risk_tool("update_research_subscription"),
            _medium_risk_tool("pause_research_subscription"),
            _medium_risk_tool("resume_research_subscription"),
            _medium_risk_tool("run_research_subscription_now"),
            _low_risk_tool("list_research_runs"),
            _low_risk_tool("get_research_digest"),
            _medium_risk_tool("submit_research_feedback"),
            _medium_risk_tool("save_research_event"),
            _low_risk_tool("list_recent_notes"),
            _low_risk_tool("get_note"),
            _low_risk_tool("find_similar_notes"),
            _medium_risk_tool("update_note"),
            _medium_risk_tool("supersede_note"),
            _medium_risk_tool("mark_note_deprecated"),
            _medium_risk_tool("mark_notes_conflicted"),
            _low_risk_tool("inspect_worker_queue"),
            _medium_risk_tool("retry_worker_task"),
            _low_risk_tool("inspect_workflow_run"),
        ]

        ex = ToolExecutor()
        for t in (
            graph_search, web_search, capture_text, capture_url, capture_upload,
            delete_note, review_digest, consolidate_knowledge, inspect_knowledge_gaps,
            research_once, create_research_subscription,
            *management_tools,
        ):
            ex.register(t)
        return ex

    def test_registry_matches_registered_tool_capabilities(self, executor):
        result = validate_registry_against_capabilities(WORKFLOW_REGISTRY, executor)
        assert result.valid, f"capability drift: {result.issues}"

    def test_unregistered_tool_is_flagged(self, executor):
        registry = WorkflowRegistry([
            _spec(
                WorkflowStepSpec("s1", "tool_call", "x", tool_name="nonexistent_tool"),
                workflow_id="bad",
                intent="ask",
            ),
            _spec(workflow_id="unknown", intent="unknown"),
        ])
        result = validate_registry_against_capabilities(registry, executor)
        assert not result.valid
        assert any("未在 ToolExecutor 中注册" in i for i in result.issues)

    def test_tool_requiring_confirmation_without_step_confirm_is_flagged(self, executor):
        registry = WorkflowRegistry([
            _spec(
                WorkflowStepSpec(
                    "s1", "tool_call", "del", tool_name="delete_note",
                    # high-risk tool but step under-declares confirmation
                    risk_level="high", requires_confirmation=False,
                    side_effects=("delete_longterm",), hitl_policy="required_for_delete",
                ),
                workflow_id="bad",
                intent="ask",
            ),
            _spec(workflow_id="unknown", intent="unknown"),
        ])
        result = validate_registry_against_capabilities(registry, executor)
        assert not result.valid
        assert any("要求确认" in i for i in result.issues)
