"""受信操作者的实验控制端；不提供生产授权或 Agent 决策。"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal
from typing_extensions import NotRequired, TypedDict

import docker
from pydantic import AwareDatetime, Field, TypeAdapter

from .contracts import (
    BaselineJob,
    RRFJob,
    ScoreJob,
)
from .file_io import (
    read_json,
    sha256_file,
    write_json,
)
from personal_agent.application.retrieval_experiment.contracts import (
    BM25Config,
    CandidateConfig,
    CandidateIdentity,
    Coverage,
    DatasetManifest,
    DenseConfig,
    Digest,
    ElasticsearchIdentity,
    ExperimentResult,
    Identifier,
    RRFConfig,
    StrictModel,
    FrozenExperiment,
    canonical_digest,
)
from personal_agent.infra.python_execution.sandbox import SandboxLimits, run_program
from personal_agent.application.retrieval_experiment.rules import (
    recipe as _recipe,
    freeze_experiment,
    validate_final_dataset,
    validate_final_result,
)


class ExecutionEnvironment(StrictModel):
    endpoint: Identifier
    image: Identifier
    network: Identifier = "none"
    es_endpoint: Identifier | None = None
    model_path: Path | None = None
    model_revision: Identifier | None = None
    timeout_seconds: Annotated[float, Field(gt=0, le=1200, allow_inf_nan=False)] = 1200
    command_digest: Digest | None = None
    deadline_at: AwareDatetime | None = None
    retain_jobs: bool = False
    worker_memory_mb: Annotated[int, Field(strict=True, gt=0)] = 4096
    worker_cpus: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 4
    worker_pids: Annotated[int, Field(strict=True, gt=0)] = 128
    candidate_memory_mb: Annotated[int, Field(strict=True, gt=0)] = 512
    candidate_cpus: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1
    candidate_pids: Annotated[int, Field(strict=True, gt=0)] = 64
    candidate_scratch_mb: Annotated[int, Field(strict=True, gt=0)] = 32
    stdout_bytes: Annotated[int, Field(strict=True, gt=0)] = 16 * 1024 * 1024
    stderr_bytes: Annotated[int, Field(strict=True, gt=0)] = 64 * 1024


class _WorkerState(TypedDict):
    job_key: Digest
    role: Literal["baseline", "rrf", "score"]
    container_name: Identifier
    container_id: str | None
    image_id: Identifier
    input_hashes: dict[str, Digest]
    status: Literal[
        "prepared", "running", "succeeded", "failed", "timed_out", "unknown"
    ]
    create_requested: bool
    start_requested: bool
    exit_code: NotRequired[int]
    backend_state: NotRequired[str]
    elapsed_seconds: NotRequired[Annotated[float, Field(ge=0, allow_inf_nan=False)]]
    container_removed: NotRequired[bool]


_WORKER_STATE = TypeAdapter(_WorkerState)


def _new_directory(path: Path) -> Path:
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def load_manifest(path: Path) -> DatasetManifest:
    manifest = DatasetManifest.model_validate(read_json(path))
    for name, expected in manifest.artifact_sha256.items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"数据产物摘要不匹配：{name}")
    return manifest


def load_result(path: Path) -> ExperimentResult:
    result = ExperimentResult.model_validate(read_json(path))
    for artifact in (
        result.artifacts.rankings,
        result.artifacts.coverage,
        result.artifacts.metrics,
        result.artifacts.per_query,
    ):
        if sha256_file(path.parent / artifact.path) != artifact.sha256:
            raise ValueError(f"结果产物摘要不匹配：{artifact.path}")
    return result


def _image_id(environment: ExecutionEnvironment, reference: str | None = None) -> str:
    if reference is not None and not reference.strip():
        raise ValueError("镜像引用不能为空")
    with closing(_docker_client(environment.endpoint)) as client:
        image = client.images.get(environment.image if reference is None else reference)
        # Docker's containerd store can discard an untagged OCI image index
        # when a build tag moves. Retain the exact local snapshot for freezing.
        retention_tag = "sha256-" + image.id.removeprefix("sha256:")
        if not image.tag("personal-agent-retrieval-snapshots", retention_tag):
            raise RuntimeError("无法保留确切执行镜像，拒绝启动不可复现作业")
        return image.id


def _docker_client(endpoint: str) -> docker.DockerClient:
    client = docker.DockerClient(base_url=endpoint, version="1.44", timeout=10)
    client.api.trust_env = False
    return client


def _worker(
    job: BaselineJob | RRFJob | ScoreJob,
    dataset: Path,
    output: Path,
    environment: ExecutionEnvironment,
    mounts: dict[str, Path] | None = None,
) -> Path:
    """固定worker；稳定身份先落盘，生产结果提交后才移除容器。"""
    from .file_io import replace_json

    started = time.monotonic()
    input_hashes = {"manifest": sha256_file(dataset)}
    for name, digest in load_manifest(dataset).artifact_sha256.items():
        input_hashes[name] = digest
    for target, source in (mounts or {}).items():
        input_hashes[target] = canonical_digest(
            {
                path.relative_to(source).as_posix(): sha256_file(path)
                for path in sorted(source.rglob("*"))
                if path.is_file()
            }
        )
    key = canonical_digest(
        {
            "command": environment.command_digest,
            "job": job.model_dump(mode="json"),
            "inputs": input_hashes,
        }
    )
    name = (
        f"retrieval-{job.mode}-{key[:40]}"
        if environment.command_digest
        else f"retrieval-trusted-{uuid.uuid4().hex}"
    )
    output = output.resolve()
    state_path = output / "job.json"
    job_dir = output.parent / ("." + output.name + "-job")
    if output.exists():
        if not environment.command_digest or not state_path.is_file():
            raise ValueError("输出目录已存在但没有可恢复作业身份")
        state = _WORKER_STATE.validate_python(read_json(state_path))
        if state.get("job_key") != key or state.get("input_hashes") != input_hashes:
            raise ValueError("已有作业的输入身份不一致")
        if state.get("status") == "succeeded":
            load_result(output / "result.json")
            return output / "result.json"
        if state.get("status") in {"failed", "timed_out"}:
            raise RuntimeError("原作业已确定失败，禁止重新执行")
    else:
        output.mkdir(parents=True)
        state = {
            "job_key": key,
            "role": job.mode,
            "container_name": name,
            "container_id": None,
            "image_id": job.image_id,
            "input_hashes": input_hashes,
            "status": "prepared",
            "create_requested": False,
            "start_requested": False,
        }
        replace_json(state_path, state)
    job_dir.mkdir(exist_ok=True)
    job_file = job_dir / "job.json"
    if job_file.exists():
        if read_json(job_file) != job.model_dump(mode="json"):
            raise ValueError("固定worker请求发生变化")
    else:
        write_json(job_file, job)
    volumes = {
        str(dataset.resolve().parent): {"bind": "/dataset", "mode": "ro"},
        str(job_dir): {"bind": "/job", "mode": "ro"},
        str(output): {"bind": "/output", "mode": "rw"},
    }
    for target, source in (mounts or {}).items():
        volumes[str(source.resolve())] = {"bind": target, "mode": "ro"}
    labels = {
        "personal-agent.command": environment.command_digest or key,
        "personal-agent.job": key,
        "personal-agent.inputs": canonical_digest(input_hashes),
    }
    terminal = False
    container = None
    with closing(_docker_client(environment.endpoint)) as client:
        try:
            if state["create_requested"]:
                container = client.containers.get(name)
            else:
                if (
                    environment.deadline_at
                    and datetime.now(timezone.utc) >= environment.deadline_at
                ):
                    state["status"] = "timed_out"
                    raise TimeoutError("原实验deadline已到，未启动worker")
                state["create_requested"] = True
                replace_json(state_path, state)
                container = client.containers.create(
                    image=job.image_id,
                    command=["/job/job.json"],
                    name=name,
                    volumes=volumes,
                    network_mode=environment.network,
                    read_only=True,
                    user="65534:65534",
                    cap_drop=["ALL"],
                    use_config_proxy=False,
                    security_opt=["no-new-privileges:true"],
                    mem_limit=environment.worker_memory_mb * 1024 * 1024,
                    nano_cpus=int(environment.worker_cpus * 1_000_000_000),
                    pids_limit=environment.worker_pids,
                    tmpfs={"/tmp": "rw,noexec,nosuid,size=256m,mode=1777"},
                    restart_policy={"Name": "no"},
                    labels=labels,
                    log_config=docker.types.LogConfig(
                        type="json-file", config={"max-size": "1m", "max-file": "1"}
                    ),
                )
            container.reload()
            if container.attrs.get("Image") != job.image_id or any(
                container.labels.get(k) != v for k, v in labels.items()
            ):
                container = None
                raise ValueError("后端作业与原镜像/输入绑定不同")
            state["container_id"] = container.id
            if container.status == "created":
                if state["start_requested"]:
                    raise RuntimeError("原start结果未知，禁止重启")
                if environment.deadline_at and datetime.now(timezone.utc) >= environment.deadline_at:
                    state["status"] = "timed_out"
                    raise TimeoutError("原实验deadline已到，未启动worker")
                state["start_requested"] = True
                replace_json(state_path, state)
                container.start()
            state["status"] = "running"
            replace_json(state_path, state)
            while True:
                container.reload()
                if container.status in {"exited", "dead"}:
                    terminal = True
                    break
                expired = (
                    datetime.now(timezone.utc) >= environment.deadline_at
                    if environment.deadline_at
                    else time.monotonic() - started >= environment.timeout_seconds
                )
                if expired:
                    state["status"] = "timed_out"
                    container.kill()
                    container.reload()
                    terminal = container.status in {"exited", "dead"}
                    break
                time.sleep(0.25)
            if not terminal:
                raise RuntimeError("作业终态未知")
            (output / "worker.log").write_bytes(container.logs(tail=200)[-65536:])
            state["exit_code"] = container.attrs["State"]["ExitCode"]
            if state["status"] != "timed_out":
                state["status"] = "succeeded" if state["exit_code"] == 0 else "failed"
            state["backend_state"] = container.status
            if state["status"] != "succeeded":
                raise RuntimeError("受信实验作业未成功")
            load_result(output / "result.json")
            return output / "result.json"
        except BaseException:
            if container is None and state["create_requested"]:
                try:
                    container = client.containers.get(name)
                    container.reload()
                    if container.attrs.get("Image") != job.image_id or any(
                        container.labels.get(k) != v for k, v in labels.items()
                    ):
                        container = None
                except docker.errors.DockerException:
                    container = None
            if container is not None and not terminal:
                try:
                    container.reload()
                    if container.status not in {"exited", "dead", "created"}:
                        container.kill()
                        container.reload()
                    terminal = container.status in {"exited", "dead"} or (
                        container.status == "created" and not state["start_requested"]
                    )
                    state["container_id"] = container.id
                    state["backend_state"] = container.status
                except docker.errors.DockerException:
                    terminal = False
            if not terminal and state["create_requested"]:
                state["status"] = "unknown"
            elif state["status"] not in {"failed", "timed_out"}:
                state["status"] = "failed"
            raise
        finally:
            state["elapsed_seconds"] = (
                state.get("elapsed_seconds", 0) + time.monotonic() - started
            )
            replace_json(state_path, state)
            if terminal and container is not None and not environment.retain_jobs:
                container.remove()
                state["container_removed"] = True
                replace_json(state_path, state)


def run_baseline(
    dataset: Path,
    output: Path,
    config: BM25Config | DenseConfig,
    environment: ExecutionEnvironment,
    *,
    allow_test: bool = False,
    expected_elasticsearch: ElasticsearchIdentity | None = None,
) -> Path:
    manifest = load_manifest(dataset)
    if manifest.split == "test" and not allow_test:
        raise ValueError("test 必须使用 test --frozen 入口")
    image_id = _image_id(environment)
    mounts: dict[str, Path] = {}
    if isinstance(config, BM25Config):
        if environment.network == "none" or not environment.es_endpoint:
            raise ValueError("BM25 需要独立实验 Elasticsearch endpoint 及专用网络")
    else:
        if environment.model_path is None or not environment.model_revision:
            raise ValueError("dense 需要本地模型快照及确切 revision")
        mounts["/model"] = environment.model_path
    job = BaselineJob(
        mode="baseline",
        manifest_path="/dataset/manifest.json",
        output_dir="/output",
        config=config,
        image_id=image_id,
        es_endpoint=environment.es_endpoint if isinstance(config, BM25Config) else None,
        index_name="retrieval-experiment-"
        + (
            canonical_digest(
                {
                    "command": environment.command_digest,
                    "config": config.model_dump(mode="json"),
                    "dataset": manifest.split_id,
                }
            )[:40]
            if environment.command_digest
            else uuid.uuid4().hex
        )
        if isinstance(config, BM25Config)
        else None,
        model_path="/model" if mounts else None,
        model_revision=environment.model_revision
        if isinstance(config, DenseConfig)
        else None,
        expected_elasticsearch=expected_elasticsearch,
    )
    return _worker(job, dataset, output, environment, mounts)


def _bound_inputs(
    dataset: Path, inputs: list[Path]
) -> tuple[list[ExperimentResult], dict[str, Path]]:
    manifest = load_manifest(dataset)
    results = [load_result(path) for path in inputs]
    for result in results:
        if (
            result.dataset.dataset_id != manifest.dataset_id
            or result.dataset.split_id != manifest.split_id
        ):
            raise ValueError("输入排名来自不同数据快照或 split")
    return results, {
        f"/result_{index}": path.resolve().parent for index, path in enumerate(inputs)
    }


def run_rrf(
    dataset: Path,
    inputs: list[Path],
    output: Path,
    config: RRFConfig,
    environment: ExecutionEnvironment,
    *,
    allow_test: bool = False,
) -> Path:
    if load_manifest(dataset).split == "test" and not allow_test:
        raise ValueError("test 必须使用 test --frozen 入口")
    _, mounts = _bound_inputs(dataset, inputs)
    return _worker(
        RRFJob(
            mode="rrf",
            manifest_path="/dataset/manifest.json",
            output_dir="/output",
            config=config,
            input_results=tuple(f"/result_{i}/result.json" for i in range(len(inputs))),
            image_id=_image_id(environment),
        ),
        dataset,
        output,
        environment,
        mounts,
    )


def rescore(
    dataset: Path, source: Path, output: Path, environment: ExecutionEnvironment
) -> Path:
    _, mounts = _bound_inputs(dataset, [source])
    return _worker(
        ScoreJob(
            mode="score",
            manifest_path="/dataset/manifest.json",
            output_dir="/output",
            image_id=_image_id(environment),
            input_result="/result_0/result.json",
        ),
        dataset,
        output,
        environment,
        mounts,
    )


def run_candidate(
    dataset: Path,
    inputs: list[Path],
    program: Path,
    config_file: Path | None,
    candidate_image: str,
    output: Path,
    config: CandidateConfig,
    environment: ExecutionEnvironment,
    *,
    timeout_seconds: float = 60,
    allow_test: bool = False,
    expected_program_sha256: str | None = None,
    expected_config_sha256: str | None = None,
) -> Path:
    if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 1200:
        raise ValueError("候选 timeout 必须大于 0 且不超过 1200 秒")
    manifest = load_manifest(dataset)
    if manifest.split == "test" and not allow_test:
        raise ValueError("test 必须使用 test --frozen 入口")
    results, input_mounts = _bound_inputs(dataset, inputs)
    if len(results) < 2 or any(
        result.config.retrieve_k < config.retrieve_k for result in results
    ):
        raise ValueError("候选需要至少两份深度充分的完整输入排名")
    candidate_image_id = _image_id(environment, candidate_image)
    if output.exists() and environment.command_digest:
        if sha256_file(output / "program.py") != sha256_file(program):
            raise ValueError("恢复源码与原快照不符")
    else:
        _new_directory(output)
        shutil.copyfile(program, output / "program.py")
    if config_file:
        read_json(config_file)
        if (output / "config.json").exists():
            if sha256_file(output / "config.json") != sha256_file(config_file):
                raise ValueError("恢复配置与原快照不符")
        else:
            shutil.copyfile(config_file, output / "config.json")
    program_sha256 = sha256_file(output / "program.py")
    config_sha256 = (
        sha256_file(output / "config.json")
        if config_file
        else hashlib.sha256(b"").hexdigest()
    )
    if (
        expected_program_sha256 is not None
        and program_sha256 != expected_program_sha256
    ) or (
        expected_config_sha256 is not None and config_sha256 != expected_config_sha256
    ):
        raise ValueError("本次执行源码或配置与冻结快照不一致")
    with tempfile.TemporaryDirectory(prefix="retrieval-inputs-") as temporary:
        staging = Path(temporary)
        write_json(staging / "corpus_ids.json", manifest.document_ids)
        bindings = {
            f"rankings_{i}.json": path.parent / "rankings.json"
            for i, path in enumerate(inputs)
        }
        bindings["queries.json"] = dataset.parent / "queries.json"
        bindings["corpus_ids.json"] = staging / "corpus_ids.json"
        if config_file:
            bindings["config.json"] = output / "config.json"
        execution = run_program(
            endpoint=environment.endpoint,
            image=candidate_image_id,
            program=output / "program.py",
            inputs=bindings,
            output_dir=output / "execution",
            limits=SandboxLimits(
                timeout_seconds=timeout_seconds,
                memory_mb=environment.candidate_memory_mb,
                cpus=environment.candidate_cpus,
                pids_limit=environment.candidate_pids,
                scratch_mb=environment.candidate_scratch_mb,
                stdout_bytes=environment.stdout_bytes,
                stderr_bytes=environment.stderr_bytes,
            ),
            job_key=canonical_digest(
                {
                    "command": environment.command_digest,
                    "program": program_sha256,
                    "config": config_sha256,
                    "inputs": [sha256_file(p) for p in inputs],
                }
            )
            if environment.command_digest
            else None,
            deadline_at=environment.deadline_at,
            retain_jobs=environment.retain_jobs,
        )
    if execution.status != "succeeded":
        raise RuntimeError(
            f"候选执行未成功：{execution.status}；作业 {execution.container_id}"
        )
    # 排名只从已确认终态的原始响应导入。评分器拒绝额外字段和自报指标。
    rankings_path = output / "execution" / "stdout.json"
    if rankings_path.read_bytes() != execution.stdout:
        raise ValueError("候选 stdout 保存身份不一致")
    candidate = CandidateIdentity(
        source_sha256=program_sha256,
        config_sha256=config_sha256,
        image_id=execution.image_id,
        job_id=execution.container_id,
        stdout_sha256=sha256_file(rankings_path),
        timeout_seconds=timeout_seconds,
    )
    path = _worker(
        ScoreJob(
            mode="score",
            manifest_path="/dataset/manifest.json",
            output_dir="/output",
            image_id=_image_id(environment),
            candidate_rankings_path="/candidate/stdout.json",
            config=config,
            candidate_identity=candidate,
            input_results=tuple(f"/result_{i}/result.json" for i in range(len(inputs))),
        ),
        dataset,
        output / "scored",
        environment,
        {"/candidate": rankings_path.parent, **input_mounts},
    )
    # 本次真实输入引用保存在控制端；冻结必须据这些确切结果恢复生成规则。
    if not (output / "inputs.json").exists():
        write_json(output / "inputs.json", tuple(str(p.resolve()) for p in inputs))
    return path


def freeze(source: Path, inputs: list[Path], output: Path) -> Path:
    result = load_result(source)
    coverage = Coverage.model_validate(
        read_json(source.parent / result.artifacts.coverage.path)
    )
    parents = tuple(load_result(path) for path in inputs)
    program = source.parent.parent / "program.py"
    configuration = source.parent.parent / "config.json"
    frozen = freeze_experiment(
        result,
        sha256_file(source),
        coverage,
        parents,
        tuple(sha256_file(path) for path in inputs),
        program_digest=sha256_file(program) if result.candidate else None,
        config_digest=(
            sha256_file(configuration)
            if configuration.exists()
            else hashlib.sha256(b"").hexdigest()
        )
        if result.candidate
        else None,
    )
    _new_directory(output)
    if result.candidate:
        shutil.copyfile(program, output / "program.py")
        if configuration.exists():
            shutil.copyfile(configuration, output / "config.json")
    path = output / "frozen.json"
    write_json(path, frozen)
    return path


def run_test(
    frozen_path: Path,
    dataset: Path,
    inputs: list[Path],
    output: Path,
    environment: ExecutionEnvironment,
    candidate_image: str | None,
) -> Path:
    frozen = FrozenExperiment.model_validate(read_json(frozen_path))
    manifest = load_manifest(dataset)
    validate_final_dataset(frozen, manifest)
    if _image_id(environment) != frozen.recipe.implementation.image_id:
        raise ValueError("受信执行镜像与冻结版本不一致")
    environment = environment.model_copy(
        update={"image": frozen.recipe.implementation.image_id}
    )
    parents, _ = _bound_inputs(dataset, inputs)
    if tuple(_recipe(parent) for parent in parents) != frozen.inputs:
        raise ValueError("test 输入排名的配置、模型或实现与冻结生成规则不一致")
    configuration = frozen.recipe.config
    if isinstance(configuration, (BM25Config, DenseConfig)):
        if isinstance(configuration, DenseConfig):
            if environment.model_path is None or frozen.recipe.model is None:
                raise ValueError("冻结 dense 模型不可用")
            model_hashes = {
                path.relative_to(environment.model_path).as_posix(): sha256_file(path)
                for path in sorted(environment.model_path.rglob("*"))
                if path.is_file()
            }
            if (
                environment.model_revision != frozen.recipe.model.revision
                or canonical_digest(model_hashes) != frozen.recipe.model.sha256
            ):
                raise ValueError("模型快照或 revision 与冻结版本不一致")
        path = run_baseline(
            dataset,
            output,
            configuration,
            environment,
            allow_test=True,
            expected_elasticsearch=frozen.recipe.implementation.elasticsearch,
        )
    elif isinstance(configuration, RRFConfig):
        path = run_rrf(
            dataset, inputs, output, configuration, environment, allow_test=True
        )
    else:
        if not candidate_image:
            raise ValueError("候选 test 需要固定 candidate-image")
        if frozen.candidate_timeout_seconds is None:
            raise ValueError("冻结候选缺少执行时限")
        with closing(_docker_client(environment.endpoint)) as client:
            if client.images.get(candidate_image).id != frozen.candidate_image_id:
                raise ValueError("候选镜像与冻结版本不一致")
        program = frozen_path.parent / "program.py"
        candidate_configuration = frozen_path.parent / "config.json"
        if sha256_file(program) != frozen.program_sha256:
            raise ValueError("冻结后的候选源码已变化")
        observed = (
            sha256_file(candidate_configuration)
            if candidate_configuration.exists()
            else hashlib.sha256(b"").hexdigest()
        )
        if observed != frozen.program_config_sha256:
            raise ValueError("冻结后的候选配置已变化")
        path = run_candidate(
            dataset,
            inputs,
            program,
            candidate_configuration if candidate_configuration.exists() else None,
            frozen.candidate_image_id,
            output,
            configuration,
            environment,
            timeout_seconds=frozen.candidate_timeout_seconds,
            allow_test=True,
            expected_program_sha256=frozen.program_sha256,
            expected_config_sha256=frozen.program_config_sha256,
        )
    actual = load_result(path)
    validate_final_result(frozen, actual)
    binding = {
        "frozen_sha256": sha256_file(frozen_path),
        "development_result_sha256": frozen.development_result_sha256,
        "test_split_id": manifest.split_id,
    }
    binding_path = path.parent / "frozen_binding.json"
    if binding_path.exists():
        if read_json(binding_path) != binding:
            raise ValueError("已存在的冻结绑定不同")
    else:
        write_json(binding_path, binding)
    return path
