from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from hashlib import sha256
from urllib.parse import urlparse

import pytest

from evals.e2e_quality.trace_archive import TraceArchive
from evals.e2e_quality.measurements import BudgetProfile, MeasurementProfile
from evals.e2e_quality.evidence_catalog import (
    EVIDENCE_BY_NODE,
    EvidenceClaimKind,
)
from evals.e2e_quality.release_gate import (
    REQUIRED_NATIVE_EVIDENCE_IDS,
    REQUIRED_LOOP_EVIDENCE_IDS,
)
# Re-export only infrastructure fixtures. Importing the test-suite-wide
# autouse fixture would deliberately disable live providers, which is invalid
# for this suite.
from tests.conftest import (  # noqa: F401
    clean_postgres_business_tables,
    postgres_url,
    temp_dir,
)
from personal_agent.kernel.config import Settings


_ARCHIVE: TraceArchive | None = None


@pytest.fixture(scope="module")
def server_temp_dir(request: pytest.FixtureRequest) -> Path:
    path = Path(tempfile.mkdtemp(prefix="e2e-server-"))
    yield path
    if request.session.testsfailed:
        print(f"FAILED_E2E_SERVER_TEMP_DIR={path}")
        return
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_e2e_database(request: pytest.FixtureRequest) -> None:
    """Reset canonical tables per journey while application processes are reused."""
    request.getfixturevalue("clean_postgres_business_tables")


def pytest_addoption(parser) -> None:
    group = parser.getgroup("architecture-e2e")
    group.addoption(
        "--e2e-scope",
        choices=("all", "release", "diagnostic"),
        default="all",
        help="select release-eligible or in-process diagnostic architecture evidence",
    )
    group.addoption(
        "--e2e-layer",
        action="append",
        choices=(
            "understanding",
            "planning_control",
            "authority_gateway",
            "journal_recovery",
            "verification_completion",
        ),
        help="select one or more architecture evidence layers",
    )
    group.addoption(
        "--e2e-require-complete-matrix",
        action="store_true",
        help=(
            "fail collection unless every required product capability claim "
            "has release evidence"
        ),
    )


def pytest_collection_modifyitems(config, items) -> None:
    """Classify every architecture E2E from the single canonical catalog."""
    selected_scope = config.getoption("--e2e-scope")
    selected_layers = set(config.getoption("--e2e-layer") or ())
    deselected = []
    collected_node_keys = {
        (Path(str(item.path)).name, item.name.split("[")[0])
        for item in items
        if Path(str(item.path)).parent.name == "e2e_quality"
        and Path(str(item.path)).name.startswith("test_")
    }
    if config.getoption("--e2e-require-complete-matrix"):
        if selected_scope != "release":
            raise pytest.UsageError(
                "--e2e-require-complete-matrix requires --e2e-scope=release"
            )
        release_case_ids = {
            case.case_id for case in EVIDENCE_BY_NODE.values()
            if (
                case.release_eligible
                and case.claim_kind is EvidenceClaimKind.PRODUCT_CAPABILITY
            )
        }
        missing_release = set(REQUIRED_NATIVE_EVIDENCE_IDS) - release_case_ids
        if missing_release:
            raise pytest.UsageError(
                "release E2E matrix is incomplete; missing: "
                + ", ".join(sorted(missing_release))
            )
        loop_case_ids = {
            case.case_id for case in EVIDENCE_BY_NODE.values()
            if case.release_eligible and case.claim_kind is EvidenceClaimKind.COMPLEX_LOOP
        }
        missing_loop = set(REQUIRED_LOOP_EVIDENCE_IDS) - loop_case_ids
        if missing_loop:
            raise pytest.UsageError(
                "complex-loop release E2E matrix is incomplete; missing: "
                + ", ".join(sorted(missing_loop))
            )
        required_catalog_nodes = {
            case.node_key
            for case in EVIDENCE_BY_NODE.values()
            if case.claim_kind in {
                EvidenceClaimKind.PRODUCT_CAPABILITY,
                EvidenceClaimKind.COMPLEX_LOOP,
            }
        }
        missing_nodes = required_catalog_nodes - collected_node_keys
        if missing_nodes:
            raise pytest.UsageError(
                "release catalog references tests that were not collected: "
                + ", ".join(f"{module}::{name}" for module, name in sorted(missing_nodes))
            )
    for item in items:
        path = Path(str(item.path))
        if path.parent.name != "e2e_quality" or not path.name.startswith("test_"):
            continue
        key = (path.name, item.name.split("[")[0])
        case = EVIDENCE_BY_NODE.get(key)
        if case is None:
            raise pytest.UsageError(
                f"unclassified architecture E2E test: {path.name}::{item.name}"
            )
        item.add_marker(pytest.mark.architecture_e2e)
        item.add_marker(
            pytest.mark.release_e2e if case.release_eligible
            else pytest.mark.diagnostic_e2e
        )
        for layer in sorted(case.layers, key=lambda value: value.value):
            item.add_marker(pytest.mark.e2e_layer(layer.value))
        item.user_properties.extend((
            ("evidence_id", case.evidence_id),
            ("case_id", case.case_id),
            ("claim_kind", case.claim_kind.value),
            ("capability_profile", case.capability_profile.value),
            ("release_eligible", case.release_eligible),
        ))
        scope_matches = (
            selected_scope == "all"
            or (selected_scope == "release" and case.release_eligible)
            or (selected_scope == "diagnostic" and not case.release_eligible)
        )
        layer_matches = not selected_layers or bool(
            selected_layers & {layer.value for layer in case.layers}
        )
        if not scope_matches or not layer_matches:
            deselected.append(item)

    if deselected:
        items[:] = [item for item in items if item not in deselected]
        config.hook.pytest_deselected(items=deselected)


