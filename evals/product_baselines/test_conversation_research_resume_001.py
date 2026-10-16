"""从真实正式运行的完整文件快照，经公开 HTTP 恢复同一研究任务。"""

from dataclasses import replace
from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Iterator

import pytest

from evals.e2e_quality.test_product_capability_outcomes import _web_search_child_overrides
from evals.e2e_quality.test_release_user_outcomes import (
    LiveWebProcess,
    _new_live_web_process,
    _require_live_dependencies,
    _yield_started_server,
)
from evals.product_baselines.evidence import ProductEvidenceRecorder
from evals.product_baselines.test_conversation_research_delivery_001 import run_research_scenario
from evals.product_baselines.test_conversation_research_review_001 import REVIEW_SCENARIO


pytestmark = [pytest.mark.integration, pytest.mark.product_e2e]
pytest_plugins = ("evals.e2e_quality.test_release_user_outcomes",)

RESUME_SCENARIO = replace(
    REVIEW_SCENARIO,
    scenario_id="tool-protocol-explicit-review-resume",
    dataset_revision="conversation-research-mcp-cooperation-review-zh-v3-resume",
)


@pytest.fixture(scope="module")
def restored_research_process(server_temp_dir: Path) -> Iterator[tuple[LiveWebProcess, str]]:
    checkpoint = os.getenv("PERSONAL_AGENT_E2E_RESEARCH_CHECKPOINT_DIR")
    if not checkpoint:
        pytest.skip("恢复样本需要真实正式运行的封存 checkpoint")
    source = Path(checkpoint)
    assert source.is_dir()
    before = {
        path.relative_to(source): sha256(path.read_bytes()).hexdigest()
        for path in source.rglob("*") if path.is_file()
    }
    assert before
    target = server_temp_dir / "server-data"
    assert not target.exists()
    shutil.copytree(source, target)
    assert before == {
        path.relative_to(target): sha256(path.read_bytes()).hexdigest()
        for path in target.rglob("*") if path.is_file()
    }, "真实状态必须完整保真恢复"
    runs = [path.name for path in (target / "interaction_runs").glob("irun_*") if path.is_dir()]
    assert len(runs) == 1
    settings = _require_live_dependencies()
    assert settings.web_search_available
    server = _new_live_web_process(
        server_temp_dir, settings, child_env_overrides=_web_search_child_overrides(settings),
    )
    for active_server in _yield_started_server(server):
        yield active_server, runs[0]


def test_conversation_research_resume_001(
    request: pytest.FixtureRequest,
    restored_research_process: tuple[LiveWebProcess, str],
    product_evidence_recorder: ProductEvidenceRecorder,
) -> None:
    server, run_ref = restored_research_process
    run_research_scenario(
        request, server, product_evidence_recorder, RESUME_SCENARIO, 1,
        resume_run_ref=run_ref,
    )
