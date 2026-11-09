"""Toolathlon Time 配置对应的首个 MCP 用例。"""

UPSTREAM_REVISION = "9be8d8fe07a497b18ee61e3f2ae694e9797f39eb"
SERVER_ID = "toolathlon-time"
TOOL = "time.convert_time"
QUESTION = "上海上午 9 点是东京几点？"
ANSWER = "10:00"
MAPPING = {
    "remote_name": "convert_time",
    "name": TOOL,
    "semantic_domains": ["time"],
    "resource_types": ["timezone"],
    "operations": ["read"],
    "trust_level": "scoped",
    "credential_mode": "none",
    "data_egress_class": "none",
    "attestation_status": "pinned",
    "freshness_profile": "static",
    "output_contract": "time_conversion",
    "evidence_contract": "provider_output",
    "failure_semantics": "typed_failure",
    "risk_level": "low",
    "permission_scope": "time:convert",
    "side_effects": ["none"],
}
