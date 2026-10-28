"""生产实验执行Port：固定工作负载经唯一引擎执行、原身份对账。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Literal
from typing_extensions import NotRequired, TypedDict

from pydantic import AwareDatetime, TypeAdapter

from personal_agent.application.retrieval_experiment.contracts import (
    BM25Config,
    CandidateConfig,
    DenseConfig,
    Digest,
    ExperimentResult,
    Identifier,
    RRFConfig,
    canonical_digest,
)
from personal_agent.application.retrieval_experiment.models import (
    BackendDiagnostic,
    BackendJobFact,
    BackendOutcome,
    BoundArtifact,
    DevelopmentWorkload,
    ExperimentCommand,
    ExperimentExecutionFact,
    FinalWorkload,
    PublishedExperimentResult,
    ResultBundle,
    RetrievalDeployment,
    Seconds,
)
from personal_agent.application.retrieval_experiment.rules import (
    recipe,
    validate_final_dataset,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from .controller import (
    ExecutionEnvironment,
    _docker_client,
    _WORKER_STATE,
    load_manifest,
    load_result,
    run_baseline,
    run_candidate,
    run_rrf,
    run_test,
)
from .deployment import LocalExperimentEnvironment
from .file_io import read_json, replace_json, sha256_file, write_json
from .retrieval import prepare_data
from personal_agent.infra.python_execution.sandbox import (
    _JobRecord, _SavedResult, _remove_staging,
)


class _StagedInput(TypedDict):
    resource_ref: ResourceRef
    content_digest: Digest
    filename: Identifier


class _ExecutionState(TypedDict):
    command_digest: Digest
    started_at: AwareDatetime
    status: Literal[
        "dispatching", "succeeded", "failed", "timed_out", "output_limit", "unknown"
    ]
    error_code: NotRequired[
        Literal["backend_unknown", "output_limit", "deadline", "execution_failed"]
        | None
    ]
    failure_type: NotRequired[str]
    failure_detail: NotRequired[str]
    elapsed_seconds: NotRequired[Seconds]
    result_paths: NotRequired[list[str]]
    cleanup_errors: NotRequired[list[str]]


_STAGED_INPUTS = TypeAdapter(list[_StagedInput])
_EXECUTION_STATE = TypeAdapter(_ExecutionState)


def _read_state(root: Path) -> _ExecutionState:
    return _EXECUTION_STATE.validate_python(read_json(root / "execution.json"))


def _save_state(root: Path, state: _ExecutionState) -> None:
    replace_json(
        root / "execution.json", _EXECUTION_STATE.dump_python(state, mode="json")
    )


class DockerExperimentBackend:
    def __init__(
        self,
        *,
        deployment: RetrievalDeployment,
        environment: LocalExperimentEnvironment,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
    ) -> None:
        self._prompts = prompts
        self.deployment = deployment
        self.environment = environment

    def _root(self, command: ExperimentCommand) -> Path:
        base = self.environment.workspace_root.resolve()
        root = base / command.command_digest
        if root.is_symlink() or root.resolve().parent != base:
            raise ValueError(self._prompts.render('experiment_backend.directory_escape'))
        if command.deployment_digest != self.deployment.deployment_digest:
            raise ValueError(self._prompts.render('experiment_backend.deployment_stale'))
        return root

    def execute(
        self, command: ExperimentCommand, inputs: tuple[BoundArtifact, ...]
    ) -> BackendOutcome:
        root = self._root(command)
        if root.exists():
            return self.reconcile(command)
        root.mkdir(parents=True)
        staged = root / "inputs"
        staged.mkdir()
        identities: list[_StagedInput] = []
        for item in inputs:
            filename = (
                canonical_digest(item.resource_ref.model_dump(mode="json")) + ".bin"
            )
            (staged / filename).write_bytes(item.content)
            identities.append(
                {
                    "resource_ref": item.resource_ref,
                    "content_digest": item.content_digest,
                    "filename": filename,
                }
            )
        replace_json(
            root / "inputs.json", _STAGED_INPUTS.dump_python(identities, mode="json")
        )
        _save_state(
            root,
            {
                "command_digest": command.command_digest,
                "started_at": datetime.now(timezone.utc),
                "status": "dispatching",
            },
        )
        return self._run(command, root)

    def reconcile(self, command: ExperimentCommand) -> BackendOutcome:
        root = self._root(command)
        if (
            not (root / "execution.json").is_file()
            or not (root / "inputs.json").is_file()
        ):
            return BackendOutcome(
                execution=ExperimentExecutionFact(
                    status="unknown", error_code="backend_unknown"
                )
            )
        saved = _read_state(root)
        if saved["command_digest"] != command.command_digest:
            raise ValueError(self._prompts.render('experiment_backend.execution_identity'))
        if saved.get("status") in {"succeeded", "failed", "timed_out", "output_limit"}:
            return self._outcome(command, root, saved)
        return self._run(command, root)

    def _inputs(
        self, command: ExperimentCommand, root: Path
    ) -> dict[ResourceRef, Path]:
        contents = {}
        for row in _STAGED_INPUTS.validate_python(read_json(root / "inputs.json")):
            ref = row["resource_ref"]
            filename = row["filename"]
            if filename != canonical_digest(ref.model_dump(mode="json")) + ".bin":
                raise ValueError(self._prompts.render('experiment_backend.filename'))
            path = root / "inputs" / filename
            if sha256_file(path) != row["content_digest"]:
                raise ValueError(self._prompts.render('experiment_backend.staging_bytes'))
            contents[ref] = path
        expected = {
            item.resource_ref: item.content_digest for item in command.bound_inputs
        }
        if isinstance(command.workload, FinalWorkload):
            private = next(
                x for x in self.deployment.materials if x.role == "test_qrels"
            )
            expected[private.resource_ref] = private.content_digest
        if set(contents) != set(expected) or any(
            sha256_file(contents[ref]) != digest for ref, digest in expected.items()
        ):
            raise ValueError(self._prompts.render('experiment_backend.input_binding'))
        return contents

    def _environment(
        self, command: ExperimentCommand, *, bm25: bool = False
    ) -> ExecutionEnvironment:
        return ExecutionEnvironment(
            endpoint=self.environment.endpoint,
            image=self.deployment.worker_image_id,
            network=self.environment.network if bm25 else "none",
            es_endpoint=self.environment.es_endpoint if bm25 else None,
            model_path=self.environment.model_path,
            model_revision=self.deployment.model.revision,
            timeout_seconds=self.deployment.limits.worker_timeout_seconds,
            command_digest=command.command_digest,
            deadline_at=command.deadline_at,
            retain_jobs=True,
            **self.deployment.limits.model_dump(
                include={
                    "worker_memory_mb",
                    "worker_cpus",
                    "worker_pids",
                    "candidate_memory_mb",
                    "candidate_cpus",
                    "candidate_pids",
                    "candidate_scratch_mb",
                    "stdout_bytes",
                    "stderr_bytes",
                }
            ),
        )

    def _materialize_result(
        self,
        publication: PublishedExperimentResult,
        inputs: dict[ResourceRef, Path],
        root: Path,
    ) -> Path:
        digest = sha256_file(inputs[publication.raw_result_ref])
        target = root / "result-inputs" / digest
        if not target.exists():
            target.mkdir(parents=True)
            for name, ref in (
                ("result", publication.raw_result_ref),
                ("rankings", publication.rankings_ref),
                ("coverage", publication.coverage_ref),
                ("metrics", publication.metrics_ref),
                ("per_query", publication.per_query_ref),
            ):
                (target / f"{name}.json").write_bytes(inputs[ref].read_bytes())
        load_result(target / "result.json")
        return target / "result.json"

    def _run(self, command: ExperimentCommand, root: Path) -> BackendOutcome:
        saved = _read_state(root)
        result_paths: list[Path] = []
        try:
            inputs = self._inputs(command, root)
            model_hash = canonical_digest(
                {
                    p.relative_to(self.environment.model_path).as_posix(): sha256_file(
                        p
                    )
                    for p in sorted(self.environment.model_path.rglob("*"))
                    if p.is_file()
                }
            )
            if model_hash != self.deployment.model.sha256:
                raise ValueError("本地模型快照与部署身份不同")
            with closing(_docker_client(self.environment.endpoint)) as client:
                if (
                    client.images.get(self.deployment.worker_image_id).id
                    != self.deployment.worker_image_id
                    or client.images.get(self.deployment.candidate_image_id).id
                    != self.deployment.candidate_image_id
                ):
                    raise ValueError("许可镜像不可用")
            final = isinstance(command.workload, FinalWorkload)
            material = {
                item.role: inputs[item.resource_ref]
                for item in self.deployment.materials
                if item.role != ("development_qrels" if final else "test_qrels")
            }
            dataset = root / "dataset" / "manifest.json"
            if not dataset.exists():
                prepare_data(
                    material["corpus"],
                    material["queries"],
                    material["test_qrels" if final else "development_qrels"],
                    "test" if final else "train",
                    dataset.parent,
                )
            manifest = load_manifest(dataset)
            expected = self.deployment.final if final else self.deployment.development
            if manifest != expected:
                raise ValueError("实际材料与部署manifest不同")
            workload = command.workload
            if isinstance(workload, DevelopmentWorkload):
                parents = [
                    self._materialize_result(p, inputs, root)
                    for p in workload.input_results
                ]
                result_paths.append(
                    self._run_config(
                        command,
                        dataset,
                        root / "development",
                        workload.config,
                        parents,
                        inputs.get(workload.program_ref),
                        inputs.get(workload.config_ref),
                    )
                )
            else:
                frozen = workload.frozen.frozen
                validate_final_dataset(frozen, manifest, prompts=self._prompts)
                freeze_dir = root / "frozen"
                if not freeze_dir.exists():
                    freeze_dir.mkdir()
                    write_json(freeze_dir / "frozen.json", frozen)
                    if workload.frozen.program_ref:
                        (freeze_dir / "program.py").write_bytes(
                            inputs[workload.frozen.program_ref].read_bytes()
                        )
                    if workload.frozen.config_ref:
                        (freeze_dir / "config.json").write_bytes(
                            inputs[workload.frozen.config_ref].read_bytes()
                        )
                # Explicit fixed final protocol: benchmark BM25, exact frozen parents, selected recipe.
                baseline_config = BM25Config(
                    method="bm25", retrieve_k=frozen.recipe.config.retrieve_k
                )
                recipes = list(frozen.inputs)
                benchmark = next(
                    (r for r in recipes if r.config == baseline_config), None
                )
                if benchmark is None and frozen.recipe.config == baseline_config:
                    benchmark = frozen.recipe
                base = run_baseline(
                    dataset,
                    root / "baseline",
                    baseline_config,
                    self._environment(command, bm25=True),
                    allow_test=True,
                    expected_elasticsearch=benchmark.implementation.elasticsearch
                    if benchmark
                    else None,
                )
                result_paths.append(base)
                parents = []
                for index, parent in enumerate(recipes):
                    if recipe(load_result(base)) == parent:
                        path = base
                    else:
                        path = run_baseline(
                            dataset,
                            root / f"parent-{index}",
                            parent.config,
                            self._environment(
                                command, bm25=parent.config.method == "bm25"
                            ),
                            allow_test=True,
                            expected_elasticsearch=parent.implementation.elasticsearch,
                        )
                        if recipe(load_result(path)) != parent:
                            raise ValueError("最终父结果生成规则与冻结身份不同")
                        result_paths.append(path)
                    parents.append(path)
                if recipe(load_result(base)) == frozen.recipe:
                    selected = base
                else:
                    selected = run_test(
                        freeze_dir / "frozen.json",
                        dataset,
                        parents,
                        root / "selected",
                        self._environment(
                            command, bm25=frozen.recipe.config.method == "bm25"
                        ),
                        self.deployment.candidate_image_id,
                    )
                    result_paths.append(selected)
                if recipe(load_result(selected)) != frozen.recipe:
                    raise ValueError("最终选中结果不符合原冻结")
            saved["status"] = "succeeded"
            saved["error_code"] = None
        except Exception as error:
            saved["failure_type"] = type(error).__name__
            saved["failure_detail"] = str(error)[:2048]
            jobs = self._jobs(root)
            status = (
                "unknown"
                if any(j.status == "unknown" for j in jobs)
                else (
                    "output_limit"
                    if any(j.status == "output_limit" for j in jobs)
                    else "timed_out"
                    if any(j.status == "timed_out" for j in jobs)
                    or datetime.now(timezone.utc) >= command.deadline_at
                    else "failed"
                )
            )
            saved["status"] = status
            saved["error_code"] = {
                "unknown": "backend_unknown",
                "output_limit": "output_limit",
                "timed_out": "deadline",
                "failed": "execution_failed",
            }[status]
        saved["elapsed_seconds"] = max(
            0.0,
            (datetime.now(timezone.utc) - saved["started_at"]).total_seconds(),
        )
        saved["result_paths"] = [str(path.relative_to(root)) for path in result_paths]
        _save_state(root, saved)
        return self._outcome(command, root, saved)

    def _run_config(
        self,
        command: ExperimentCommand,
        dataset: Path,
        output: Path,
        config: BM25Config | DenseConfig | RRFConfig | CandidateConfig,
        parents: list[Path],
        program: Path | None,
        config_file: Path | None,
    ) -> Path:
        environment = self._environment(command, bm25=config.method == "bm25")
        if isinstance(config, (BM25Config, DenseConfig)):
            return run_baseline(dataset, output, config, environment)
        if isinstance(config, RRFConfig):
            return run_rrf(dataset, parents, output, config, environment)
        if program is None:
            raise ValueError("候选没有确切源码")
        return run_candidate(
            dataset,
            parents,
            program,
            config_file,
            self.deployment.candidate_image_id,
            output,
            config,
            environment,
            timeout_seconds=self.deployment.limits.candidate_timeout_seconds,
        )

    def _jobs(self, root: Path) -> tuple[BackendJobFact, ...]:
        jobs = []
        for path in root.rglob("job.json"):
            if path.parent.name.startswith("."):
                continue
            row = read_json(path)
            if "container_name" not in row:
                continue
            candidate = "input_sha256" in row
            row = (
                asdict(TypeAdapter(_JobRecord).validate_python(row))
                if candidate
                else _WORKER_STATE.validate_python(row)
            )
            status = row.get("phase") if candidate else row.get("status")
            if status in {"prepared", "create_requested", "start_requested", "started"}:
                status = "unknown"
            if status == "exited":
                status = "succeeded" if row.get("exit_code") == 0 else "failed"
            elapsed = row.get("elapsed_seconds")
            if candidate and (path.parent / "result.json").is_file():
                elapsed = (
                    TypeAdapter(_SavedResult)
                    .validate_python(read_json(path.parent / "result.json"))
                    .elapsed_seconds
                )
            jobs.append(
                BackendJobFact(
                    job_key=row.get("job_key")
                    or canonical_digest(row["container_name"]),
                    role="candidate" if candidate else row["role"],
                    container_name=row["container_name"],
                    container_id=row.get("container_id") or None,
                    image_id=row["image_id"] or None,
                    status=status,
                    elapsed_seconds=elapsed,
                )
            )
        return tuple(jobs)

    def _capture_file(self, root: Path, relative: Path) -> Path | None:
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_path'))
        for part in (path, *path.parents):
            if part.is_symlink():
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_symlink'))
            if part == root:
                break
        if not path.exists():
            return None
        if not path.is_file():
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_file'))
        return path

    def _candidate_diagnostics(
        self,
        command: ExperimentCommand,
        root: Path,
        fact: ExperimentExecutionFact,
    ) -> tuple[BackendDiagnostic, ...]:
        if fact.status not in {"failed", "timed_out", "output_limit", "unknown"}:
            return ()
        workload = command.workload
        if isinstance(workload, DevelopmentWorkload):
            if not isinstance(workload.config, CandidateConfig):
                return ()
            directory = Path("development") / "execution"
            program_ref, config_ref = workload.program_ref, workload.config_ref
            input_count = len(workload.input_results)
        else:
            if not isinstance(workload.frozen.frozen.recipe.config, CandidateConfig):
                return ()
            directory = Path("selected") / "execution"
            program_ref = workload.frozen.program_ref
            config_ref = workload.frozen.config_ref
            input_count = len(workload.frozen.frozen.inputs)
        files = {
            name: self._capture_file(root, directory / name)
            for name in ("job.json", "result.json", "stdout.json", "stderr.log")
        }
        if files["result.json"] is None:
            if files["stdout.json"] is not None or files["stderr.log"] is not None:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_snapshot'))
            return ()
        if any(path is None for path in files.values()):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_original'))
        capture_files = {name: path for name, path in files.items() if path is not None}
        job = TypeAdapter(_JobRecord).validate_python(
            read_json(capture_files["job.json"])
        )
        saved = TypeAdapter(_SavedResult).validate_python(
            read_json(capture_files["result.json"])
        )
        resolved_after_capture = (
            saved.status == "unknown"
            and not saved.container_id
            and bool(job.container_id)
        )
        if (
            (job.container_id != saved.container_id and not resolved_after_capture)
            or job.image_id != saved.image_id
            or saved.stdout_file != "stdout.json"
            or saved.stderr_file != "stderr.log"
        ):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_job'))
        matching_jobs = [
            item
            for item in fact.jobs
            if item.role == "candidate" and item.job_key == job.job_key
        ]
        if (
            len(matching_jobs) != 1
            or not job.job_key
            or job.container_name != "retrieval-candidate-" + job.job_key[:40]
            or job.container_name != matching_jobs[0].container_name
            or (job.container_id or None) != matching_jobs[0].container_id
            or (job.image_id or None) != matching_jobs[0].image_id
            or (job.image_id and job.image_id != self.deployment.candidate_image_id)
        ):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_authorization'))
        bindings = {
            item.resource_ref: item.content_digest for item in command.bound_inputs
        }
        if program_ref is None or program_ref not in bindings:
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_source'))
        expected_roles = {
            "program.py",
            "queries.json",
            "corpus_ids.json",
            *(f"rankings_{index}.json" for index in range(input_count)),
        }
        if config_ref is not None:
            expected_roles.add("config.json")
        hashes = TypeAdapter(dict[str, Digest]).validate_python(job.input_sha256)
        if (
            set(hashes) != expected_roles
            or hashes["program.py"] != bindings[program_ref]
            or (
                config_ref is not None
                and hashes["config.json"] != bindings.get(config_ref)
            )
        ):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_input'))
        if isinstance(workload, FinalWorkload) and (
            hashes["program.py"] != workload.frozen.frozen.program_sha256
            or hashes.get("config.json", hashlib.sha256(b"").hexdigest())
            != workload.frozen.frozen.program_config_sha256
        ):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_freeze'))
        parent_hashes = []
        expected_rankings = {}
        if isinstance(workload, DevelopmentWorkload):
            for index, publication in enumerate(workload.input_results):
                parent_hashes.append(bindings[publication.raw_result_ref])
                expected_rankings[f"rankings_{index}.json"] = bindings[
                    publication.rankings_ref
                ]
            manifest = self.deployment.development
        else:
            baseline = self._capture_file(root, Path("baseline") / "result.json")
            if baseline is None:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_baseline'))
            baseline_result = ExperimentResult.model_validate(read_json(baseline))
            for index, parent in enumerate(workload.frozen.frozen.inputs):
                path = (
                    baseline
                    if recipe(baseline_result) == parent
                    else self._capture_file(
                        root, Path(f"parent-{index}") / "result.json"
                    )
                )
                if path is None:
                    raise ValueError(self._prompts.render('experiment_backend.diagnostic_parent'))
                result = ExperimentResult.model_validate(read_json(path))
                if recipe(result) != parent:
                    raise ValueError(self._prompts.render('experiment_backend.diagnostic_parent_recipe'))
                parent_hashes.append(sha256_file(path))
                expected_rankings[f"rankings_{index}.json"] = (
                    result.artifacts.rankings.sha256
                )
            manifest = self.deployment.final
        corpus_ids = (
            json.dumps(
                manifest.document_ids,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        expected_inputs = {
            **expected_rankings,
            "queries.json": manifest.artifact_sha256["queries.json"],
            "corpus_ids.json": hashlib.sha256(corpus_ids).hexdigest(),
        }
        expected_key = canonical_digest(
            {
                "command": command.command_digest,
                "program": bindings[program_ref],
                "config": bindings[config_ref]
                if config_ref is not None
                else hashlib.sha256(b"").hexdigest(),
                "inputs": parent_hashes,
            }
        )
        if job.job_key != expected_key or any(
            hashes[name] != digest for name, digest in expected_inputs.items()
        ):
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_digest'))
        stdout_limit = min(job.limits.stdout_bytes, self.deployment.limits.stdout_bytes)
        stderr_limit = min(job.limits.stderr_bytes, self.deployment.limits.stderr_bytes)
        captures = {}
        for name, size, limit in (
            ("stdout.json", saved.stdout_bytes, stdout_limit),
            ("stderr.log", saved.stderr_bytes, stderr_limit),
        ):
            path = capture_files[name]
            if size < 0 or size > limit or path.stat().st_size != size:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_size'))
            with path.open("rb") as stream:
                captures[name] = stream.read(limit + 1)
            if len(captures[name]) != size:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_changed'))
        stdout, stderr = captures["stdout.json"], captures["stderr.log"]
        if hashlib.sha256(stdout).hexdigest() != saved.stdout_sha256:
            raise ValueError(self._prompts.render('experiment_backend.diagnostic_stdout_digest'))
        if resolved_after_capture:
            if stdout or stderr:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_unknown_nonempty'))
            return ()
        if not job.container_id or not job.image_id:
            if stdout or stderr:
                raise ValueError(self._prompts.render('experiment_backend.diagnostic_unbound_nonempty'))
            return ()
        stdout_limitations = ()
        try:
            stdout.decode("utf-8", errors="strict")
            stdout_type, stdout_suffix = "text/plain", "txt"
        except UnicodeDecodeError:
            stdout_type, stdout_suffix = "application/octet-stream", "bin"
            stdout_limitations = (
                self._prompts.render('experiment_backend.stdout_encoding'),
            )
        replaced = False
        try:
            stderr_text = stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            stderr_text = stderr.decode("utf-8", errors="replace")
            replaced = True
        stderr_projection = stderr_text.encode("utf-8")
        truncated = len(stderr_projection) > stderr_limit
        if truncated:
            stderr_projection = (
                stderr_projection[:stderr_limit]
                .decode("utf-8", errors="ignore")
                .encode("utf-8")
            )
        prefix = "candidate-" + job.job_key[:16]
        return (
            BackendDiagnostic(
                filename=f"{prefix}-stdout.{stdout_suffix}",
                content_type=stdout_type,
                content=stdout,
                limitations=stdout_limitations,
            ),
            BackendDiagnostic(
                filename=f"{prefix}-stderr.txt",
                content_type="text/plain",
                content=stderr_projection,
                limitations=(
                    self._prompts.render('experiment_backend.stderr_projection')
                    + (self._prompts.render('experiment_backend.stderr_replaced') if replaced else self._prompts.render('experiment_backend.stderr_not_replaced'))
                    + (
                        self._prompts.render('experiment_backend.stderr_truncated')
                        if truncated
                        else self._prompts.render('experiment_backend.stderr_not_truncated')
                    ),
                ),
            ),
        )

    def _outcome(
        self, command: ExperimentCommand, root: Path, saved: _ExecutionState
    ) -> BackendOutcome:
        bundles = []
        manifest = (
            load_manifest(root / "dataset" / "manifest.json", prompts=self._prompts)
            if saved.get("result_paths")
            else None
        )
        for relative in saved.get("result_paths", []):
            path = (root / relative).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError(self._prompts.render('experiment_backend.result_path'))
            result = load_result(path, prompts=self._prompts)
            bundles.append(
                ResultBundle(
                    result=result,
                    result_bytes=path.read_bytes(),
                    corpus_bytes=(root / "dataset" / "corpus.json").read_bytes(),
                    queries_bytes=(root / "dataset" / "queries.json").read_bytes(),
                    **{
                        name: (path.parent / f"{name}.json").read_bytes()
                        for name in ("rankings", "coverage", "metrics", "per_query")
                    },
                )
            )
        if manifest:
            for bundle in bundles:
                for name, content in (
                    ("corpus", bundle.corpus_bytes),
                    ("queries", bundle.queries_bytes),
                ):
                    if (
                        hashlib.sha256(content).hexdigest()
                        != manifest.artifact_sha256[f"{name}.json"]
                    ):
                        raise ValueError(self._prompts.render('experiment_backend.public_projection'))
        fact = ExperimentExecutionFact(
            status=saved["status"],
            jobs=self._jobs(root),
            elapsed_seconds=saved.get("elapsed_seconds"),
            error_code=saved.get("error_code"),
        )
        diagnostic = BackendDiagnostic(
            filename="execution.json",
            content_type="application/json",
            content=fact.model_dump_json().encode("utf-8"),
        )
        return BackendOutcome(
            execution=fact,
            results=tuple(bundles),
            diagnostics=(diagnostic, *self._candidate_diagnostics(command, root, fact)),
        )

    def cleanup(self, command: ExperimentCommand) -> None:
        import docker

        root = self._root(command)
        saved = _read_state(root)
        if saved["status"] == "unknown":
            return
        errors: list[str] = []
        with closing(_docker_client(self.environment.endpoint)) as client:
            for job in self._jobs(root):
                if job.status in {"running", "created", "unknown"}:
                    continue
                confirmed_unstarted = False
                if job.role != "candidate":
                    for state_path in root.rglob("job.json"):
                        raw = read_json(state_path)
                        if (
                            raw.get("container_name") == job.container_name
                            and "input_sha256" not in raw
                        ):
                            worker_state = _WORKER_STATE.validate_python(raw)
                            confirmed_unstarted = (
                                worker_state["start_requested"] is False
                            )
                            break
                removed = False
                try:
                    container = client.containers.get(job.container_name)
                    container.reload()
                    if (
                        container.attrs.get("Image") == job.image_id
                        and container.id == job.container_id
                        and (
                            container.status in {"exited", "dead"}
                            or (container.status == "created" and confirmed_unstarted)
                        )
                    ):
                        container.remove()
                        removed = True
                except docker.errors.NotFound:
                    removed = True
                except docker.errors.DockerException as error:
                    errors.append(f"{job.job_key}: {type(error).__name__}")
                    continue
                if removed and job.role == "candidate":
                    for path in root.rglob("job.json"):
                        if path.parent.name.startswith("."):
                            continue
                        raw = read_json(path)
                        if raw.get("container_name") != job.container_name:
                            continue
                        record = TypeAdapter(_JobRecord).validate_python(raw)
                        staging = Path(record.staging_directory)
                        try:
                            if staging.exists():
                                _remove_staging(staging)
                            record.container_removed = True
                            replace_json(path, asdict(record))
                        except (OSError, RuntimeError) as error:
                            errors.append(f"{job.job_key}: {type(error).__name__}")
        saved["cleanup_errors"] = errors
        _save_state(root, saved)
