"""Unified governance policy layer.

A single ``PolicyEngine`` decides allow / deny / require_confirmation /
require_escalation for tool calls, memory access, and entry sources, replacing
the governance logic previously hardcoded inside the tool gateway, the
``delete_note`` tool, and the memory facade.
"""

from personal_agent.policy.engine import PolicyEngine, PolicyRules
from personal_agent.policy.models import PolicyAction, PolicyDecision, PolicyEffect, PolicyInput

__all__ = [
    "PolicyAction",
    "PolicyDecision",
    "PolicyEffect",
    "PolicyEngine",
    "PolicyInput",
    "PolicyRules",
]
