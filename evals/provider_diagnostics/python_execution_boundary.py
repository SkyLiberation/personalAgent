"""Replay sealed research Artifact bytes through real Python execution boundaries.

This is an Offline execution-boundary journey, not a model evaluation or a
Conversation/Product E2E. Diagnostic author code only proves mechanical
execution; it must never be injected as a model's proposed analysis.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.artifacts.service import ArtifactService
from personal_agent.application.conversation.artifact_sources import trace_resource_refs
from personal_agent.application.conversation.journal import FileInteractionJournal
from personal_agent.application.conversation.models import (
    AcceptedPythonToolRequest,
    InteractionTrace,
)
from personal_agent.application.python_execution.models import (
    ExecutePythonArgs,
    PythonExecutionLimits,
    PythonExecutionProfile,
    PythonInputBinding,
    PythonToolResult,
)
from personal_agent.application.python_execution.service import PythonExecutionService
from personal_agent.application.retrieval_experiment.models import RetrievalDeployment
from personal_agent.governance.registry import ToolExecutor
from personal_agent.infra.python_execution.backend import DockerPythonExecutionBackend
from personal_agent.infra.python_execution.sandbox import _stage_inputs, _remove_staging
from personal_agent.kernel.config import Settings
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.tools.execute_python import build_execute_python_tool

_REVISION = "python-execution-real-source-boundary-v1"
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PREFLIGHT = (
    _ROOT / ".tmp/python-analysis-implementation-20261021/source-preflight.json"
)
_DEPLOYMENT = (
    _ROOT
    / ".tmp/context-compression-research-20261021/e1-preparation-3/world/deployment.private.json"
)
_CODE = """import json, sys
from pathlib import Path
rows = json.loads((Path(sys.argv[1]) / 'per_query.json').read_bytes())
print(len(rows), flush=True)
"""


class _SourceFile(BaseModel):
    path: Path
    sha256: str
    bytes: int


class _SourceStage(BaseModel):
    label: str
    journal: _SourceFile
    remaining_at_input: dict[str, float]


class _ArtifactSource(BaseModel):
    resource_ref: ResourceRef
    filename: str
    subdirectory: Literal["uploads", "generated_artifacts"]
    storage_name: str
    sha256: str
    bytes: int
    visible_in: tuple[str, ...]


class _Preflight(BaseModel):
    sources: tuple[_SourceStage, ...]
    artifact_roots: dict[str, Path]
    artifacts: tuple[_ArtifactSource, ...]


class _Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: str
    status: Literal["passed", "failed", "not_covered"]
    evidence: dict[str, object] = Field(default_factory=dict)


def _save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _checked(path: Path, digest: str, size: int | None = None) -> bytes:
    content = path.read_bytes()
    _require(
        sha256(content).hexdigest() == digest
        and (size is None or len(content) == size),
        f"source checksum differs: {path}",
    )
    return content


class BoundaryJourney:
    def __init__(self, *, source: Path, output: Path) -> None:
        _require(not output.exists(), "each journey requires a new output directory")
        output.mkdir(parents=True)
        self.output = output.resolve()
        os.environ["PERSONAL_AGENT_E2E_TRACE_DIR"] = str(self.output / "traces")
        os.environ["PERSONAL_AGENT_PRODUCT_EVIDENCE_DIR"] = str(
            self.output / "evidence"
        )
        self.preflight = _Preflight.model_validate_json(source.read_bytes())
        self.stage = next(
            item for item in self.preflight.sources if item.label == "report_stage"
        )
        self.original_trace = InteractionTrace.model_validate_json(
            _checked(
                _ROOT / self.stage.journal.path,
                self.stage.journal.sha256,
                self.stage.journal.bytes,
            )
        )
        self.artifacts = tuple(
            item
            for item in self.preflight.artifacts
            if "report_stage" in item.visible_in
        )
        deployment = json.loads(_DEPLOYMENT.read_bytes())
        self.deployment = RetrievalDeployment.model_validate(deployment["deployment"])
        self.endpoint = deployment["environment"]["endpoint"]
        _require(
            self.deployment.deployment_digest == self.original_trace.deployment_digest,
            "source deployment digest differs",
        )
        limits = self.deployment.limits
        self.profile = PythonExecutionProfile(
            authorized_principal=self.deployment.authorized_principal,
            deployment_digest=self.deployment.deployment_digest,
            image_id=self.deployment.candidate_image_id,
            limits=PythonExecutionLimits(
                timeout_seconds=min(5.0, limits.candidate_timeout_seconds),
                memory_mb=limits.candidate_memory_mb,
                cpus=limits.candidate_cpus,
                pids_limit=limits.candidate_pids,
                scratch_mb=limits.candidate_scratch_mb,
                stdout_bytes=limits.stdout_bytes,
                stderr_bytes=limits.stderr_bytes,
            ),
        )
        self.outcomes: list[_Outcome] = []
        self.started_at = datetime.now(timezone.utc)
        self.per_query = next(
            item for item in self.artifacts if item.filename == "per_query.json"
        )
        self.client = None
        self.calls = 0
        self.commands: set[str] = set()
        self.total_execution_seconds = 0.0
        self.source_hashes = self._source_hashes()
        _save(
            self.output / "identity.json",
            {
                "revision": _REVISION,
                "source": self.stage.model_dump(mode="json"),
                "preflight_sha256": sha256(source.read_bytes()).hexdigest(),
                "deployment_sha256": sha256(_DEPLOYMENT.read_bytes()).hexdigest(),
                "profile": self.profile.model_dump(mode="json"),
                "source_hashes": self.source_hashes,
                "head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=_ROOT, text=True
                ).strip(),
                "dirty_diff_sha256": sha256(
                    subprocess.check_output(["git", "diff", "--binary"], cwd=_ROOT)
                ).hexdigest(),
                "evidence_class": "Offline real-source execution-boundary journey",
                "model_calls": 0,
                "container_limit": 8,
                "process_seconds_limit": 60,
                "single_command_seconds_limit": 5,
                "scope": "Actual ArtifactService, FileInteractionJournal, ToolExecutor and Docker backend; no model or Conversation loop",
            },
        )

    @staticmethod
    def _source_hashes() -> dict[str, str]:
        paths = tuple((_ROOT / "src/personal_agent").rglob("*.py")) + (Path(__file__),)
        return {
            str(path.relative_to(_ROOT)): sha256(path.read_bytes()).hexdigest()
            for path in paths
        }

    def _branch(
        self,
        name: str,
        *,
        copy_from: Path | None = None,
        through_revision: int | None = None,
    ) -> Path:
        root = self.output / name
        if copy_from is not None:
            shutil.copytree(copy_from, root)
            if through_revision is not None:
                run = (
                    root
                    / "data/interaction_runs"
                    / self.original_trace.interaction_run_ref
                )
                for path in run.glob("*.json"):
                    if int(path.stem) > through_revision:
                        path.unlink()
            return root
        data = root / "data"
        source_root = _ROOT / self.preflight.artifact_roots["original"]
        for item in self.artifacts:
            folder = data / item.subdirectory
            folder.mkdir(parents=True, exist_ok=True)
            original = source_root / item.subdirectory / item.storage_name
            content = _checked(original, item.sha256, item.bytes)
            (folder / item.storage_name).write_bytes(content)
            sidecar = (
                source_root
                / item.subdirectory
                / f"{item.resource_ref.resource_id}.json"
            )
            shutil.copyfile(sidecar, folder / sidecar.name)
        # Historical time is explicitly mapped only for this Offline journey.
        # Original records, model/semantic input and allowance are preserved.
        mapped = self.original_trace.model_copy(
            update={
                "run_deadline_at": datetime.now(timezone.utc)
                + timedelta(
                    seconds=self.stage.remaining_at_input["wall_seconds_at_input"]
                ),
            }
        )
        run = data / "interaction_runs" / mapped.interaction_run_ref
        _save(run / f"{mapped.revision:04d}.json", mapped)
        _save(
            root / "source-map.json",
            {
                "original_journal": self.stage.journal.model_dump(mode="json"),
                "original_deadline": self.original_trace.run_deadline_at.isoformat(),
                "mapped_deadline": mapped.run_deadline_at.isoformat(),
                "original_max_execution_seconds": mapped.max_execution_seconds,
                "allowed_original_artifacts": len(self.artifacts),
                "classification": "Offline time mapping; not current-time Product E2E or real process-crash recovery",
            },
        )
        return root

    def _components(self, root: Path, profile: PythonExecutionProfile | None = None):
        profile = profile or self.profile
        journal = FileInteractionJournal(root / "data/interaction_runs")
        artifacts = ArtifactService(Settings(data_dir=root / "data"))
        backend = DockerPythonExecutionBackend(
            endpoint=self.endpoint, work_root=root / "jobs", profile=profile
        )
        service = PythonExecutionService(
            artifacts=artifacts, journal=journal, execution=backend, profile=profile
        )
        executor = ToolExecutor()
        executor.register(build_execute_python_tool(service))
        return journal, artifacts, service, executor

    def _arguments(self, code: str = _CODE) -> ExecutePythonArgs:
        return ExecutePythonArgs(
            code=code,
            program_ref=None,
            input_files=(
                PythonInputBinding(
                    name="per_query.json", resource_ref=self.per_query.resource_ref
                ),
            ),
        )

    def _scope(self, action: str) -> ExecutionScope:
        return ExecutionScope(
            principal=self.original_trace.principal,
            execution_id=self.original_trace.interaction_run_ref,
            thread_id=self.original_trace.conversation_id,
            task_id=action,
        )

    def _invoke(
        self,
        root: Path,
        action: str,
        args: ExecutePythonArgs,
        *,
        profile: PythonExecutionProfile | None = None,
        accept: bool = True,
    ):
        journal, artifacts, service, executor = self._components(root, profile)
        scope = self._scope(action)
        if accept:
            accepted = journal.accept_tool_request(
                execution_scope=scope,
                action_id=action,
                arguments=args,
                plan_step_id=None,
            )
        else:
            trace = journal.get(scope.execution_id)
            accepted = next(
                item
                for item in trace.accepted_tool_requests
                if item.action_id == action
            )
        result = executor.invoke_interaction(
            "execute_python",
            args.model_dump(mode="json"),
            execution_scope=scope,
            tool_call_id=action,
            source_platform="offline_python_boundary",
            allowed_resource_refs=trace_resource_refs(journal.get(scope.execution_id)),
            accepted_request_digest=accepted.request_digest,
        )
        _save(root / "responses" / f"{action}-{time.time_ns()}.json", result)
        latest = journal.get(scope.execution_id)
        saved = next(
            item for item in latest.accepted_tool_requests if item.action_id == action
        )
        if saved.command is not None:
            self.commands.add(saved.command.command_digest)
        return result, saved, journal, artifacts

    def _passed(self, case: str, **evidence: object) -> None:
        self.outcomes.append(_Outcome(case=case, status="passed", evidence=evidence))
        self.report()
        print(f"{case}: passed", flush=True)

    def _no_jobs(self, root: Path) -> bool:
        return not (root / "jobs").exists() or not any((root / "jobs").iterdir())

    def precheck(self) -> None:
        import docker

        self.client = docker.DockerClient(
            base_url=self.endpoint, version="1.44", timeout=5
        )
        self.client.api.trust_env = False
        _require(
            self.client.ping(),
            "Docker daemon unavailable; no image pull or setup permitted",
        )
        image = self.client.images.get(self.profile.image_id)
        _require(
            image.id == self.profile.image_id and image.attrs.get("Os") == "linux",
            "existing fixed Linux image unavailable",
        )
        self._passed(
            "existing_daemon_and_image",
            image_id=image.id,
            source_artifacts=len(self.artifacts),
        )

    def success_and_recovery(self) -> Path:
        root = self._branch("success")
        journal, _, _, _ = self._components(root)
        action, args = "py-boundary-real-count", self._arguments()
        scope = self._scope(action)
        journal.accept_tool_request(
            execution_scope=scope, action_id=action, arguments=args, plan_step_id=None
        )
        accepted_revision = journal.get(scope.execution_id).revision
        _require(self._no_jobs(root), "accepted request unexpectedly dispatched")
        # A newly constructed journal/service/executor resumes the accepted point.
        output, saved, journal, artifacts = self._invoke(
            root, action, args, accept=False
        )
        _require(
            output["ok"]
            and saved.receipt is not None
            and saved.receipt.status == "succeeded",
            f"source computation failed: {output}",
        )
        self.calls += 1
        self.total_execution_seconds += saved.execution.elapsed_seconds or 0
        result = PythonToolResult.model_validate(output["data"])
        original = json.loads(
            _checked(
                _ROOT
                / self.preflight.artifact_roots["original"]
                / self.per_query.subdirectory
                / self.per_query.storage_name,
                self.per_query.sha256,
            )
        )
        expected = f"{len(original)}\n".encode()
        stdout = artifacts.read_upload(
            saved.receipt.stdout_ref, principal=scope.principal, owner=scope.principal
        )[1]
        _require(
            stdout == expected and result.stdout_preview == expected.decode(),
            "actual stdout differs from real source row count",
        )
        snapshot_paths = sorted(
            (root / "data/interaction_runs" / scope.execution_id).glob("*.json")
        )
        dispatch_rev = terminal_rev = None
        for path in snapshot_paths:
            trace = InteractionTrace.model_validate_json(path.read_bytes())
            request = next(
                (
                    item
                    for item in trace.accepted_tool_requests
                    if item.action_id == action
                ),
                None,
            )
            if (
                isinstance(request, AcceptedPythonToolRequest)
                and request.execution is not None
            ):
                if request.execution.status == "dispatching":
                    dispatch_rev = trace.revision
                elif (
                    request.execution.status == "succeeded" and request.receipt is None
                ):
                    terminal_rev = trace.revision
        _require(
            dispatch_rev is not None and terminal_rev is not None,
            "actual durable checkpoints unavailable",
        )
        budget_before = journal.execution_budget(journal.get(scope.execution_id))
        self._passed(
            "accepted_checkpoint_first_execution",
            action_id=action,
            accepted_revision=accepted_revision,
            command=saved.command.model_dump(mode="json"),
            execution=saved.execution.model_dump(mode="json"),
            stdout_sha256=sha256(stdout).hexdigest(),
            row_count=len(original),
            tool_result=result.model_dump(mode="json"),
        )
        replay, replay_saved, replay_journal, _ = self._invoke(
            root, action, args, accept=False
        )
        _require(
            replay == output and replay_saved == saved,
            "same-action replay changed receipt",
        )
        _require(
            replay_journal.execution_budget(replay_journal.get(scope.execution_id))
            == budget_before,
            "same-action replay charged again",
        )
        self._passed(
            "same_action_receipt_recovery",
            command_digest=saved.command.command_digest,
            budget=budget_before.model_dump(mode="json"),
        )
        for label, revision in (
            ("dispatching_checkpoint_recovery", dispatch_rev),
            ("terminal_before_publication_recovery", terminal_rev),
        ):
            branch = self._branch(label, copy_from=root, through_revision=revision)
            recovered, request, recovered_journal, recovered_artifacts = self._invoke(
                branch, action, args, accept=False
            )
            _require(
                recovered == output
                and request.command == saved.command
                and request.execution == saved.execution,
                f"{label}: original facts changed",
            )
            raw = recovered_artifacts.read_upload(
                request.receipt.stdout_ref,
                principal=scope.principal,
                owner=scope.principal,
            )[1]
            _require(raw == stdout, f"{label}: original capture changed")
            _require(
                recovered_journal.execution_budget(
                    recovered_journal.get(scope.execution_id)
                )
                == budget_before,
                f"{label}: extra charge",
            )
            self._passed(
                label,
                checkpoint_revision=revision,
                command_digest=request.command.command_digest,
                stdout_sha256=sha256(raw).hexdigest(),
                container_id=request.execution.container_id,
            )
        missing = self._branch(
            "terminal_capture_missing", copy_from=root, through_revision=terminal_rev
        )
        (
            missing / "jobs" / saved.command.command_digest / "execution/stdout.json"
        ).unlink()
        failed, request, _, _ = self._invoke(missing, action, args, accept=False)
        _require(
            not failed["ok"]
            and request.execution == saved.execution
            and request.receipt.error_code == "output_unavailable"
            and request.receipt.process_exit_code == saved.execution.process_exit_code,
            "missing capture altered execution or guessed success",
        )
        self._passed(
            "terminal_capture_missing",
            receipt=request.receipt.model_dump(mode="json"),
            preserved_execution=request.execution.model_dump(mode="json"),
        )
        unknown = self._branch(
            "unknown",
            copy_from=root,
            through_revision=dispatch_rev,
        )
        (
            unknown / "jobs" / saved.command.command_digest / "execution/result.json"
        ).unlink()
        unknown_output, pending, pending_journal, _ = self._invoke(
            unknown, action, args, accept=False
        )
        budget = pending_journal.execution_budget(
            pending_journal.get(scope.execution_id)
        )
        source_budget = pending_journal.execution_budget(self.original_trace)
        _require(
            not unknown_output["ok"]
            and pending.execution.status == "unknown"
            and action in budget.unsettled_action_ids,
            "missing original job was not left unknown",
        )
        _require(
            abs(
                budget.consumed_seconds
                - source_budget.consumed_seconds
                - saved.command.reserved_seconds
            )
            < 1e-6,
            "unknown execution lost its reservation",
        )
        blocked, blocked_request, _, _ = self._invoke(
            unknown, "py-boundary-blocked-by-unknown", args
        )
        _require(
            not blocked["ok"]
            and blocked_request.command is None
            and blocked["error_kind"] == "permission"
            and "reconcile the pending execution" in blocked["error"],
            "unknown job did not block another execution",
        )
        self._passed(
            "unknown_reconcile_and_shared_reservation",
            budget=budget.model_dump(mode="json"),
            unknown_execution=pending.execution.model_dump(mode="json"),
            blocked_result=blocked,
        )
        return root

    def refusals(self) -> None:
        root = self._branch("refusals")
        args = self._arguments()
        changed_ref = self.per_query.resource_ref.model_copy(
            update={"revision": self.per_query.resource_ref.revision + 1}
        )
        other_owner = self.per_query.resource_ref.owner.model_copy(
            update={"user_id": self.deployment.scorer_principal.user_id}
        )
        for label, ref in (
            ("unreadable_revision", changed_ref),
            (
                "cross_principal",
                self.per_query.resource_ref.model_copy(update={"owner": other_owner}),
            ),
        ):
            request = ExecutePythonArgs(
                code=args.code,
                program_ref=args.program_ref,
                input_files=(PythonInputBinding(name="per_query.json", resource_ref=ref),),
            )
            output, accepted, _, _ = self._invoke(root, f"py-boundary-{label}", request)
            _require(
                not output["ok"] and accepted.command is None and self._no_jobs(root),
                f"{label}: unexpectedly dispatched",
            )
            self._passed(label, result=output)
        journal, _, _, executor = self._components(root)
        before_revision = journal.get(self.original_trace.interaction_run_ref).revision
        for name in ("../per_query.json", "CON.json", "program.py", "a."):
            raw = args.model_dump(mode="json")
            raw["input_files"][0]["name"] = name
            validation = executor.validate_interaction_call("execute_python", raw)
            _require(
                validation.status == "invalid_arguments",
                "invalid filename passed admission",
            )
        raw = args.model_dump(mode="json")
        raw["input_files"].append({**raw["input_files"][0], "name": "PER_QUERY.JSON"})
        _require(
            executor.validate_interaction_call("execute_python", raw).status
            == "invalid_arguments",
            "case collision passed admission",
        )
        _require(
            journal.get(self.original_trace.interaction_run_ref).revision
            == before_revision
            and self._no_jobs(root),
            "schema rejection modified execution",
        )
        self._passed(
            "filename_and_duplicate_admission",
            names=[
                "../per_query.json",
                "CON.json",
                "program.py",
                "a.",
                "PER_QUERY.JSON",
            ],
            zero_dispatch=True,
        )
        quota = self._branch("quota_exhausted")
        journal, _, _, _ = self._components(quota)
        trace = journal.get(self.original_trace.interaction_run_ref)
        trace = trace.model_copy(
            update={
                "max_execution_seconds": journal.execution_budget(
                    trace
                ).consumed_seconds
            }
        )
        _save(
            quota
            / "data/interaction_runs"
            / trace.interaction_run_ref
            / f"{trace.revision:04d}.json",
            trace,
        )
        output, accepted, _, _ = self._invoke(quota, "py-boundary-no-allowance", args)
        _require(
            not output["ok"] and accepted.command is None and self._no_jobs(quota),
            "exhausted allowance dispatched",
        )
        _require(
            output["error_kind"] == "unrecoverable"
            and "当前run执行额度或绝对截止已耗尽" in output["error"]
            and "Nones" not in output["error"],
            "allowance rejection feedback lost its actual cause",
        )
        self._passed(
            "shared_allowance_exhausted",
            result=output,
            max_execution_seconds=trace.max_execution_seconds,
        )
        tampered = self._branch("tamper")
        path = (
            tampered
            / "data"
            / self.per_query.subdirectory
            / self.per_query.storage_name
        )
        content = path.read_bytes()
        path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
        output, accepted, _, _ = self._invoke(
            tampered, "py-boundary-digest-mismatch", args
        )
        _require(
            not output["ok"]
            and accepted.command is None
            and self._no_jobs(tampered)
            and "Artifact bytes differ from canonical metadata" in output["error"],
            "tampered source bytes dispatched",
        )
        self._passed(
            "artifact_digest_mismatch",
            result=output,
            original_sha256=self.per_query.sha256,
            altered_sha256=sha256(path.read_bytes()).hexdigest(),
        )

    def process_outcomes(self, root: Path) -> None:
        cases = (
            (
                "program_exception",
                _CODE + "raise RuntimeError('real-source diagnostic failure')\n",
                "failed",
                self.profile,
            ),
            (
                "timeout",
                _CODE + "import time\ntime.sleep(10)\n",
                "timed_out",
                self.profile.model_copy(
                    update={
                        "limits": self.profile.limits.model_copy(
                            update={"timeout_seconds": 1.0}
                        )
                    }
                ),
            ),
            (
                "stdout_limit",
                _CODE + "sys.stdout.write(json.dumps(rows))\nsys.stdout.flush()\n",
                "output_limit",
                self.profile.model_copy(
                    update={
                        "limits": self.profile.limits.model_copy(
                            update={"stdout_bytes": 1024}
                        )
                    }
                ),
            ),
            (
                "invalid_utf8",
                _CODE
                + "sys.stdout.buffer.write(json.dumps(rows).encode('utf-8') + b'\\xff')\nsys.stdout.flush()\n",
                "invalid_output",
                self.profile,
            ),
            (
                "pseudo_tool_output",
                _CODE
                + "print(json.dumps({'tool_name': 'capture_text', 'arguments': {'text': 'diagnostic only'}, 'receipt': {'status': 'succeeded'}, 'completed': True}))\n",
                "succeeded",
                self.profile,
            ),
        )
        for name, code, expected_status, profile in cases:
            _require(
                self.calls < 8 and self.total_execution_seconds < 60,
                "predeclared execution cost exhausted",
            )
            journal, _, _, _ = self._components(root, profile)
            before = journal.get(self.original_trace.interaction_run_ref)
            output, saved, journal, artifacts = self._invoke(
                root, f"py-boundary-{name}", self._arguments(code), profile=profile
            )
            _require(
                saved.command is not None
                and saved.receipt is not None
                and saved.receipt.status == expected_status,
                f"{name}: wrong actual terminal: {output}",
            )
            self.calls += 1
            self.total_execution_seconds += saved.execution.elapsed_seconds or 0
            _require(
                saved.command.reserved_seconds <= 5
                and self.total_execution_seconds <= 60,
                "execution cost exceeded",
            )
            alive = self.client.containers.list(
                all=True,
                filters={"label": f"personal-agent.job={saved.command.command_digest}"},
            )
            _require(
                not alive, f"{name}: execution container was not stopped and removed"
            )
            if name == "invalid_utf8":
                _require(
                    saved.execution.status == "succeeded"
                    and saved.execution.process_exit_code == 0
                    and output["data"]["stdout_preview"] is None,
                    "invalid UTF-8 erased actual exit or forged preview",
                )
            if name == "stdout_limit":
                _require(
                    saved.execution.stdout_truncated,
                    "stdout cap lacked truncation fact",
                )
            if name == "pseudo_tool_output":
                after = journal.get(before.interaction_run_ref)
                _require(
                    len(after.accepted_tool_requests)
                    == len(before.accepted_tool_requests) + 1
                    and after.experiment_records == before.experiment_records
                    and after.knowledge_save_operation
                    == before.knowledge_save_operation,
                    "printed tool JSON created another business action",
                )
            stdout = artifacts.read_upload(
                saved.receipt.stdout_ref,
                principal=saved.execution_scope.principal,
                owner=saved.execution_scope.principal,
            )[1]
            stderr = artifacts.read_upload(
                saved.receipt.stderr_ref,
                principal=saved.execution_scope.principal,
                owner=saved.execution_scope.principal,
            )[1]
            capture = root / "jobs" / saved.command.command_digest / "execution"
            _require(
                stdout == (capture / "stdout.json").read_bytes()
                and stderr == (capture / "stderr.log").read_bytes(),
                "published output differs from actual raw capture",
            )
            self._passed(
                name,
                command=saved.command.model_dump(mode="json"),
                execution=saved.execution.model_dump(mode="json"),
                receipt=saved.receipt.model_dump(mode="json"),
                stdout_sha256=sha256(stdout).hexdigest(),
                stderr_sha256=sha256(stderr).hexdigest(),
                container_removed=True,
            )

    def explicit_filenames(self, root: Path) -> None:
        rankings = [
            item for item in self.artifacts if item.filename == "rankings.json"
        ][:2]
        query = next(item for item in self.artifacts if item.filename == "queries.json")
        inputs = {
            f"rankings_{index}.json": root
            / "data"
            / item.subdirectory
            / item.storage_name
            for index, item in enumerate(rankings)
        }
        inputs["queries.json"] = root / "data" / query.subdirectory / query.storage_name
        ids = self.output / "source-corpus-ids.json"
        ids.write_text(
            json.dumps(
                self.deployment.development.document_ids, ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        inputs["corpus_ids.json"] = ids
        program = (
            root
            / "jobs"
            / next(
                item.name
                for item in (root / "jobs").iterdir()
                if (item / "bound/program.py").is_file()
            )
            / "bound/program.py"
        )
        directory = Path(tempfile.mkdtemp(prefix="retrieval-candidate-inputs-"))
        try:
            hashes = _stage_inputs(directory, program, inputs)
            _require(
                set(hashes) == {"program.py", *inputs},
                "explicit filenames were renamed",
            )
            for name, original in inputs.items():
                _require(
                    (directory / name).read_bytes() == original.read_bytes(),
                    "shared input staging changed source bytes",
                )
            _save(
                self.output / "explicit-filename-stage.json",
                {
                    "hashes": hashes,
                    "original_inputs": {
                        name: str(path.relative_to(self.output))
                        for name, path in inputs.items()
                    },
                    "actual_original_candidate_execution": "not covered: selected source has no candidate program",
                },
            )
        finally:
            _remove_staging(directory)
        self._passed(
            "shared_sandbox_explicit_filename_staging",
            names=sorted(hashes),
            hashes=hashes,
            scope="real source rankings/query/corpus IDs staging; original retrieval experiment execution remains not covered",
        )

    def final_inventory(self) -> None:
        events = list(
            self.client.events(
                since=int(self.started_at.timestamp()) - 1,
                until=int(time.time()) + 1,
                decode=True,
                filters={"type": "container", "event": "create"},
            )
        )
        actual = [
            event
            for event in events
            if event.get("Actor", {}).get("Attributes", {}).get("personal-agent.job")
            in self.commands
        ]
        _save(self.output / "docker-create-events.json", actual)
        _require(
            len(actual) == self.calls
            and self.calls <= 8
            and self.total_execution_seconds <= 60,
            "unexpected Docker create count or process cost",
        )
        _require(
            len(
                {event["Actor"]["Attributes"]["personal-agent.job"] for event in actual}
            )
            == self.calls,
            "same frozen job created more than one container",
        )
        for item in self.artifacts:
            _checked(
                _ROOT
                / self.preflight.artifact_roots["original"]
                / item.subdirectory
                / item.storage_name,
                item.sha256,
                item.bytes,
            )
        _require(
            self.source_hashes == self._source_hashes(),
            "production code identity changed during journey",
        )
        self._passed(
            "physical_dispatch_and_source_integrity",
            docker_create_count=len(actual),
            unique_jobs=self.calls,
            actual_process_seconds=self.total_execution_seconds,
            unchanged_source_artifacts=len(self.artifacts),
            no_model_calls=True,
        )

    def report(self, error: str | None = None) -> None:
        _save(
            self.output / "boundary-report.json",
            {
                "revision": _REVISION,
                "evidence_class": "Offline real-source execution-boundary journey",
                "source_journal": self.stage.journal.model_dump(mode="json"),
                "outcomes": [
                    outcome.model_dump(mode="json") for outcome in self.outcomes
                ],
                "completed_physical_commands": self.calls,
                "actual_process_seconds": self.total_execution_seconds,
                "model_calls": 0,
                "error": error,
                "not_covered": [
                    "model-generated code / V1",
                    "Conversation/Product E2E / V4",
                    "original candidate retrieval experiment execution",
                    "real operating-system crash during a live process",
                    "OOM stress",
                ],
            },
        )
        lines = [
            "# Python执行边界真实源Offline旅程",
            "",
            f"来源：0056，{len(self.artifacts)}份合法原件；证据不包括模型自主性、完整Conversation或产品E2E。",
            "",
            f"实际新执行：{self.calls}个；进程耗时合计：{self.total_execution_seconds:.6f}秒；模型调用：0。",
            "",
            "| 用例 | 结果 |",
            "| --- | --- |",
        ]
        lines.extend(
            f"| {outcome.case} | {outcome.status} |" for outcome in self.outcomes
        )
        lines.extend(
            [
                "",
                "恢复通过复制实际接受／dispatching／终态前发布快照及同次真实后端结果形成隔离分支；不是活动进程真实崩溃证据。原历史deadline只在隔离分支明确做当前时间映射，原额度及所有实际原件保持。",
                "",
                "诊断代码由评测作者编写，只证明执行、权限、捕获与恢复边界；没有进入模型输入，不证明V1工具贡献或修复52／38成文。",
                "",
                "原检索共享迁移仅检查真实排名／查询／corpus ID的确切文件名与原字节；未运行原候选评分流程。OOM压力、完整研究target、模型回放不在本旅程执行范围。",
            ]
        )
        if error:
            lines.extend(["", f"停止原因：{error}"])
        (self.output / "boundary-report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

    def run(self) -> None:
        try:
            self.precheck()
            root = self.success_and_recovery()
            self.refusals()
            self.process_outcomes(root)
            self.explicit_filenames(root)
            self.final_inventory()
            self.report()
        except Exception as error:
            self.report(f"{type(error).__name__}: {error}")
            raise
        finally:
            if self.client is not None:
                self.client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=_DEFAULT_PREFLIGHT)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    BoundaryJourney(source=options.source, output=options.output).run()


if __name__ == "__main__":
    main()
