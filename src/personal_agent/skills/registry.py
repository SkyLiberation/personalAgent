"""Tenant-aware repository for skill discovery and activation."""

from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime

from personal_agent.kernel.contracts.agentic import TaskContract
from personal_agent.skills.contracts import (
    LoadedSkill,
    SkillInstallation,
    SkillPackageManifest,
    SkillTrustDecision,
)
from personal_agent.skills.loader import SkillPackageLoader


class SkillRegistry:
    def __init__(self, root: Path | None = None, loader: SkillPackageLoader | None = None) -> None:
        self._root = root or Path(__file__).with_name("packages")
        self._loader = loader or SkillPackageLoader()
        self._paths = {
            manifest.skill_id: path.parent
            for path in sorted(self._root.glob("*/skill.yaml"))
            if (manifest := self._loader.load_manifest(path.parent))
        }
        self._installations: dict[tuple[str, str], SkillInstallation] = {}
        self._trust: dict[tuple[str, str], SkillTrustDecision] = {}

    @classmethod
    def with_builtin_trust(cls, tenant_id: str = "default") -> "SkillRegistry":
        registry = cls()
        now = datetime.now(UTC)
        for manifest in registry.manifests():
            registry.install(
                SkillInstallation(
                    tenant_id=tenant_id,
                    skill_id=manifest.skill_id,
                    source_location=str(registry._paths[manifest.skill_id]),
                    installed_version=manifest.version,
                    status="installed",
                    approved_permissions=manifest.requested_permissions,
                    installed_at=now,
                    signature_verification="unsigned",
                ),
                SkillTrustDecision(
                    tenant_id=tenant_id,
                    skill_id=manifest.skill_id,
                    version=manifest.version,
                    decision="trusted",
                    reason_codes=("bundled_project_package",),
                    decided_at=now,
                ),
            )
        return registry

    def manifests(self) -> tuple[SkillPackageManifest, ...]:
        return tuple(self._loader.load_manifest(path) for path in self._paths.values())

    def install(self, record: SkillInstallation, trust: SkillTrustDecision) -> None:
        manifest = self.manifest(record.skill_id)
        if record.installed_version != manifest.version or trust.version != manifest.version:
            raise ValueError("installation and trust records must match the package version")
        if not set(record.approved_permissions).issubset(manifest.requested_permissions):
            raise ValueError("approved permissions exceed package request")
        self._installations[(record.tenant_id, record.skill_id)] = record
        self._trust[(record.tenant_id, record.skill_id)] = trust

    def manifest(self, skill_id: str) -> SkillPackageManifest:
        path = self._paths.get(skill_id)
        if path is None:
            raise KeyError(skill_id)
        return self._loader.load_manifest(path)

    def get(self, tenant_id: str, skill_id: str) -> LoadedSkill:
        installation = self._installations.get((tenant_id, skill_id))
        trust = self._trust.get((tenant_id, skill_id))
        if installation is None or installation.status != "installed":
            raise PermissionError(f"skill is not installed: {skill_id}")
        if trust is None or trust.decision != "trusted":
            raise PermissionError(f"skill is not trusted: {skill_id}")
        return self._loader.load(self._paths[skill_id])

    def candidates(self, task: TaskContract) -> tuple[SkillPackageManifest, ...]:
        domains = {item.semantic_domain for item in task.resource_requirements}
        operations = set(task.requested_operations)
        return tuple(
            manifest for manifest in self.manifests()
            if (
                domains.intersection(manifest.applicability.semantic_domains)
                or operations.intersection(manifest.applicability.operations)
                or task.result_contract in manifest.applicability.result_contracts
            )
        )


__all__ = ["SkillRegistry"]
