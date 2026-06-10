from __future__ import annotations

import pytest

from personal_agent.policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyInput,
    PolicyRules,
)


def _tool_input(**overrides) -> PolicyInput:
    base = dict(
        action="tool_call",
        user_id="u1",
        execution_mode="direct",
        tool_name="delete_note",
        risk_level="high",
        requires_confirmation=True,
        side_effects=("delete_longterm",),
        permission_scope="memory:delete",
    )
    base.update(overrides)
    return PolicyInput(**base)


class TestToolDecisions:
    def test_low_risk_tool_allowed(self):
        engine = PolicyEngine()
        decision = engine.evaluate(
            PolicyInput(action="tool_call", tool_name="graph_search", risk_level="low")
        )
        assert decision.allowed
        assert decision.rule == "tool.default"

    def test_high_risk_unconfirmed_requires_confirmation(self):
        decision = PolicyEngine().evaluate(_tool_input(confirmed=False))
        assert decision.needs_confirmation
        assert decision.rule == "tool.high_risk_confirmation"

    def test_high_risk_confirmed_allowed(self):
        decision = PolicyEngine().evaluate(_tool_input(confirmed=True))
        assert decision.allowed
        assert decision.rule == "tool.high_risk_confirmed"

    def test_react_blocks_side_effecting_tool(self):
        decision = PolicyEngine().evaluate(
            _tool_input(
                execution_mode="react",
                confirmed=True,
                react_allowed_tools=frozenset({"delete_note"}),
            )
        )
        assert decision.effect == "deny"
        assert decision.rule == "react.blocked_side_effect"

    def test_react_blocks_tool_not_in_allow_list(self):
        decision = PolicyEngine().evaluate(
            PolicyInput(
                action="tool_call",
                execution_mode="react",
                tool_name="web_search",
                react_allowed_tools=frozenset({"graph_search"}),
            )
        )
        assert decision.effect == "deny"
        assert decision.rule == "react.not_allowed"

    def test_confirm_disabled_when_rule_off(self):
        engine = PolicyEngine(PolicyRules(require_confirmation_for_high_risk=False))
        decision = engine.evaluate(_tool_input(confirmed=False))
        assert decision.allowed


class TestOverrides:
    def test_deny_user_overrides_allow(self):
        engine = PolicyEngine(PolicyRules(deny_users=frozenset({"banned"})))
        decision = engine.evaluate(
            PolicyInput(action="tool_call", tool_name="graph_search", user_id="banned")
        )
        assert decision.effect == "deny"
        assert decision.rule == "override.deny_user"

    def test_deny_tool(self):
        engine = PolicyEngine(PolicyRules(deny_tools=frozenset({"web_search"})))
        decision = engine.evaluate(
            PolicyInput(action="tool_call", tool_name="web_search", user_id="u1")
        )
        assert decision.effect == "deny"
        assert decision.rule == "override.deny_tool"

    def test_deny_scope(self):
        engine = PolicyEngine(PolicyRules(deny_scopes=frozenset({"memory:delete"})))
        decision = engine.evaluate(_tool_input(confirmed=True))
        assert decision.effect == "deny"
        assert decision.rule == "override.deny_scope"


class TestMemoryDecisions:
    def test_owner_mismatch_denied(self):
        decision = PolicyEngine().evaluate(
            PolicyInput(
                action="memory_write",
                user_id="u1",
                resource_owner="u2",
                resource="note-1",
            )
        )
        assert decision.effect == "deny"
        assert decision.rule == "memory.owner_mismatch"

    def test_owner_match_allowed(self):
        decision = PolicyEngine().evaluate(
            PolicyInput(
                action="memory_write",
                user_id="u1",
                resource_owner="u1",
                resource="note-1",
            )
        )
        assert decision.allowed

    def test_delete_unconfirmed_requires_confirmation(self):
        decision = PolicyEngine().evaluate(
            PolicyInput(
                action="memory_delete",
                user_id="u1",
                resource_owner="u1",
                resource="note-1",
                confirmed=False,
            )
        )
        assert decision.needs_confirmation
        assert decision.rule == "memory.delete_confirmation"

    def test_delete_confirmed_allowed(self):
        decision = PolicyEngine().evaluate(
            PolicyInput(
                action="memory_delete",
                user_id="u1",
                resource_owner="u1",
                resource="note-1",
                confirmed=True,
            )
        )
        assert decision.allowed


class TestEntryDecisions:
    def test_source_not_in_allow_list_denied(self):
        engine = PolicyEngine(PolicyRules(allow_sources=frozenset({"web"})))
        decision = engine.evaluate(
            PolicyInput(action="entry_access", source_platform="feishu", user_id="u1")
        )
        assert decision.effect == "deny"
        assert decision.rule == "entry.source_not_allowed"

    def test_allowed_source_passes(self):
        engine = PolicyEngine(PolicyRules(allow_sources=frozenset({"web"})))
        decision = engine.evaluate(
            PolicyInput(action="entry_access", source_platform="web", user_id="u1")
        )
        assert decision.allowed


class TestDecisionHelpers:
    def test_allow_helper(self):
        assert PolicyDecision.allow().effect == "allow"

    def test_deny_helper_carries_kind(self):
        decision = PolicyDecision.deny("nope", error_kind="invalid_param")
        assert decision.effect == "deny"
        assert decision.error_kind == "invalid_param"
