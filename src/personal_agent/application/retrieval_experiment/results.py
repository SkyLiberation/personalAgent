"""正式结果原字节的唯一只读恢复；Runtime 与下载包复现共用。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from typing import Protocol

from personal_agent.application.artifacts.models import ArtifactResourceItem

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal, ExecutionScope

from .contracts import ExperimentResult
from .models import (
    BoundArtifact,
    PublishedExperimentResult,
    PublishedFrozenExperiment,
    RetrievalDeployment,
)


class PublishedArtifactReadPort(Protocol):
    def read_upload(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> tuple[object, bytes]: ...

    def resource_item(
        self,
        resource_ref: ResourceRef,
        *,
        principal: AuthenticatedPrincipal,
        owner: AuthenticatedPrincipal,
    ) -> ArtifactResourceItem: ...


class PublishedExperimentReader:
    def __init__(
        self,
        *,
        artifacts: PublishedArtifactReadPort,
        deployment: RetrievalDeployment | None = None,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self._prompts = prompts
        self.artifacts = artifacts
        self.deployment = deployment

    def read_artifact(
        self,
        ref: ResourceRef,
        *,
        execution_scope: ExecutionScope,
    ) -> BoundArtifact:
        principal = execution_scope.principal
        _, content = self.artifacts.read_upload(
            ref, principal=principal, owner=principal
        )
        item = self.artifacts.resource_item(ref, principal=principal, owner=principal)
        if item.size_bytes != len(content):
            raise ValueError(self._prompts.render('experiment_results.artifact_size'))
        return BoundArtifact.model_validate({'resource_ref': ref, 'content_digest': item.content_digest, 'content': content}, context=self._prompts)

    def read_result(
        self,
        ref: ResourceRef,
        *,
        execution_scope: ExecutionScope,
    ) -> tuple[PublishedExperimentResult, ExperimentResult, tuple[BoundArtifact, ...]]:
        wrapper = self.read_artifact(ref, execution_scope=execution_scope)
        publication = PublishedExperimentResult.model_validate_json(wrapper.content)
        raw = self.read_artifact(
            publication.raw_result_ref, execution_scope=execution_scope
        )
        result = ExperimentResult.model_validate_json(raw.content)
        files = tuple(
            self.read_artifact(
                getattr(publication, f"{name}_ref"), execution_scope=execution_scope
            )
            for name in ("rankings", "coverage", "metrics", "per_query")
        )
        for name, content in zip(
            ("rankings", "coverage", "metrics", "per_query"), files
        ):
            if getattr(result.artifacts, name).sha256 != content.content_digest:
                raise ValueError(self._prompts.render('experiment_results.publication_identity'))
        projections = []
        for name in ("corpus", "queries"):
            binding = getattr(publication, name)
            bound = self.read_artifact(
                binding.resource_ref, execution_scope=execution_scope
            )
            if bound.content_digest != binding.content_digest:
                raise ValueError(self._prompts.render('experiment_results.projection_binding'))
            if self.deployment:
                manifest = (
                    self.deployment.development
                    if result.dataset.split == "train"
                    else self.deployment.final
                )
                if manifest.artifact_sha256[f"{name}.json"] != bound.content_digest:
                    raise ValueError(self._prompts.render('experiment_results.projection_prepared'))
            projections.append(bound)
        return publication, result, (wrapper, raw, *files, *projections)

    def read_frozen(
        self,
        ref: ResourceRef,
        *,
        execution_scope: ExecutionScope,
    ) -> PublishedFrozenExperiment:
        return PublishedFrozenExperiment.model_validate_json(
            self.read_artifact(ref, execution_scope=execution_scope).content
        )
