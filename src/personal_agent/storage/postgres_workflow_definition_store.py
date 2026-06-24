from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.kernel.contracts.workflow import (
    WorkflowRegistryProtocol,
    WorkflowSpec,
)
from personal_agent.storage.postgres_common import PostgresStoreBase


@dataclass(frozen=True, slots=True)
class WorkflowDeployment:
    workflow_id: str
    environment: str
    stable_version: str
    status: str = "stable"
    canary_version: str | None = None
    canary_percent: int = 0


@dataclass(frozen=True, slots=True)
class WorkflowEvalRun:
    eval_run_id: str
    workflow_id: str
    version: str
    suite: str
    status: str
    passed: bool
    score: float | None
    metrics: dict
    report: dict


class PostgresWorkflowDefinitionStore(PostgresStoreBase):
    """Versioned workflow definitions and deployment selectors.

    The static in-repo ``WorkflowRegistry`` remains the source for code-owned
    definitions. This store persists those definitions, pins active deployments,
    and gives runtime selection a stable platform boundary for future canary and
    version migration work.
    """

    def ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_definitions (
                        workflow_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        spec JSONB NOT NULL,
                        status TEXT NOT NULL DEFAULT 'registered',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (workflow_id, version)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_definitions_intent_idx
                    ON workflow_definitions (intent, workflow_id, version)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_deployments (
                        workflow_id TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'default',
                        stable_version TEXT NOT NULL,
                        canary_version TEXT,
                        canary_percent INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'stable',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (workflow_id, environment)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_eval_runs (
                        eval_run_id TEXT PRIMARY KEY,
                        workflow_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        suite TEXT NOT NULL,
                        status TEXT NOT NULL,
                        passed BOOLEAN NOT NULL,
                        score DOUBLE PRECISION,
                        metrics JSONB NOT NULL,
                        report JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS workflow_eval_runs_gate_idx
                    ON workflow_eval_runs (workflow_id, version, suite, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_eval_policies (
                        workflow_id TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'default',
                        policy JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (workflow_id, environment)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS workflow_state_migrations (
                        workflow_id TEXT NOT NULL,
                        from_version TEXT NOT NULL,
                        to_version TEXT NOT NULL,
                        step_mapping JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (workflow_id, from_version, to_version)
                    )
                    """
                )
        self._initialized = True

    def sync_registry(
        self,
        registry: WorkflowRegistryProtocol,
        *,
        environment: str = "default",
    ) -> int:
        """Upsert all code-owned specs and initialize stable deployments."""
        self.ensure_schema()
        specs = registry.all_specs()
        with self._connect() as conn:
            with conn.cursor() as cur:
                for spec in specs:
                    cur.execute(
                        """
                        INSERT INTO workflow_definitions (
                            workflow_id, version, intent, spec, status
                        )
                        VALUES (%s, %s, %s, %s, 'registered')
                        ON CONFLICT (workflow_id, version) DO UPDATE
                        SET intent = EXCLUDED.intent,
                            spec = EXCLUDED.spec,
                            updated_at = now()
                        """,
                        (
                            spec.workflow_id,
                            spec.version,
                            spec.intent,
                            Jsonb(spec.to_definition_payload()),
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO workflow_deployments (
                            workflow_id, environment, stable_version, status
                        )
                        VALUES (%s, %s, %s, 'stable')
                        ON CONFLICT (workflow_id, environment) DO NOTHING
                        """,
                        (spec.workflow_id, environment, spec.version),
                    )
        return len(specs)

    def set_deployment(
        self,
        workflow_id: str,
        *,
        stable_version: str,
        environment: str = "default",
        status: str = "stable",
        canary_version: str | None = None,
        canary_percent: int = 0,
        require_eval_gate: bool = True,
        eval_suite: str = "default",
    ) -> WorkflowDeployment:
        self.ensure_schema()
        status = status if status in {"stable", "canary", "disabled"} else "stable"
        canary_percent = max(0, min(100, int(canary_percent)))
        if require_eval_gate and status != "disabled":
            target_version = canary_version if status == "canary" and canary_version else stable_version
            gate = self.evaluate_deployment_gate(
                workflow_id,
                target_version,
                environment=environment,
                fallback_suite=eval_suite,
            )
            if not gate["passed"]:
                raise ValueError(
                    "Workflow deployment blocked by eval gate: "
                    f"workflow_id={workflow_id} version={target_version} suite={eval_suite} "
                    f"status={gate['status']}"
                )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_deployments (
                        workflow_id, environment, stable_version, canary_version,
                        canary_percent, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (workflow_id, environment) DO UPDATE
                    SET stable_version = EXCLUDED.stable_version,
                        canary_version = EXCLUDED.canary_version,
                        canary_percent = EXCLUDED.canary_percent,
                        status = EXCLUDED.status,
                        updated_at = now()
                    """,
                    (
                        workflow_id,
                        environment,
                        stable_version,
                        canary_version,
                        canary_percent,
                        status,
                    ),
                )
        return WorkflowDeployment(
            workflow_id=workflow_id,
            environment=environment,
            stable_version=stable_version,
            status=status,
            canary_version=canary_version,
            canary_percent=canary_percent,
        )

    def record_eval_run(
        self,
        *,
        workflow_id: str,
        version: str,
        suite: str = "default",
        passed: bool,
        score: float | None = None,
        metrics: dict | None = None,
        report: dict | None = None,
        eval_run_id: str | None = None,
    ) -> WorkflowEvalRun:
        """Record an offline eval result usable by the deployment gate."""
        from uuid import uuid4

        self.ensure_schema()
        run_id = eval_run_id or f"eval-{uuid4().hex[:16]}"
        status = "passed" if passed else "failed"
        metrics_payload = dict(metrics or {})
        report_payload = dict(report or {})
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_eval_runs (
                        eval_run_id, workflow_id, version, suite, status, passed,
                        score, metrics, report
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING eval_run_id, workflow_id, version, suite, status,
                              passed, score, metrics, report
                    """,
                    (
                        run_id,
                        workflow_id,
                        version,
                        suite,
                        status,
                        passed,
                        score,
                        Jsonb(metrics_payload),
                        Jsonb(report_payload),
                    ),
                )
                row = cur.fetchone()
        return _eval_run_from_row(row)

    def latest_eval_run(
        self,
        workflow_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> WorkflowEvalRun | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT eval_run_id, workflow_id, version, suite, status,
                           passed, score, metrics, report
                    FROM workflow_eval_runs
                    WHERE workflow_id = %s AND version = %s AND suite = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (workflow_id, version, suite),
                )
                row = cur.fetchone()
        return _eval_run_from_row(row) if row else None

    def get_eval_gate_status(
        self,
        workflow_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> dict[str, object]:
        latest = self.latest_eval_run(workflow_id, version, suite=suite)
        if latest is None:
            return {
                "workflow_id": workflow_id,
                "version": version,
                "suite": suite,
                "status": "missing",
                "passed": False,
                "eval_run_id": None,
            }
        return {
            "workflow_id": workflow_id,
            "version": version,
            "suite": suite,
            "status": latest.status,
            "passed": latest.passed,
            "eval_run_id": latest.eval_run_id,
            "score": latest.score,
            "metrics": latest.metrics,
        }

    def set_eval_policy(
        self,
        workflow_id: str,
        *,
        required_suites: list[dict[str, object]],
        environment: str = "default",
    ) -> dict[str, object]:
        self.ensure_schema()
        normalized: list[dict[str, object]] = []
        for item in required_suites:
            suite = str(item.get("suite") or "").strip()
            if not suite:
                continue
            normalized.append({
                "suite": suite,
                "min_score": item.get("min_score"),
                "metric_thresholds": dict(item.get("metric_thresholds") or {}),
            })
        policy = {"required_suites": normalized}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_eval_policies (
                        workflow_id, environment, policy
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (workflow_id, environment) DO UPDATE
                    SET policy = EXCLUDED.policy,
                        updated_at = now()
                    """,
                    (workflow_id, environment, Jsonb(policy)),
                )
        return policy

    def get_eval_policy(
        self,
        workflow_id: str,
        *,
        environment: str = "default",
    ) -> dict[str, object] | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT policy
                    FROM workflow_eval_policies
                    WHERE workflow_id = %s AND environment = %s
                    """,
                    (workflow_id, environment),
                )
                row = cur.fetchone()
        return dict(row["policy"] or {}) if row else None

    def evaluate_deployment_gate(
        self,
        workflow_id: str,
        version: str,
        *,
        environment: str = "default",
        fallback_suite: str = "default",
    ) -> dict[str, object]:
        policy = self.get_eval_policy(workflow_id, environment=environment)
        required = list((policy or {}).get("required_suites") or [])
        if not required:
            return self.get_eval_gate_status(workflow_id, version, suite=fallback_suite)

        suite_results: list[dict[str, object]] = []
        all_passed = True
        for requirement in required:
            suite = str(requirement.get("suite") or "")
            latest = self.latest_eval_run(workflow_id, version, suite=suite)
            reasons: list[str] = []
            if latest is None:
                reasons.append("missing")
            else:
                if not latest.passed:
                    reasons.append("failed")
                min_score = requirement.get("min_score")
                if min_score is not None and (
                    latest.score is None or latest.score < float(min_score)
                ):
                    reasons.append(f"score<{min_score}")
                for metric, threshold in dict(
                    requirement.get("metric_thresholds") or {}
                ).items():
                    value = latest.metrics.get(metric)
                    if value is None or float(value) < float(threshold):
                        reasons.append(f"{metric}<{threshold}")
            passed = not reasons
            all_passed = all_passed and passed
            suite_results.append({
                "suite": suite,
                "passed": passed,
                "reasons": reasons,
                "eval_run_id": latest.eval_run_id if latest else None,
            })
        return {
            "workflow_id": workflow_id,
            "version": version,
            "environment": environment,
            "status": "passed" if all_passed else "failed",
            "passed": all_passed,
            "suites": suite_results,
        }

    def get_deployment(
        self,
        workflow_id: str,
        *,
        environment: str = "default",
    ) -> WorkflowDeployment | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT workflow_id, environment, stable_version, canary_version,
                           canary_percent, status
                    FROM workflow_deployments
                    WHERE workflow_id = %s AND environment = %s
                    """,
                    (workflow_id, environment),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return WorkflowDeployment(
            workflow_id=row["workflow_id"],
            environment=row["environment"],
            stable_version=row["stable_version"],
            status=row["status"],
            canary_version=row["canary_version"],
            canary_percent=row["canary_percent"],
        )

    def get_definition(self, workflow_id: str, version: str) -> WorkflowSpec | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT spec
                    FROM workflow_definitions
                    WHERE workflow_id = %s AND version = %s
                    """,
                    (workflow_id, version),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return WorkflowSpec.from_definition_payload(row["spec"] or {})

    def set_state_migration(
        self,
        workflow_id: str,
        *,
        from_version: str,
        to_version: str,
        step_mapping: dict[str, str] | None = None,
    ) -> dict[str, object]:
        self.ensure_schema()
        mapping = dict(step_mapping or {})
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workflow_state_migrations (
                        workflow_id, from_version, to_version, step_mapping
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (workflow_id, from_version, to_version) DO UPDATE
                    SET step_mapping = EXCLUDED.step_mapping,
                        updated_at = now()
                    """,
                    (workflow_id, from_version, to_version, Jsonb(mapping)),
                )
        return {
            "workflow_id": workflow_id,
            "from_version": from_version,
            "to_version": to_version,
            "step_mapping": mapping,
        }

    def get_state_migration(
        self,
        workflow_id: str,
        *,
        from_version: str,
        to_version: str,
    ) -> dict[str, object] | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT workflow_id, from_version, to_version, step_mapping
                    FROM workflow_state_migrations
                    WHERE workflow_id = %s AND from_version = %s AND to_version = %s
                    """,
                    (workflow_id, from_version, to_version),
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def select_active_spec(
        self,
        intent: str,
        *,
        registry: WorkflowRegistryProtocol,
        environment: str = "default",
        routing_key: str = "",
    ) -> WorkflowSpec | None:
        """Return the deployed spec for an intent, or None when disabled/missing."""
        static_spec = registry.select(intent)
        deployment = self.get_deployment(static_spec.workflow_id, environment=environment)
        if deployment is None:
            return static_spec
        if deployment.status == "disabled":
            return None
        version = deployment.stable_version
        if (
            deployment.status == "canary"
            and deployment.canary_version
            and deployment.canary_percent > 0
        ):
            bucket_key = routing_key or static_spec.workflow_id
            bucket = int(
                sha256(f"{static_spec.workflow_id}:{bucket_key}".encode("utf-8")).hexdigest()[:8],
                16,
            ) % 100
            if bucket < deployment.canary_percent:
                version = deployment.canary_version
        return self.get_definition(static_spec.workflow_id, version) or static_spec

    def list_definitions(self) -> list[dict[str, object]]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.workflow_id, d.version, d.intent, d.status,
                           dep.environment, dep.stable_version, dep.canary_version,
                           dep.canary_percent, dep.status AS deployment_status
                    FROM workflow_definitions d
                    LEFT JOIN workflow_deployments dep
                      ON dep.workflow_id = d.workflow_id
                    ORDER BY d.workflow_id, d.version
                    """
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def record_definitions(self, specs: Iterable[WorkflowSpec]) -> int:
        self.ensure_schema()
        count = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for spec in specs:
                    cur.execute(
                        """
                        INSERT INTO workflow_definitions (
                            workflow_id, version, intent, spec, status
                        )
                        VALUES (%s, %s, %s, %s, 'registered')
                        ON CONFLICT (workflow_id, version) DO UPDATE
                        SET intent = EXCLUDED.intent,
                            spec = EXCLUDED.spec,
                            updated_at = now()
                        """,
                        (
                            spec.workflow_id,
                            spec.version,
                            spec.intent,
                            Jsonb(spec.to_definition_payload()),
                        ),
                    )
                    count += 1
        return count


def _eval_run_from_row(row) -> WorkflowEvalRun:
    return WorkflowEvalRun(
        eval_run_id=row["eval_run_id"],
        workflow_id=row["workflow_id"],
        version=row["version"],
        suite=row["suite"],
        status=row["status"],
        passed=bool(row["passed"]),
        score=row["score"],
        metrics=row["metrics"] or {},
        report=row["report"] or {},
    )
