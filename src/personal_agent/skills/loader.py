"""Filesystem loader for progressively disclosed skill packages."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import yaml

from personal_agent.skills.contracts import LoadedSkill, PlaybookSpec, SkillPackageManifest


class SkillPackageError(ValueError):
    pass


class SkillPackageLoader:
    def discover(self, root: Path) -> tuple[SkillPackageManifest, ...]:
        manifests = [self.load_manifest(path.parent) for path in sorted(root.glob("*/skill.yaml"))]
        return tuple(manifests)

    def load_manifest(self, package_path: Path) -> SkillPackageManifest:
        path = package_path / "skill.yaml"
        if not path.is_file():
            raise SkillPackageError(f"missing skill manifest: {path}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise SkillPackageError(f"skill manifest must be an object: {path}")
        manifest = SkillPackageManifest.model_validate(payload)
        actual_hash = self.content_hash(package_path)
        if manifest.content_hash != f"sha256:{actual_hash}":
            raise SkillPackageError(f"content hash mismatch for {manifest.skill_id}")
        return manifest

    def load(self, package_path: Path) -> LoadedSkill:
        manifest = self.load_manifest(package_path)
        instructions_path = package_path / "SKILL.md"
        if not instructions_path.is_file():
            raise SkillPackageError(f"missing SKILL.md for {manifest.skill_id}")
        playbooks = []
        for path in sorted((package_path / "playbooks").glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
            playbooks.append(PlaybookSpec.model_validate(payload))
        return LoadedSkill(
            manifest=manifest,
            instructions=instructions_path.read_text(encoding="utf-8").strip(),
            playbooks=tuple(playbooks),
            package_path=str(package_path),
        )

    @staticmethod
    def content_hash(package_path: Path) -> str:
        digest = sha256()
        paths = [package_path / "SKILL.md"]
        paths.extend(sorted((package_path / "playbooks").glob("*.yaml")))
        paths.extend(sorted(path for path in (package_path / "scripts").glob("**/*") if path.is_file()))
        for path in paths:
            if not path.is_file():
                continue
            digest.update(path.relative_to(package_path).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()


__all__ = ["SkillPackageError", "SkillPackageLoader"]
