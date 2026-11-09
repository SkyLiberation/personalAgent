"""检索实验唯一业务入口：授权快照、冻结、外部执行和正式发布。"""

from __future__ import annotations

from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.kernel.contracts.tool_runtime import accepted_tool_request_digest
from .contracts import (
    BM25Config,
    CandidateConfig,
    Coverage,
    DenseConfig,
    ExperimentResult,
    RRFConfig,
    canonical_digest,
)
from .models import (
    BackendOutcome,
    BoundArtifact,
    BoundInputIdentity,
    CandidateDevelopment,
    DevelopmentWorkload,
    EvaluateFinal,
    ExperimentAction,
    ExperimentActionReceipt,
    ExperimentCommand,
    ExperimentExecutionFact,
    ExperimentJournalView,
    ExperimentMetricSummary,
    ExperimentRecord,
    ExperimentToolArgs,
    ExperimentToolResult,
    FinalWorkload,
    FreezeExperiment,
    PublishedExperimentResult,
    PublishedFrozenExperiment,
    RetrievalDeployment,
    RunDevelopment,
)
from .ports import (
    ExperimentArtifactPort,
    ExperimentExecutionPort,
    ExperimentJournalPort,
)
from .rules import freeze_experiment
from .results import PublishedExperimentReader


def _json_bytes(value: BaseModel) -> bytes:
    return (
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


class RetrievalExperimentService:
    def __init__(
        self,
        *,
        artifacts: ExperimentArtifactPort,
        journal: ExperimentJournalPort,
        execution: ExperimentExecutionPort,
        deployment: RetrievalDeployment,
        prompts: PromptCatalog = DEFAULT_PROMPTS,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._prompts = prompts
        self.artifacts = artifacts
        self.journal = journal
        self.execution = execution
        self.deployment = deployment
        self.clock = clock
        self.reader = PublishedExperimentReader(
            artifacts=artifacts, deployment=deployment, prompts=prompts,
        )

    def _read(
        self, ref: ResourceRef, scope: ExecutionScope, *, private: bool = False
    ) -> BoundArtifact:
        principal = self.deployment.scorer_principal if private else scope.principal
        _, content = self.artifacts.read_upload(
            ref, principal=principal, owner=principal
        )
        metadata = self.artifacts.resource_item(
            ref, principal=principal, owner=principal
        )
        return BoundArtifact.model_validate({'resource_ref': ref, 'content_digest': metadata.content_digest, 'content': content}, context=self._prompts)

    def read_result(
        self, ref: ResourceRef, *, execution_scope: ExecutionScope
    ) -> tuple[PublishedExperimentResult, ExperimentResult, tuple[BoundArtifact, ...]]:
        return self.reader.read_result(ref, execution_scope=execution_scope)

    def read_frozen(
        self, ref: ResourceRef, *, execution_scope: ExecutionScope
    ) -> PublishedFrozenExperiment:
        return self.reader.read_frozen(ref, execution_scope=execution_scope)

    def _publish(
        self,
        scope: ExecutionScope,
        key: str,
        name: str,
        content: bytes,
        sources: tuple[ResourceRef, ...],
        mime: str = "application/json",
        limitations: tuple[str, ...] = (),
    ) -> ResourceRef:
        return self.artifacts.publish_machine(
            execution_scope=scope,
            producer_key=f"retrieval-experiment:{key}:{name}",
            producer_ref=key,
            filename=name,
            content_type=mime,
            file_bytes=content,
            kind="retrieval_experiment",
            source_artifact_refs=tuple(dict.fromkeys(sources)),
            limitations=limitations,
        )

    def execute(
        self,
        action: ExperimentAction,
        *,
        execution_scope: ExecutionScope,
        action_id: str,
        request_digest: str,
    ) -> ExperimentToolResult:
        scope = execution_scope
        if scope.principal != self.deployment.authorized_principal:
            raise PermissionError(self._prompts.render('retrieval_experiment.authorization'))
        expected = accepted_tool_request_digest(
            execution_scope=scope,
            action_id=action_id,
            tool_name="retrieval_experiment",
            arguments=ExperimentToolArgs(action=action),
        )
        if request_digest != expected:
            raise PermissionError(self._prompts.render('retrieval_experiment.request_digest'))
        view = self.journal.load(
            execution_scope=scope, action_id=action_id, request_digest=request_digest
        )
        if (
            view.execution_scope != scope
            or view.action_id != action_id
            or view.action != action
            or view.request_digest != request_digest
            or view.deployment_digest != self.deployment.deployment_digest
        ):
            raise PermissionError(self._prompts.render('retrieval_experiment.accepted_deployment'))
        record = next(
            (item for item in view.records if item.action_id == action_id), None
        )
        if record and record.receipt and record.receipt.status != "unknown":
            if record.command is not None:
                self.execution.cleanup(record.command)
            return self._response(record.receipt, record, scope)
        if isinstance(action, FreezeExperiment):
            return self._freeze(action, view)
        if record and record.command:
            command = record.command
            if record.execution is not None:
                outcome = self.execution.reconcile(command)
            else:
                inputs = self._inputs(command, scope)
                self.journal.record_execution(
                    execution_scope=scope,
                    action_id=action_id,
                    fact=ExperimentExecutionFact(status="dispatching"),
                )
                outcome = self.execution.execute(command, inputs)
        else:
            command, inputs = self._command(action, view)
            self.journal.bind_command(
                execution_scope=scope, action_id=action_id, command=command
            )
            self.journal.record_execution(
                execution_scope=scope,
                action_id=action_id,
                fact=ExperimentExecutionFact(status="dispatching"),
            )
            outcome = self.execution.execute(command, inputs)
        self.journal.record_execution(
            execution_scope=scope, action_id=action_id, fact=outcome.execution
        )
        receipt = self._publish_outcome(command, outcome)
        self.journal.record_result(
            execution_scope=scope, action_id=action_id, receipt=receipt
        )
        if receipt.status != "unknown":
            self.execution.cleanup(command)
        return self._response(
            receipt,
            ExperimentRecord(
                action_id=action_id,
                request_digest=request_digest,
                command=command,
                execution=outcome.execution,
                receipt=receipt,
            ),
            scope,
        )

    def _completed_results(
        self, view: ExperimentJournalView
    ) -> tuple[ResourceRef, ...]:
        return tuple(
            ref
            for item in view.records
            if item.receipt and item.receipt.status == "succeeded"
            for ref in item.receipt.result_refs
        )

    def _require_result(self, ref: ResourceRef, view: ExperimentJournalView) -> None:
        if (
            ref not in self._completed_results(view)
            or ref not in view.allowed_artifact_refs
        ):
            raise PermissionError(self._prompts.render('retrieval_experiment.result_not_successful'))

    def _draft(
        self, ref: ResourceRef, view: ExperimentJournalView, mime: str
    ) -> BoundArtifact:
        if ref not in view.allowed_artifact_refs:
            raise PermissionError(self._prompts.render('retrieval_experiment.program_unreadable'))
        snapshot = self.artifacts.read_snapshot(
            ref,
            principal=view.execution_scope.principal,
            owner=view.execution_scope.principal,
        )
        if (
            snapshot.record.purpose != "draft"
            or (
                snapshot.record.execution_scope is None
                or snapshot.record.execution_scope.principal
                != view.execution_scope.principal
                or snapshot.record.execution_scope.execution_id
                != view.execution_scope.execution_id
                or snapshot.record.execution_scope.thread_id
                != view.execution_scope.thread_id
            )
            or snapshot.record.content_type != mime
        ):
            raise PermissionError(self._prompts.render('retrieval_experiment.program_not_draft'))
        return self._read(ref, view.execution_scope)

    def _command(
        self, action: RunDevelopment | EvaluateFinal, view: ExperimentJournalView
    ) -> tuple[ExperimentCommand, tuple[BoundArtifact, ...]]:
        scope = view.execution_scope
        inputs: list[BoundArtifact] = []
        if isinstance(action, RunDevelopment):
            if any(
                item.command
                and isinstance(item.command.workload, FinalWorkload)
                and item.execution is not None
                for item in view.records
            ):
                raise ValueError(self._prompts.render('retrieval_experiment.development_after_final'))
            request = action.request
            config = {
                "bm25": BM25Config,
                "dense": DenseConfig,
                "rrf": RRFConfig,
                "candidate": CandidateConfig,
            }[request.method](method=request.method, retrieve_k=request.retrieve_k)
            publications = []
            refs = getattr(request, "input_result_refs", ())
            if len(set(refs)) != len(refs):
                raise ValueError(self._prompts.render('retrieval_experiment.duplicate_input'))
            for ref in refs:
                self._require_result(ref, view)
                pub, result, files = self.read_result(ref, execution_scope=scope)
                if (
                    result.dataset.dataset_id != self.deployment.development.dataset_id
                    or result.dataset.split_id != self.deployment.development.split_id
                    or result.config.retrieve_k < config.retrieve_k
                ):
                    raise ValueError(self._prompts.render('retrieval_experiment.input_rankings'))
                publications.append(pub)
                inputs.extend(files)
            program_ref = config_ref = None
            if isinstance(request, CandidateDevelopment):
                program_ref, config_ref = request.program_ref, request.config_ref
                inputs.append(self._draft(program_ref, view, "text/x-python"))
                if config_ref:
                    inputs.append(self._draft(config_ref, view, "application/json"))
            workload = DevelopmentWorkload(
                operation=action.operation,
                config=config,
                input_results=tuple(publications),
                input_result_refs=refs,
                program_ref=program_ref,
                config_ref=config_ref,
            )
        else:
            frozen_refs = tuple(
                item.receipt.frozen_ref
                for item in view.records
                if item.receipt
                and item.receipt.status == "succeeded"
                and item.receipt.frozen_ref
            )
            if not frozen_refs or action.frozen_ref != frozen_refs[-1]:
                raise PermissionError(self._prompts.render('retrieval_experiment.freeze_not_submitted'))
            frozen_bytes = self._read(action.frozen_ref, scope)
            frozen = self.read_frozen(action.frozen_ref, execution_scope=scope)
            workload = FinalWorkload(
                operation=action.operation, frozen_ref=action.frozen_ref, frozen=frozen
            )
            inputs.append(frozen_bytes)
            for ref in (frozen.program_ref, frozen.config_ref):
                if ref:
                    inputs.append(self._read(ref, scope))
        for material in self.deployment.materials:
            if material.role == "test_qrels":
                continue
            snapshot = self._read(material.resource_ref, scope)
            if snapshot.content_digest != material.content_digest:
                raise ValueError(self._prompts.render('retrieval_experiment.deployment_changed'))
            inputs.append(snapshot)
        unique = {item.resource_ref: item for item in inputs}
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(self._prompts.render('retrieval_experiment.clock'))
        now = now.astimezone(timezone.utc)
        remaining = min(
            view.remaining_execution_seconds,
            (view.run_deadline_at - now).total_seconds(),
            self.deployment.limits.worker_timeout_seconds,
        )
        if remaining <= 0:
            raise ValueError(self._prompts.render('retrieval_experiment.deadline'))
        payload = dict(
            execution_scope=scope,
            action_id=view.action_id,
            request_digest=view.request_digest,
            deployment_digest=view.deployment_digest,
            workload=workload,
            bound_inputs=tuple(
                BoundInputIdentity(
                    resource_ref=x.resource_ref, content_digest=x.content_digest
                )
                for x in unique.values()
            ),
            accepted_at=now,
            deadline_at=now + timedelta(seconds=remaining),
            reserved_seconds=remaining,
        )
        # Pydantic's JSON encoding is shared by digest validation and persistence.
        from pydantic import TypeAdapter

        raw = TypeAdapter(dict).dump_python(payload, mode="json")
        command = ExperimentCommand.model_validate({**payload, 'command_digest': canonical_digest(raw)}, context=self._prompts)
        return command, self._inputs(command, scope)

    def _inputs(
        self, command: ExperimentCommand, scope: ExecutionScope
    ) -> tuple[BoundArtifact, ...]:
        items = []
        for binding in command.bound_inputs:
            content = self._read(binding.resource_ref, scope)
            if content.content_digest != binding.content_digest:
                raise ValueError(self._prompts.render('retrieval_experiment.snapshot_changed'))
            items.append(content)
        if isinstance(command.workload, FinalWorkload):
            private = next(
                x for x in self.deployment.materials if x.role == "test_qrels"
            )
            content = self._read(private.resource_ref, scope, private=True)
            if content.content_digest != private.content_digest:
                raise ValueError(self._prompts.render('retrieval_experiment.private_digest'))
            items.append(content)
        return tuple(items)

    def _freeze(
        self, action: FreezeExperiment, view: ExperimentJournalView
    ) -> ExperimentToolResult:
        scope = view.execution_scope
        self._require_result(action.selected_result_ref, view)
        for item in reversed(view.records):
            if item.receipt and item.receipt.frozen_ref:
                old = self.read_frozen(item.receipt.frozen_ref, execution_scope=scope)
                if old.selected_result_ref == action.selected_result_ref:
                    receipt = ExperimentActionReceipt(
                        operation="freeze",
                        status="succeeded",
                        frozen_ref=item.receipt.frozen_ref,
                    )
                    self.journal.record_result(
                        execution_scope=scope, action_id=view.action_id, receipt=receipt
                    )
                    return self._response(receipt, None, scope)
                if any(
                    r.command
                    and isinstance(r.command.workload, FinalWorkload)
                    and r.execution
                    for r in view.records
                ):
                    raise ValueError(self._prompts.render('retrieval_experiment.freeze_after_final'))
        pub, result, files = self.read_result(
            action.selected_result_ref, execution_scope=scope
        )
        parents, hashes = [], []
        for ref in pub.input_result_refs:
            self._require_result(ref, view)
            _, parent, contents = self.read_result(ref, execution_scope=scope)
            parents.append(parent)
            hashes.append(contents[1].content_digest)
        program = self._read(pub.program_ref, scope) if pub.program_ref else None
        config = self._read(pub.config_ref, scope) if pub.config_ref else None
        frozen = freeze_experiment(
            result,
            files[1].content_digest,
            Coverage.model_validate_json(files[3].content),
            tuple(parents),
            tuple(hashes),
            program_digest=program.content_digest if program else None,
            config_digest=config.content_digest
            if config
            else hashlib.sha256(b"").hexdigest(),
            prompts=self._prompts,
        )
        published = PublishedFrozenExperiment(
            frozen=frozen,
            selected_result_ref=action.selected_result_ref,
            input_result_refs=pub.input_result_refs,
            program_ref=pub.program_ref,
            config_ref=pub.config_ref,
        )
        ref = self._publish(
            scope,
            view.request_digest,
            "frozen.json",
            _json_bytes(published),
            (action.selected_result_ref,),
        )
        receipt = ExperimentActionReceipt(
            operation="freeze", status="succeeded", frozen_ref=ref
        )
        self.journal.record_result(
            execution_scope=scope, action_id=view.action_id, receipt=receipt
        )
        return self._response(receipt, None, scope)

    def _publish_outcome(
        self, command: ExperimentCommand, outcome: BackendOutcome
    ) -> ExperimentActionReceipt:
        scope, refs, publications = command.execution_scope, [], []
        source_refs = tuple(x.resource_ref for x in command.bound_inputs)
        for index, bundle in enumerate(outcome.results):
            key = f"{command.command_digest}:{index}"
            manifest = (
                self.deployment.development
                if bundle.result.dataset.split == "train"
                else self.deployment.final
            )
            projections: dict[str, BoundInputIdentity] = {}
            for role, content in (
                ("corpus", bundle.corpus_bytes),
                ("queries", bundle.queries_bytes),
            ):
                digest = hashlib.sha256(content).hexdigest()
                if digest != manifest.artifact_sha256[f"{role}.json"]:
                    raise ValueError(self._prompts.render('retrieval_experiment.projection_digest'))
                original = next(
                    item for item in self.deployment.materials if item.role == role
                )
                projection_ref = self._publish(
                    scope, key, f"{role}.json", content, (original.resource_ref,)
                )
                projections[role] = BoundInputIdentity(
                    resource_ref=projection_ref, content_digest=digest
                )
            file_refs = {}
            for name, content in (
                ("result", bundle.result_bytes),
                ("rankings", bundle.rankings),
                ("coverage", bundle.coverage),
                ("metrics", bundle.metrics),
                ("per_query", bundle.per_query),
            ):
                file_refs[name] = self._publish(
                    scope, key, f"{name}.json", content, source_refs
                )
            workload = command.workload
            if isinstance(workload, DevelopmentWorkload):
                parent_refs, program_ref, config_ref = (
                    workload.input_result_refs,
                    workload.program_ref,
                    workload.config_ref,
                )
            else:
                # Parent identity is the original raw result bytes, never wrapper serialization.
                by_digest = {
                    hashlib.sha256(b.result_bytes).hexdigest(): ref
                    for b, ref in zip(outcome.results[:index], refs)
                }
                parent_refs = tuple(by_digest[d] for d in bundle.result.input_results)
                program_ref = (
                    workload.frozen.program_ref if bundle.result.candidate else None
                )
                config_ref = (
                    workload.frozen.config_ref if bundle.result.candidate else None
                )
            published = PublishedExperimentResult(
                raw_result_ref=file_refs["result"],
                rankings_ref=file_refs["rankings"],
                coverage_ref=file_refs["coverage"],
                metrics_ref=file_refs["metrics"],
                per_query_ref=file_refs["per_query"],
                corpus=projections["corpus"],
                queries=projections["queries"],
                input_result_refs=parent_refs,
                program_ref=program_ref,
                config_ref=config_ref,
            )
            refs.append(
                self._publish(
                    scope,
                    key + ":publication",
                    "experiment.json",
                    _json_bytes(published),
                    (
                        *file_refs.values(),
                        *(item.resource_ref for item in projections.values()),
                    ),
                )
            )
            publications.append(published)
        diagnostics = tuple(
            self._publish(
                scope,
                command.command_digest + ":" + hashlib.sha256(item.content).hexdigest(),
                item.filename,
                item.content,
                (),
                item.content_type,
                item.limitations,
            )
            for item in outcome.diagnostics
        )
        return ExperimentActionReceipt(
            operation=command.workload.operation,
            status=outcome.execution.status,
            result_refs=tuple(refs),
            diagnostic_refs=diagnostics,
            error_code=outcome.execution.error_code,
        )

    def _response(
        self,
        receipt: ExperimentActionReceipt,
        record: ExperimentRecord | None,
        scope: ExecutionScope,
    ) -> ExperimentToolResult:
        summaries = []
        corpus = queries = None
        for ref in receipt.result_refs:
            published, result, _ = self.read_result(ref, execution_scope=scope)
            corpus, queries = published.corpus, published.queries
            summaries.append(
                ExperimentMetricSummary(
                    result_ref=ref,
                    publication=published,
                    method=result.config.method,
                    split=result.dataset.split,
                    query_count=result.metrics.query_count,
                    retrieve_k=result.config.retrieve_k,
                    metrics=result.metrics,
                )
            )
        fact = record.execution if record else None
        limitations = (
            [self._prompts.render('retrieval_experiment.unknown')] if receipt.status == "unknown" else []
        )
        for ref in receipt.diagnostic_refs:
            limitations.extend(
                self.artifacts.read_limitations(
                    ref, principal=scope.principal, owner=scope.principal
                )
            )
        return ExperimentToolResult(
            receipt=receipt,
            summaries=tuple(summaries),
            corpus=corpus,
            queries=queries,
            elapsed_seconds=fact.elapsed_seconds or 0 if fact else 0,
            unsettled_seconds=record.command.reserved_seconds
            if record and record.command and receipt.status == "unknown"
            else 0,
            limitations=tuple(dict.fromkeys(limitations)),
        )
