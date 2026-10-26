"""串行执行固定 LongDS v1.1 Lite 原题，保留每项独立采集和评分。"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import file_digest, sha1, sha256
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from time import sleep
from typing import Literal
from urllib.parse import quote
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from personal_agent.kernel.config import Settings

from .longds_judge import JudgeScoreReport, MeteredJudge, score
from .longds_materials import (
    DATASET_REVISION, TASK_NAME, LongDSInput, LongDSPreparation, LongDSTurn,
    json_bytes, seal, verify_preparation, verify_seal,
)
from .run_longds import ROOT, LongDSCapture, _configuration, _source_identity, _source_paths, baseline


LITE_SHA256 = "51f03d65ce3149ae36fb283140ee9aaffca77d9d3bb13d5487d6cf04d443931f"
SOURCE_DIRECTORY = ROOT / ".tmp/longds-design-20261023"
QUALIFICATION = ROOT / ".tmp/longds-implementation-20261023/judge/qualification"
REFERENCE_CONFIGURATION = ROOT / ".tmp/lv4/preparation-identity.json"
TOKEN_LIMIT = 60_000_000


class TaskIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_domain: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    dataset_name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    task_id: str = Field(pattern=r"^task[0-9]+$")

    @property
    def key(self) -> str:
        return f"{self.task_domain}/{self.dataset_name}/{self.task_id}"


class LFSIdentity(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    oid: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class SourceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    type: Literal["file", "directory"]
    path: str
    oid: str = Field(pattern=r"^[0-9a-f]{40}$")
    size: int = Field(ge=0)
    lfs: LFSIdentity | None = None


class TaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task: TaskIdentity
    status: Literal["completed", "capture_failed", "preparation_failed", "score_failed"]
    planned_turns: int
    capture: LongDSCapture | None = None
    judged_turns: int = 0
    correct_turns: int = 0
    known_judge_tokens: int = 0
    unknown_judge_attempts: int = 0
    exception_type: str | None = None


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task: TaskIdentity
    task_url: str
    task_sha256: str
    input_tree_url: str
    input_tree_sha256: str


class SuiteProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_revision: str = DATASET_REVISION
    version: Literal["v1.1"] = "v1.1"
    split: Literal["lite"] = "lite"
    language: Literal["en"] = "en"
    evidence_class: Literal["unverified_flow_capture"] = "unverified_flow_capture"
    release_eligible: Literal[False] = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tasks: tuple[TaskIdentity, ...]
    planned_turns: int
    source_digest: str
    configuration_digest: str
    current_task: str | None = None
    results: tuple[TaskResult, ...] = ()
    state: Literal["running", "paused", "finished"] = "running"
    stop_reason: str = "running"


def _write(path: Path, value: BaseModel) -> None:
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def collect(root: Path) -> tuple[TaskIdentity, ...]:
    source = (root / "task_list_lite.json").read_bytes()
    if sha256(source).hexdigest() != LITE_SHA256:
        raise ValueError("Lite清单不属于固定的官方数据版本")
    tasks = TypeAdapter(tuple[TaskIdentity, ...]).validate_json(source)
    if len(tasks) != 24 or len({t.key for t in tasks}) != 24 or TASK_NAME not in {t.key for t in tasks}:
        raise ValueError("Lite官方清单身份或数量不符")
    return tuple(t for t in tasks if t.key != TASK_NAME)


def source_turns(root: Path, task: TaskIdentity) -> tuple[LongDSTurn, ...]:
    source = json.loads((root / "sources" / task.key / "task.json").read_bytes())
    return tuple(LongDSTurn.model_validate({k: row[k] for k in ("turn_id", "context", "question")}) for row in source)


def _digest_file(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return file_digest(stream, algorithm).hexdigest()


def _git_blob(path: Path) -> str:
    digest = sha1(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_data(path: Path, entry: SourceEntry) -> bool:
    if not path.is_file() or path.stat().st_size != entry.size:
        return False
    if entry.lfs is not None:
        return entry.size == entry.lfs.size and _digest_file(path) == entry.lfs.oid
    return _git_blob(path) == entry.oid


def _download(path: Path, entry: SourceEntry) -> str:
    url = f"https://huggingface.co/datasets/zjunlp/LongDS/resolve/{DATASET_REVISION}/{quote(entry.path, safe='/')}"
    if _valid_data(path, entry):
        return url
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".download")
    for attempt in range(3):
        try:
            with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            if not _valid_data(temporary, entry):
                raise ValueError("下载文件与官方Git blob或LFS身份不符")
            temporary.replace(path)
            return url
        except (OSError, ValueError):
            if attempt == 2:
                raise
            sleep(2 ** attempt)
    raise RuntimeError("下载重试边界失效")


def prepare_original(root: Path, task: TaskIdentity, directory: Path) -> LongDSPreparation:
    source = root / "sources" / task.key
    entries = TypeAdapter(tuple[SourceEntry, ...]).validate_json((source / "input-tree.json").read_bytes())
    prefix = f"data/longds/{task.key}/data/"
    raw = root / "downloads"
    inputs: list[LongDSInput] = []
    data_paths: list[tuple[Path, str, str]] = []
    for entry in entries:
        if not entry.path.startswith(prefix):
            raise ValueError("输入数据目录越过该项固定来源")
        relative = PurePosixPath(entry.path[len(prefix):])
        if relative.is_absolute() or not relative.parts or any(p in (".", "..") or ":" in p or "\\" in p for p in relative.parts):
            raise ValueError("输入数据路径不安全")
        if entry.type != "file":
            continue
        target = raw / (entry.lfs.oid if entry.lfs is not None else entry.oid)
        if not target.is_relative_to(raw.resolve()):
            raise ValueError("输入数据本地路径越界")
        url = _download(target, entry)
        data_paths.append((target, relative.as_posix(), url))
        print("data_ready", task.key, relative.as_posix(), target.stat().st_size, flush=True)
    if not data_paths:
        raise ValueError("官方任务没有输入文件")
    directory.mkdir(parents=True, exist_ok=False)
    private = directory / "evaluator-private"
    private.mkdir()
    shutil.copyfile(source / "task.json", private / "task.json")
    shutil.copyfile(source / "input-tree.json", private / "input-tree.json")
    data = directory / "data"
    data.mkdir()
    if any("/" in name for _, name, _ in data_paths):
        archive = data / "longds-data.zip"
        with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=6) as output:
            for path, name, _ in data_paths:
                output.write(path, name)
        inputs.append(LongDSInput(filename=archive.name, bytes=archive.stat().st_size,
            git_blob=_git_blob(archive), sha256=_digest_file(archive), url="archive:official-data-tree"))
    else:
        for path, name, url in data_paths:
            shutil.copyfile(path, data / name)
            inputs.append(LongDSInput(filename=name, bytes=path.stat().st_size,
                git_blob=_git_blob(path), sha256=_digest_file(path), url=url))
    prepared = LongDSPreparation(task=task.key, turns=source_turns(root, task), inputs=tuple(inputs),
        english_source_sha256=_digest_file(source / "task.json"), language="en")
    (directory / "preparation.json").write_text(prepared.model_dump_json(indent=2), encoding="utf-8")
    (directory / "prompts.en.json").write_bytes(json_bytes([t.model_dump(mode="json") for t in prepared.turns]))
    seal(directory)
    return verify_preparation(directory)


def configure() -> Settings:
    load_dotenv(ROOT / ".env", override=True)
    settings = Settings.from_env()
    expected = json.loads(REFERENCE_CONFIGURATION.read_bytes())["expected_configuration"]
    if (settings.structured.model != expected["structured"]["model"]
            or settings.openai.model != expected["openai"]["model"]
            or settings.structured.extra_body != expected["structured"]["extra_body"]):
        raise ValueError("当前模型或思考参数已变化，不能默默沿用旧运行计划")
    for prefix, config in (("STRUCTURED", settings.structured), ("OPENAI", settings.openai)):
        if config.capacity is None or not config.api_key or not config.base_url:
            raise ValueError("缺少现有显式模型和容量配置")
        os.environ.update({prefix + "_MODEL": config.model, prefix + "_BASE_URL": config.base_url,
            prefix + "_API_KEY": config.api_key, prefix + "_MODEL_CAPACITY": config.capacity.model_dump_json()})
    os.environ.update(PYTHON_DOTENV_DISABLED="1", OPENAI_SMALL_MODEL=settings.openai.model,
        STRUCTURED_EXTRA_BODY=json.dumps(settings.structured.extra_body),
        STRUCTURED_OUTPUT_TRANSPORT=expected["structured"]["output_transport"],
        PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS=str(expected["structured"]["timeout_seconds"]),
        PERSONAL_AGENT_STRUCTURED_MAX_RETRIES=str(expected["structured"]["max_retries"]),
        PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS=str(expected["openai"]["timeout_seconds"]),
        PERSONAL_AGENT_OPENAI_MAX_RETRIES=str(expected["openai"]["max_retries"]),
        PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS="40", PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS="256",
        PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS="4", PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS="10000000",
        PERSONAL_AGENT_ANSWER_RESULT='{"writer":"direct","verification":"none"}', PYTHONDONTWRITEBYTECODE="1")
    effective = Settings.from_env()
    if _configuration(effective) != expected:
        raise ValueError("实际模型、容量或执行配置与原完整运行不一致")
    return effective


def _sources_unchanged(output: Path) -> bool:
    expected = json.loads((output / "code/source-hashes.json").read_bytes())
    actual = {p.relative_to(ROOT).as_posix(): _digest_file(p) for p in _source_paths()}
    return actual == expected


def _check_windows_paths(output: Path) -> None:
    invocation = ("server-data/interaction_runs/irun_" + "f" * 32 + "/model_invocations/"
        + "f" * 32 + "/000000." + "f" * 32 + ".response.json")
    paths = [output / "t23/capture/checkpoint-17" / invocation]
    paths.extend(output / "t23/capture/source-snapshot" / p.relative_to(ROOT) for p in _source_paths())
    if os.name == "nt" and max(len(str(p)) for p in paths) >= 260:
        raise ValueError("当前归档路径超过Windows安全长度，请使用更短的输出根")


def run(root: Path, output: Path) -> SuiteProgress:
    settings = configure()
    tasks = collect(root)
    _check_windows_paths(output)
    output.mkdir(parents=True, exist_ok=False)
    code = output / "code"
    code.mkdir()
    _source_identity(code)
    shutil.copytree(root / "sources", output / "sources")
    shutil.copyfile(root / "task_list_lite.json", output / "task_list_lite.json")
    provenance = tuple(SourceProvenance(task=t,
        task_url=f"https://huggingface.co/datasets/zjunlp/LongDS/resolve/{DATASET_REVISION}/task/longds_v1.1/{t.key}/task.json",
        task_sha256=_digest_file(output / "sources" / t.key / "task.json"),
        input_tree_url=f"https://huggingface.co/api/datasets/zjunlp/LongDS/tree/{DATASET_REVISION}/data/longds/{t.key}/data?recursive=true&expand=false",
        input_tree_sha256=_digest_file(output / "sources" / t.key / "input-tree.json")) for t in tasks)
    (output / "sources/origins.json").write_bytes(TypeAdapter(tuple[SourceProvenance, ...]).dump_json(provenance, indent=2))
    seal(output / "sources")
    progress = SuiteProgress(tasks=tasks, planned_turns=sum(len(source_turns(output, t)) for t in tasks),
        source_digest=json.loads((code / "repository.json").read_bytes())["source_digest"],
        configuration_digest=sha256(json_bytes(_configuration(settings))).hexdigest())
    _write(output / "progress.json", progress)
    (output / "launch.json").write_bytes(json_bytes({"pid": os.getpid(), "started_at": progress.started_at.isoformat()}))
    identity = json.loads(REFERENCE_CONFIGURATION.read_bytes())
    try:
        for index, task in enumerate(tasks, 1):
            verify_seal(output / "sources")
            if not _sources_unchanged(output):
                progress.state, progress.stop_reason = "paused", "source_changed"
                break
            if sha256(json_bytes(_configuration(Settings.from_env()))).hexdigest() != progress.configuration_digest:
                progress.state, progress.stop_reason = "paused", "effective_configuration_changed"
                break
            if shutil.disk_usage(root).free < 10 * 1024 ** 3:
                progress.state, progress.stop_reason = "paused", "free_disk_below_10GiB"
                break
            progress.current_task = task.key
            _write(output / "progress.json", progress)
            task_root = output / f"t{index:02}"
            task_root.mkdir(parents=True)
            planned = len(source_turns(output, task))
            capture = None
            judge = None
            stage = "preparation_failed"
            try:
                prepared = prepare_original(output, task, task_root / "materials")
                verify_seal(output / "sources")
                if not _sources_unchanged(output):
                    raise ValueError("准备期间源码发生变化，不得开始新采集")
                stage = "capture_failed"
                capture = baseline(task_root / "materials", task_root / "capture", purpose="target",
                    user_turns=len(prepared.turns), task_token_limit=TOKEN_LIMIT,
                    python_image_id=identity["python_image_id"], docker_endpoint=identity["docker_endpoint"])
                stage = "score_failed"
                verify_seal(QUALIFICATION)
                judge = MeteredJudge(task_root / "judge", source_directory=SOURCE_DIRECTORY)
                score(judge, materials=task_root / "materials", capture=task_root / "capture", name="official",
                    qualification_directory=QUALIFICATION)
                scores = JudgeScoreReport.model_validate_json((task_root / "judge/official/report.json").read_bytes())
                result = TaskResult(task=task, planned_turns=planned, capture=capture,
                    status="completed" if capture.answered_turns == planned and scores.judged_turns == planned else "capture_failed",
                    judged_turns=scores.judged_turns, correct_turns=scores.correct_turns,
                    known_judge_tokens=scores.known_judge_tokens, unknown_judge_attempts=scores.unknown_usage_attempts)
            except Exception as error:
                used, unknown = judge.usage() if judge is not None else (0, 0)
                result = TaskResult(task=task, status=stage, planned_turns=planned,
                    capture=capture, exception_type=type(error).__name__, known_judge_tokens=used,
                    unknown_judge_attempts=unknown)
                print("task_failure", task.key, stage, type(error).__name__, str(error), flush=True)
            finally:
                if judge is not None:
                    judge.client.close()
            _write(task_root / "result.json", result)
            progress.results += (result,)
            progress.current_task = None
            _write(output / "progress.json", progress)
            print("task_finished", result.model_dump_json(), flush=True)
            if result.status == "capture_failed" and capture is None:
                progress.state, progress.stop_reason = "paused", "capture_exit_not_confirmed"
                break
            if capture is not None and not capture.actual_process_stopped:
                progress.state, progress.stop_reason = "paused", "web_process_not_stopped"
                break
            if capture is not None and capture.requested_turns == 0:
                progress.state, progress.stop_reason = "paused", "formal_entry_not_reached"
                break
            if capture is not None and (capture.known_tokens > 2 * 26_423_421 * planned / 36
                    or capture.wall_seconds > 2 * 3995.375 * planned / 36):
                progress.state, progress.stop_reason = "paused", "cost_review_at_atomic_task_boundary"
                break
        else:
            progress.state, progress.stop_reason = "finished", "all_selected_tasks_attempted"
    except BaseException:
        progress.state, progress.stop_reason = "paused", "suite_interrupted_or_environment_failure"
        raise
    finally:
        _write(output / "progress.json", progress)
    return progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    tasks = collect(root)
    if args.collect_only:
        print(json.dumps({"tasks": len(tasks), "turns": sum(len(source_turns(root, t)) for t in tasks),
            "language": "en", "model_calls": 0, "selected": [t.key for t in tasks]}, ensure_ascii=False, indent=2))
    else:
        if args.output is None:
            parser.error("执行时必须指定尚不存在的--output目录")
        print(run(root, args.output.resolve()).model_dump_json(), flush=True)


if __name__ == "__main__":
    main()