@pytest.fixture(scope="session")
def trace_archive() -> TraceArchive:
    global _ARCHIVE
    output_root = Path(
        os.getenv("PERSONAL_AGENT_E2E_TRACE_DIR", "data/e2e_traces")
    ).resolve()
    settings = Settings.from_env()
    provider = (
        urlparse(settings.structured.base_url).hostname
        if settings.structured.base_url
        else "openai"
    )
    catalog_path = Path(__file__).with_name("evidence_catalog.py")
    fixtures_dir = Path(__file__).with_name("fixtures")
    fixture_bytes = b"".join(
        path.read_bytes()
        for path in sorted(fixtures_dir.rglob("*"))
        if path.is_file()
    )
    budget = settings.interaction_loop
    measurement_profile = MeasurementProfile(
        profile_id=os.getenv(
            "PERSONAL_AGENT_E2E_MEASUREMENT_PROFILE",
            "current-runtime",
        ),
        runtime_implementation="personal-agent-conversation-loop",
        structured_provider=provider or "openai-compatible",
        structured_model=settings.structured.model,
        prompt_revision=budget.policy_revision,
        capability_catalog_revision=sha256(catalog_path.read_bytes()).hexdigest()[:16],
        budget=BudgetProfile(
            max_model_turns=budget.max_model_turns,
            max_tool_calls=budget.max_tool_calls,
            max_agent_calls=budget.max_agent_calls,
            max_total_tokens=budget.max_total_tokens,
            max_concurrency=budget.max_concurrency,
        ),
        fixture_revision=sha256(fixture_bytes).hexdigest()[:16],
        repetition=int(os.getenv("PERSONAL_AGENT_E2E_REPETITION", "1")),
    )
    archive = TraceArchive(output_root, measurement_profile=measurement_profile)
    _ARCHIVE = archive
    yield archive


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    archive = item.funcargs.get("trace_archive") or _ARCHIVE
    if archive is None:
        return
    detail = str(report.longrepr) if report.failed else None
    archive.record_test_result(
        nodeid=item.nodeid,
        phase=report.when,
        outcome=report.outcome,
        duration_seconds=report.duration,
        detail=detail,
    )


def pytest_sessionfinish(session, exitstatus: int) -> None:
    global _ARCHIVE
    if _ARCHIVE is not None:
        _ARCHIVE.finalize(exit_status=exitstatus)
        print(f"LIVE_E2E_TRACE_DIR={_ARCHIVE.run_dir}")
        _ARCHIVE = None
