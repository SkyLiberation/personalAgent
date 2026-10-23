"""Prepare authorized E1/P1 inputs and the real experiment deployment, without decisions."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from personal_agent.application.artifacts import ArtifactService
from personal_agent.application.retrieval_experiment.contracts import DatasetManifest, ModelIdentity, canonical_digest
from personal_agent.application.retrieval_experiment.models import ExperimentLimits, MaterialBinding, RetrievalDeployment
from personal_agent.infra.retrieval_experiment.deployment import LocalExperimentEnvironment, RetrievalDeploymentConfig
from personal_agent.infra.retrieval_experiment.retrieval import prepare_data
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .retrieval_baseline import MODEL, SOURCE, RetrievalScenario, RetrievalWorld, prepare_world

SCORER = AuthenticatedPrincipal(tenant_id="personal-agent", user_id="retrieval-experiment-scorer")


class LiveRetrievalWorld(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    initial: RetrievalWorld
    input_artifact_refs: tuple[ResourceRef, ...]
    deployment_path: Path
    deployment_digest: str


def prepare_live_world(
    settings: Settings,
    scenario: RetrievalScenario,
    *,
    limits: ExperimentLimits,
    directory: Path,
    worker_image_id: str,
    candidate_image_id: str,
    endpoint: str,
    network: str,
    es_endpoint: str,
) -> LiveRetrievalWorld:
    """Only original materials and trusted resources; no rankings, code, plan or winner."""
    directory.mkdir(parents=True, exist_ok=False)
    initial = prepare_world(settings, scenario, limits=limits)
    artifacts = ArtifactService(settings)
    private_path = SOURCE / "BeIR-scifact-qrels/test.tsv"
    private_bytes = private_path.read_bytes()
    private_ref = artifacts.save_upload(
        filename="test.tsv", content_type="text/tab-separated-values", file_bytes=private_bytes,
        uploads_dir=settings.data_dir / "uploads", principal=SCORER, owner=SCORER,
    )
    manifests = {}
    for split in ("train", "test"):
        manifest_path = prepare_data(
            SOURCE / "BeIR-scifact/corpus.parquet", SOURCE / "BeIR-scifact/queries.parquet",
            SOURCE / f"BeIR-scifact-qrels/{split}.tsv", split, directory / f"prepared-{split}",
        )
        manifests[split] = DatasetManifest.model_validate_json(manifest_path.read_bytes())
    model_hashes = {
        path.relative_to(MODEL).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(MODEL.rglob("*")) if path.is_file()
    }
    roles = ("corpus", "queries", "development_qrels")
    materials = tuple(
        MaterialBinding(role=role, resource_ref=item.resource_ref, content_digest=item.sha256)
        for role, item in zip(roles, initial.files, strict=True)
    ) + (MaterialBinding(role="test_qrels", resource_ref=private_ref,
                         content_digest=sha256(private_bytes).hexdigest()),)
    deployment = RetrievalDeployment(
        limits=limits,
        authorized_principal=initial.principal, scorer_principal=SCORER, materials=materials,
        development=manifests["train"], final=manifests["test"],
        worker_image_id=worker_image_id, candidate_image_id=candidate_image_id,
        model=ModelIdentity(revision="1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
                            sha256=canonical_digest(model_hashes)),
    )
    # Keep the host root short on Windows; command and result identities retain
    # their complete hashes in the existing backend directory protocol.
    job_root = (
        Path(__file__).resolve().parents[2] / ".tmp" / "rj"
        / sha256(str(directory.resolve()).encode("utf-8")).hexdigest()[:16]
    )
    config = RetrievalDeploymentConfig(
        deployment=deployment,
        environment=LocalExperimentEnvironment(
            endpoint=endpoint, network=network, es_endpoint=es_endpoint,
            model_path=MODEL.resolve(), workspace_root=job_root,
        ),
    )
    deployment_path = directory / "deployment.private.json"
    deployment_path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    return LiveRetrievalWorld(
        initial=initial,
        input_artifact_refs=(initial.environment_ref, *(item.resource_ref for item in initial.files)),
        deployment_path=deployment_path, deployment_digest=deployment.deployment_digest,
    )
