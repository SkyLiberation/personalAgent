"""两 arm 真实首 SDK 的独立零 HTTP 预检；不调度或重置模型样本。"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import http.client
import json
from pathlib import Path
import subprocess
from typing import Iterator, Literal
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile

from evals.product_baselines.retrieval_http_server import redact_payload
from evals.provider_diagnostics.python_result_analysis_archive import (
    AUTHORITY,
    ROOT,
    PreparationSeal,
    code_identity,
    restore_branch,
    select_source,
    stamp,
    verify_file,
    verify_plan,
)
from evals.provider_diagnostics.python_result_analysis_capture import (
    compare_first_sdk,
    write_record,
)
from evals.provider_diagnostics.python_result_analysis_models import (
    FileStamp,
    FirstSdkAudit,
    GroupPlan,
    Record,
)
from evals.provider_diagnostics.python_result_analysis_runtime import (
    RootConfiguration,
    branch_environment,
    branch_settings,
    build_branch_context,
    converse_source,
    root_configuration,
)


class InputProbeStopped(BaseException):
    pass


class ArmInputValidation(Record):
    arm: Literal["B", "C"]
    reason: str
    passed: bool
    sdk: FileStamp | None
    audit: FirstSdkAudit | None
    configuration: RootConfiguration
    clock_mapping: FileStamp
    blocked_http: tuple[str, ...]
    blocked_processes: tuple[str, ...]
    error_type: str | None


class InputValidation(Record):
    group_id: str
    started_at: datetime
    finished_at: datetime
    validation_plan: FileStamp
    preserved_group_plan: FileStamp
    preserved_group_state: FileStamp
    group_state_unchanged: bool
    arms: tuple[ArmInputValidation, ...]
    passed: bool
    physical_sends: Literal[0] = 0
    model_responses: Literal[0] = 0
    container_starts: Literal[0] = 0


class InputValidationSeal(Record):
    files: tuple[FileStamp, ...]


class InputProbe:
    def __init__(self, branch: Path, plan: GroupPlan, arm: Literal["B", "C"]):
        self.branch, self.plan, self.arm = branch, plan, arm
        self.audit: FirstSdkAudit | None = None
        self.sdk: FileStamp | None = None
        self.blocked_http: list[str] = []
        self.blocked_processes: list[str] = []

    @contextmanager
    def installed(self) -> Iterator[None]:
        import httpx
        import requests

        from personal_agent.infra.structured_model import OpenAIModelClient

        def blocked_http(*args, **kwargs):
            self.blocked_http.append("HTTP_send")
            raise InputProbeStopped("unexpected_http")

        async def blocked_async_http(*args, **kwargs):
            blocked_http()

        def blocked_process(*args, **kwargs):
            self.blocked_processes.append("subprocess.Popen")
            raise InputProbeStopped("unexpected_subprocess")

        def capture(adapter, client, operation, kwargs):
            if self.sdk is not None:
                raise InputProbeStopped("multiple_sdk_requests")
            payload = redact_payload(kwargs)
            path = self.branch / "first-sdk.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.sdk = stamp(path)
            self.audit = compare_first_sdk(
                json.loads(self.plan.source.request.path.read_text(encoding="utf-8")),
                payload,
                sample_id=f"{self.arm}1",
                source_sha256=self.plan.source.request.sha256,
                wall_upper=self.plan.source.remaining.wall_seconds_at_input,
            )
            write_record(self.branch / "first-sdk-audit.json", self.audit)
            # No call to the SDK implementation, no synthetic model response.
            raise InputProbeStopped("first_sdk_captured")

        replacements = (
            (OpenAIModelClient, "_create_chat_completion", capture),
            (httpx.Client, "send", blocked_http),
            (httpx.AsyncClient, "send", blocked_async_http),
            (requests.Session, "send", blocked_http),
            (urllib.request.OpenerDirector, "open", blocked_http),
            (http.client.HTTPConnection, "connect", blocked_http),
            (subprocess, "Popen", blocked_process),
        )
        originals = [
            (owner, name, getattr(owner, name)) for owner, name, _ in replacements
        ]
        try:
            for owner, name, replacement in replacements:
                setattr(owner, name, replacement)
            yield
        finally:
            for owner, name, original in reversed(originals):
                setattr(owner, name, original)


def _validate_arm(plan: GroupPlan, directory: Path, arm: Literal["B", "C"]):
    from personal_agent.application.conversation.models import InteractionTrace
    from personal_agent.infra.storage.postgres_common import (
        close_postgres_connection_pools,
    )

    branch = directory / arm
    restore_branch(plan, branch)
    settings = branch_settings(plan, branch)
    configuration = root_configuration(plan, settings)
    write_record(branch / "root-configuration.json", configuration)
    original = InteractionTrace.model_validate_json(plan.source.trace.path.read_bytes())
    probe = InputProbe(branch, plan, arm)
    context = None
    reason, error_type = "runtime_returned_without_sdk", None
    with probe.installed(), branch_environment(branch):
        try:
            context = build_branch_context(settings, baseline=arm == "B")
            converse_source(context.service, original)
        except InputProbeStopped as stopped:
            reason = str(stopped)
        except Exception as error:
            reason, error_type = (
                "composition_or_conversation_failure",
                type(error).__name__,
            )
        finally:
            if context is not None:
                context.shutdown()
            else:
                close_postgres_connection_pools()
    result = ArmInputValidation(
        arm=arm,
        reason=reason,
        passed=(
            reason == "first_sdk_captured"
            and probe.audit is not None
            and probe.audit.passed
            and not probe.blocked_http
            and not probe.blocked_processes
        ),
        sdk=probe.sdk,
        audit=probe.audit,
        configuration=configuration,
        clock_mapping=stamp(branch / "clock-mapping.json"),
        blocked_http=tuple(probe.blocked_http),
        blocked_processes=tuple(probe.blocked_processes),
        error_type=error_type,
    )
    write_record(branch / "result.json", result)
    return result


def validate_inputs(group: Path, directory: Path) -> InputValidation:
    """旧 seal 仅取源；当前代码／Spec身份在独立预检目录重新封存。"""
    if directory.exists():
        raise FileExistsError("预检目录必须不存在；不覆盖旧预检或准备失败")
    seal = PreparationSeal.model_validate_json(
        (group / "preparation-seal.json").read_bytes()
    )
    for item in (seal.plan, seal.code_snapshot, seal.preflight):
        verify_file(item)
    plan = GroupPlan.model_validate_json((group / "plan.json").read_bytes())
    if select_source(seal.preflight.path) != plan.source:
        raise ValueError("预检不能改变既有组的真实来源")
    plan_bytes, state_bytes = (
        (group / "plan.json").read_bytes(),
        (group / "group-state.json").read_bytes(),
    )
    current = plan.model_copy(
        update={"code_files": code_identity(), "authority": stamp(AUTHORITY)}
    )
    verify_plan(current)
    directory.mkdir(parents=True)
    (directory / "source-group-plan.json").write_bytes(plan_bytes)
    (directory / "group-state-at-validation.json").write_bytes(state_bytes)
    write_record(directory / "validation-plan.json", current)
    with ZipFile(
        directory / "code-snapshot.zip", "x", compression=ZIP_DEFLATED
    ) as archive:
        for name in current.code_files:
            archive.write(ROOT / name, name)
        archive.write(AUTHORITY, AUTHORITY.relative_to(ROOT).as_posix())
    started = datetime.now(UTC)
    arms = (
        _validate_arm(current, directory, "B"),
        _validate_arm(current, directory, "C"),
    )
    state_unchanged = (group / "group-state.json").read_bytes() == state_bytes
    result = InputValidation(
        group_id=plan.group_id,
        started_at=started,
        finished_at=datetime.now(UTC),
        validation_plan=stamp(directory / "validation-plan.json"),
        preserved_group_plan=stamp(directory / "source-group-plan.json"),
        preserved_group_state=stamp(directory / "group-state-at-validation.json"),
        group_state_unchanged=state_unchanged,
        arms=arms,
        passed=state_unchanged and all(item.passed for item in arms),
    )
    verify_plan(current)
    if (group / "plan.json").read_bytes() != plan_bytes:
        raise ValueError("预检期间组身份发生变化；不能把预检当作新身份通过")
    write_record(directory / "validation-result.json", result)
    write_record(
        directory / "validation-seal.json",
        InputValidationSeal(
            files=tuple(
                stamp(path) for path in sorted(directory.rglob("*")) if path.is_file()
            )
        ),
    )
    return result


def require_validated_inputs(directory: Path, plan: GroupPlan, settings) -> None:
    seal = InputValidationSeal.model_validate_json(
        (directory / "validation-seal.json").read_bytes()
    )
    for item in seal.files:
        verify_file(item)
    result = InputValidation.model_validate_json(
        (directory / "validation-result.json").read_bytes()
    )
    validated = GroupPlan.model_validate_json(result.validation_plan.path.read_bytes())
    if (
        not result.passed
        or validated != plan
        or {item.arm for item in result.arms} != {"B", "C"}
    ):
        raise ValueError("须先通过当前代码／Spec身份的完整两arm零HTTP预检")
    actual = root_configuration(plan, settings).comparison_identity()
    if any(item.configuration.comparison_identity() != actual for item in result.arms):
        raise ValueError("实际root配置与两arm已封存预检不同，不能付费")
