"""Skill visibility and name resolution for an authenticated Conversation."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from personal_agent.application.bash_execution.models import BashWorkspaceFile
from personal_agent.application.bash_execution.ports import BashArtifactPort
from personal_agent.kernel.contracts.derivation import canonical_digest
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope


SkillName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)]
SkillSource = Literal["project", "user", "bundled"]
LOAD_SKILL_CAPABILITY = "load_skill"


class LoadedSkill(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    name: SkillName
    instructions: str = Field(min_length=1)
    source: SkillSource | None = None


class InstalledSkill(LoadedSkill):
    description: str = Field(min_length=1, max_length=1024)
    model_invocable: bool = True
    directory: Path | None = Field(default=None, exclude=True)


@dataclass(frozen=True)
class SkillScript:
    relative_path: str
    content: bytes


class PublishedSkillScripts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_base: str = Field(min_length=1)
    files: tuple[BashWorkspaceFile, ...] = Field(min_length=1)


def publish_skill_scripts(
    skill: InstalledSkill, scope: ExecutionScope, *, input_root: str,
    read_scripts: Callable[[Path], tuple[SkillScript, ...]], artifacts: BashArtifactPort,
) -> PublishedSkillScripts | None:
    if skill.directory is None:
        return None
    scripts = read_scripts(skill.directory)
    if not scripts:
        return None
    revision = canonical_digest([(item.relative_path, sha256(item.content).hexdigest()) for item in scripts])
    directory = f"skills/{skill.name}/{revision}"
    producer_scope = scope.model_copy(update={"task_id": None})
    files = []
    for item in scripts:
        path = f"{directory}/{item.relative_path}"
        ref = artifacts.publish_machine(
            execution_scope=producer_scope, producer_key=f"skill-script:{scope.execution_id}:{path}", producer_ref=path,
            filename=Path(item.relative_path).name, content_type="application/octet-stream",
            file_bytes=item.content, kind="skill_script",
        )
        files.append(BashWorkspaceFile(name=path, resource_ref=ref))
    return PublishedSkillScripts(resource_base=f"{input_root}/{directory}", files=tuple(files))


def render_skill_summaries(skills: Mapping[str, InstalledSkill]) -> str:
    return "\n".join(
        "- " + json.dumps({"name": skill.name, "description": skill.description}, ensure_ascii=False)
        for skill in skills.values()
    )


@dataclass(frozen=True)
class SkillLibrary:
    root_digest: str
    skills: tuple[InstalledSkill, ...]


class SkillCatalog:
    """Resolve the same precedence for model discovery and actual tool execution."""

    def __init__(
        self,
        *,
        bundled: SkillLibrary | None,
        users: Mapping[AuthenticatedPrincipal, SkillLibrary],
        projects: Mapping[tuple[AuthenticatedPrincipal, str], SkillLibrary],
    ) -> None:
        self._bundled = bundled
        self._users = dict(users)
        self._projects = dict(projects)

    @property
    def available(self) -> bool:
        return any(
            skill.model_invocable
            for library in (self._bundled, *self._users.values(), *self._projects.values())
            if library is not None
            for skill in library.skills
        )

    def scope_digest(self, principal: AuthenticatedPrincipal, session_id: str, *, source_platform: str) -> str | None:
        libraries = self._visible_libraries(principal, session_id, source_platform=source_platform)
        if all(source == "bundled" for source, _ in libraries):
            return None
        return canonical_digest({source: library.root_digest for source, library in libraries})

    def visible(
        self, principal: AuthenticatedPrincipal, session_id: str | None, *, source_platform: str | None,
    ) -> dict[str, InstalledSkill]:
        visible = {}
        for source, library in self._visible_libraries(principal, session_id, source_platform=source_platform):
            for skill in library.skills:
                if skill.name not in visible:
                    visible[skill.name] = skill.model_copy(update={"source": source})
        return {name: skill for name, skill in visible.items() if skill.model_invocable}

    def _visible_libraries(
        self, principal: AuthenticatedPrincipal, session_id: str | None, *, source_platform: str | None,
    ) -> tuple[tuple[SkillSource, SkillLibrary], ...]:
        if source_platform != "web":
            return (("bundled", self._bundled),) if self._bundled is not None else ()
        ordered: tuple[tuple[SkillSource, SkillLibrary | None], ...] = (
            ("project", self._projects.get((principal, session_id)) if session_id is not None else None),
            ("user", self._users.get(principal)),
            ("bundled", self._bundled),
        )
        return tuple((source, library) for source, library in ordered if library is not None)
