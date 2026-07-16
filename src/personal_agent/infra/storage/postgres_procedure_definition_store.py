from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from personal_agent.capabilities.contracts.procedure import (
    ProcedureCatalogPort,
    ProcedureDefinition,
)
from personal_agent.infra.storage.postgres_common import PostgresStoreBase


@dataclass(frozen=True, slots=True)
class ProcedureDeployment:
    procedure_id: str
    environment: str
    stable_version: str
    status: str = "stable"
    canary_version: str | None = None
    canary_percent: int = 0


@dataclass(frozen=True, slots=True)
class ProcedureEvalRun:
    eval_run_id: str
    procedure_id: str
    version: str
    suite: str
    status: str
    passed: bool
    score: float | None
    metrics: dict
    report: dict


class PostgresProcedureDefinitionStore(PostgresStoreBase):
    """Versioned procedure definitions and deployment selectors.

        The static in-repo ``ProcedureCatalog`` remains the source for code-owned
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
                    CREATE TABLE IF NOT EXISTS procedure_definitions (
                        procedure_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        purpose TEXT NOT NULL,
                        spec JSONB NOT NULL,
                        status TEXT NOT NULL DEFAULT 'registered',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (procedure_id, version)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS procedure_definitions_purpose_idx
                    ON procedure_definitions (purpose, procedure_id, version)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS procedure_deployments (
                        procedure_id TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'default',
                        stable_version TEXT NOT NULL,
                        canary_version TEXT,
                        canary_percent INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'stable',
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (procedure_id, environment)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS procedure_eval_runs (
                        eval_run_id TEXT PRIMARY KEY,
                        procedure_id TEXT NOT NULL,
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
                    CREATE INDEX IF NOT EXISTS procedure_eval_runs_gate_idx
                    ON procedure_eval_runs (procedure_id, version, suite, created_at DESC)
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS procedure_eval_policies (
                        procedure_id TEXT NOT NULL,
                        environment TEXT NOT NULL DEFAULT 'default',
                        policy JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (procedure_id, environment)
                    )
                    """
                )
        self._initialized = True

    def sync_registry(
        self,
        registry: ProcedureCatalogPort,
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
                        INSERT INTO procedure_definitions (
                            procedure_id, version, purpose, spec, status
                        )
                        VALUES (%s, %s, %s, %s, 'registered')
                        ON CONFLICT (procedure_id, version) DO UPDATE
                        SET purpose = EXCLUDED.purpose,
                            spec = EXCLUDED.spec,
                            updated_at = now()
                        """,
                        (
                            spec.procedure_id,
                            spec.version,
                            spec.purpose,
                            Jsonb(spec.to_definition_payload()),
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO procedure_deployments (
                            procedure_id, environment, stable_version, status
                        )
                        VALUES (%s, %s, %s, 'stable')
                        ON CONFLICT (procedure_id, environment) DO NOTHING
                        """,
                        (spec.procedure_id, environment, spec.version),
                    )
        return len(specs)

    def set_deployment(
        self,
        procedure_id: str,
        *,
        stable_version: str,
        environment: str = "default",
        status: str = "stable",
        canary_version: str | None = None,
        canary_percent: int = 0,
        require_eval_gate: bool = True,
        eval_suite: str = "default",
    ) -> ProcedureDeployment:
        self.ensure_schema()
        status = status if status in {"stable", "canary", "disabled"} else "stable"
        canary_percent = max(0, min(100, int(canary_percent)))
        if require_eval_gate and status != "disabled":
            target_version = canary_version if status == "canary" and canary_version else stable_version
            gate = self.evaluate_deployment_gate(
                procedure_id,
                target_version,
                environment=environment,
                fallback_suite=eval_suite,
            )
            if not gate["passed"]:
                raise ValueError(
                    "Procedure deployment blocked by eval gate: "
                    f"procedure_id={procedure_id} version={target_version} suite={eval_suite} "
                    f"status={gate['status']}"
                )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO procedure_deployments (
                        procedure_id, environment, stable_version, canary_version,
                        canary_percent, status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (procedure_id, environment) DO UPDATE
                    SET stable_version = EXCLUDED.stable_version,
                        canary_version = EXCLUDED.canary_version,
                        canary_percent = EXCLUDED.canary_percent,
                        status = EXCLUDED.status,
                        updated_at = now()
                    """,
                    (
                        procedure_id,
                        environment,
                        stable_version,
                        canary_version,
                        canary_percent,
                        status,
                    ),
                )
        return ProcedureDeployment(
            procedure_id=procedure_id,
            environment=environment,
            stable_version=stable_version,
            status=status,
            canary_version=canary_version,
            canary_percent=canary_percent,
        )

    def record_eval_run(
        self,
        *,
        procedure_id: str,
        version: str,
        suite: str = "default",
        passed: bool,
        score: float | None = None,
        metrics: dict | None = None,
        report: dict | None = None,
        eval_run_id: str | None = None,
    ) -> ProcedureEvalRun:
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
                    INSERT INTO procedure_eval_runs (
                        eval_run_id, procedure_id, version, suite, status, passed,
                        score, metrics, report
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING eval_run_id, procedure_id, version, suite, status,
                              passed, score, metrics, report
                    """,
                    (
                        run_id,
                        procedure_id,
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
        procedure_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> ProcedureEvalRun | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT eval_run_id, procedure_id, version, suite, status,
                           passed, score, metrics, report
                    FROM procedure_eval_runs
                    WHERE procedure_id = %s AND version = %s AND suite = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (procedure_id, version, suite),
                )
                row = cur.fetchone()
        return _eval_run_from_row(row) if row else None

    def get_eval_gate_status(
        self,
        procedure_id: str,
        version: str,
        *,
        suite: str = "default",
    ) -> dict[str, object]:
        latest = self.latest_eval_run(procedure_id, version, suite=suite)
        if latest is None:
            return {
                "procedure_id": procedure_id,
                "version": version,
                "suite": suite,
                "status": "missing",
                "passed": False,
                "eval_run_id": None,
            }
        return {
            "procedure_id": procedure_id,
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
        procedure_id: str,
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
                    INSERT INTO procedure_eval_policies (
                        procedure_id, environment, policy
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (procedure_id, environment) DO UPDATE
                    SET policy = EXCLUDED.policy,
                        updated_at = now()
                    """,
                    (procedure_id, environment, Jsonb(policy)),
                )
        return policy

    def get_eval_policy(
        self,
        procedure_id: str,
        *,
        environment: str = "default",
    ) -> dict[str, object] | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT policy
                    FROM procedure_eval_policies
                    WHERE procedure_id = %s AND environment = %s
                    """,
                    (procedure_id, environment),
                )
                row = cur.fetchone()
        return dict(row["policy"] or {}) if row else None

    def evaluate_deployment_gate(
        self,
        procedure_id: str,
        version: str,
        *,
        environment: str = "default",
        fallback_suite: str = "default",
    ) -> dict[str, object]:
        policy = self.get_eval_policy(procedure_id, environment=environment)
        required = list((policy or {}).get("required_suites") or [])
        if not required:
            return self.get_eval_gate_status(procedure_id, version, suite=fallback_suite)

        suite_results: list[dict[str, object]] = []
        all_passed = True
        for requirement in required:
            suite = str(requirement.get("suite") or "")
            latest = self.latest_eval_run(procedure_id, version, suite=suite)
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
            "procedure_id": procedure_id,
            "version": version,
            "environment": environment,
            "status": "passed" if all_passed else "failed",
            "passed": all_passed,
            "suites": suite_results,
        }

    def get_deployment(
        self,
        procedure_id: str,
        *,
        environment: str = "default",
    ) -> ProcedureDeployment | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT procedure_id, environment, stable_version, canary_version,
                           canary_percent, status
                    FROM procedure_deployments
                    WHERE procedure_id = %s AND environment = %s
                    """,
                    (procedure_id, environment),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProcedureDeployment(
            procedure_id=row["procedure_id"],
            environment=row["environment"],
            stable_version=row["stable_version"],
            status=row["status"],
            canary_version=row["canary_version"],
            canary_percent=row["canary_percent"],
        )

    def get_definition(self, procedure_id: str, version: str) -> ProcedureDefinition | None:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT spec
                    FROM procedure_definitions
                    WHERE procedure_id = %s AND version = %s
                    """,
                    (procedure_id, version),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return ProcedureDefinition.from_definition_payload(row["spec"] or {})

    def select_active_spec(
        self,
        procedure_id: str,
        *,
        registry: ProcedureCatalogPort,
        environment: str = "default",
        routing_key: str = "",
    ) -> ProcedureDefinition | None:
        """Return the deployed spec by identity, or None when disabled."""
        static_spec = registry.get(procedure_id)
        deployment = self.get_deployment(static_spec.procedure_id, environment=environment)
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
            bucket_key = routing_key or static_spec.procedure_id
            bucket = int(
                sha256(f"{static_spec.procedure_id}:{bucket_key}".encode("utf-8")).hexdigest()[:8],
                16,
            ) % 100
            if bucket < deployment.canary_percent:
                version = deployment.canary_version
        return self.get_definition(static_spec.procedure_id, version) or static_spec

    def list_definitions(self) -> list[dict[str, object]]:
        self.ensure_schema()
        with self._connect(row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT d.procedure_id, d.version, d.purpose, d.status,
                           dep.environment, dep.stable_version, dep.canary_version,
                           dep.canary_percent, dep.status AS deployment_status
                    FROM procedure_definitions d
                    LEFT JOIN procedure_deployments dep
                      ON dep.procedure_id = d.procedure_id
                    ORDER BY d.procedure_id, d.version
                    """
                )
                rows = cur.fetchall()
        return [dict(row) for row in rows]

    def record_definitions(self, specs: Iterable[ProcedureDefinition]) -> int:
        self.ensure_schema()
        count = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for spec in specs:
                    cur.execute(
                        """
                        INSERT INTO procedure_definitions (
                            procedure_id, version, purpose, spec, status
                        )
                        VALUES (%s, %s, %s, %s, 'registered')
                        ON CONFLICT (procedure_id, version) DO UPDATE
                        SET purpose = EXCLUDED.purpose,
                            spec = EXCLUDED.spec,
                            updated_at = now()
                        """,
                        (
                            spec.procedure_id,
                            spec.version,
                            spec.purpose,
                            Jsonb(spec.to_definition_payload()),
                        ),
                    )
                    count += 1
        return count


def _eval_run_from_row(row) -> ProcedureEvalRun:
    return ProcedureEvalRun(
        eval_run_id=row["eval_run_id"],
        procedure_id=row["procedure_id"],
        version=row["version"],
        suite=row["suite"],
        status=row["status"],
        passed=bool(row["passed"]),
        score=row["score"],
        metrics=row["metrics"] or {},
        report=row["report"] or {},
    )
