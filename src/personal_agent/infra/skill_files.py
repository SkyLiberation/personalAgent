"""Load trusted deployment skill packages at startup."""

from pathlib import Path

import yaml

from personal_agent.application.bash_execution.models import INPUT_MAX_BYTES, validate_workspace_path
from personal_agent.application.conversation.skills import InstalledSkill, SkillCatalog, SkillLibrary, SkillScript
from personal_agent.kernel.config_models import SkillScopesConfig
from personal_agent.kernel.contracts.derivation import canonical_digest


BUNDLED_SKILL_ROOT = Path(__file__).resolve().parents[1] / "bundled_skills"
_MAX_SKILL_BYTES = 64 * 1024
_SKILL_SUBDIRECTORIES = (Path(".dsh/skills"), Path(".agents/skills"))


def load_skill_catalog(bundled: Path | None, scopes: SkillScopesConfig) -> SkillCatalog:
    bundled_root = bundled.resolve(strict=True) if bundled is not None else None
    return SkillCatalog(
        bundled=SkillLibrary(canonical_digest(str(bundled_root)), load_installed_skills(bundled_root))
        if bundled_root is not None else None,
        users={entry.principal: _load_scoped_library(entry.home) for entry in scopes.users},
        projects={
            (entry.principal, entry.session_id): _load_scoped_library(entry.root)
            for entry in scopes.projects
        },
    )


def _load_scoped_library(root: Path) -> SkillLibrary:
    if not root.is_absolute():
        raise ValueError("Scoped skill roots must be absolute host directories")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Scoped skill root must be a directory")
    installed = {}
    for relative in _SKILL_SUBDIRECTORIES:
        directory = root / relative
        if directory.resolve() != directory:
            raise ValueError(f"Linked scoped skill directory is unsupported: {directory}")
        if directory.exists():
            for skill in load_installed_skills(directory):
                installed.setdefault(skill.name, skill)
    return SkillLibrary(canonical_digest(str(root)), tuple(installed.values()))


def load_installed_skills(root: Path) -> tuple[InstalledSkill, ...]:
    root = root.resolve(strict=True)
    skills = []
    for directory in sorted(root.iterdir()):
        path = directory / "SKILL.md"
        if not directory.is_dir() or not path.is_file():
            continue
        if path.resolve() != path or directory.is_symlink() or path.is_symlink():
            raise ValueError(f"Linked skill packages are unsupported: {directory.name}")
        skills.append(_read_skill(path))
    return tuple(skills)


def _read_skill(path: Path) -> InstalledSkill:
    with path.open("rb") as source:
        data = source.read(_MAX_SKILL_BYTES + 1)
    if len(data) > _MAX_SKILL_BYTES:
        raise ValueError(f"Skill exceeds {_MAX_SKILL_BYTES} bytes: {path.parent.name}")
    lines = data.decode("utf-8-sig").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"Skill frontmatter missing: {path.parent.name}")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
    else:
        raise ValueError(f"Unclosed skill frontmatter: {path.parent.name}")
    metadata = yaml.safe_load("".join(lines[1:index]))
    if not isinstance(metadata, dict) or metadata.get("name") != path.parent.name:
        raise ValueError(f"Skill name must match its directory: {path.parent.name}")
    description = metadata.get("description")
    return InstalledSkill(
        name=metadata["name"],
        description=" ".join(description.split()) if isinstance(description, str) else description,
        instructions="".join(lines[index + 1:]).lstrip("\r\n"),
        model_invocable=metadata.get("disable-model-invocation") is not True,
        directory=path.parent,
    )


def read_skill_scripts(directory: Path) -> tuple[SkillScript, ...]:
    """Read the selected package's script files for the immutable Bash input snapshot."""
    root = directory / "scripts"
    if root.resolve() != root or root.is_symlink():
        raise ValueError("Linked skill script directory is unsupported")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError("Skill scripts must be installed in a directory")
    pending = [root]
    paths: set[str] = set()
    remaining = INPUT_MAX_BYTES
    files = []
    for parent in pending:
        for path in sorted(parent.iterdir()):
            relative = validate_workspace_path(path.relative_to(directory).as_posix())
            normalized = relative.casefold()
            if normalized in paths or path.resolve() != path or path.is_symlink():
                raise ValueError("Skill resource path is linked or duplicated")
            paths.add(normalized)
            if path.is_dir():
                pending.append(path)
                continue
            if not path.is_file():
                raise ValueError("Skill resource must be a regular file")
            with path.open("rb") as source:
                content = source.read(remaining + 1)
            if len(content) > remaining:
                raise ValueError("Skill scripts exceed the Bash input byte limit")
            remaining -= len(content)
            files.append(SkillScript(relative, content))
    return tuple(files)
