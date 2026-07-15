"""Immutable skill packages and tenant-owned installation records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SkillApplicability(BaseModel):
    semantic_domains: tuple[str, ...] = ()
    evidence_gap_codes: tuple[str, ...] = ()
    result_contracts: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()


class PlaybookSpec(BaseModel):
    playbook_id: str
    applicable_conditions: tuple[str, ...] = ()
    recommended_actions: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()
    allowed_deviations: tuple[str, ...] = ()


class SkillPackageManifest(BaseModel):
    skill_id: str = Field(alias="id")
    version: str
    description: str
    publisher: str
    content_hash: str
    signature: str = ""
    runtime_compatibility: str
    dependencies: tuple[str, ...] = ()
    requested_permissions: tuple[str, ...] = ()
    required_capability_kinds: tuple[str, ...] = ()
    output_contracts: tuple[str, ...] = ()
    verifier_profile: str = "default"
    eval_contract: str = ""
    applicability: SkillApplicability = Field(default_factory=SkillApplicability)


class SkillInstallation(BaseModel):
    tenant_id: str
    skill_id: str
    source_location: str
    installed_version: str
    status: Literal["discovered", "installed", "disabled"] = "discovered"
    approved_permissions: tuple[str, ...] = ()
    installed_by: str = "system"
    installed_at: datetime
    signature_verification: Literal["verified", "unsigned", "invalid"] = "unsigned"


class SkillTrustDecision(BaseModel):
    tenant_id: str
    skill_id: str
    version: str
    decision: Literal["trusted", "untrusted", "denied"]
    reason_codes: tuple[str, ...] = ()
    decided_at: datetime


class SkillActivation(BaseModel):
    activation_id: str
    tenant_id: str
    run_id: str
    goal_id: str
    skill_id: str
    version: str
    reason: str


class SkillScriptAuthorization(BaseModel):
    tenant_id: str
    skill_id: str
    version: str
    script_path: str
    capability_id: str
    approved: bool = False


class LoadedSkill(BaseModel):
    manifest: SkillPackageManifest
    instructions: str
    playbooks: tuple[PlaybookSpec, ...] = ()
    package_path: str


__all__ = [
    "LoadedSkill",
    "PlaybookSpec",
    "SkillActivation",
    "SkillApplicability",
    "SkillInstallation",
    "SkillPackageManifest",
    "SkillScriptAuthorization",
    "SkillTrustDecision",
]
