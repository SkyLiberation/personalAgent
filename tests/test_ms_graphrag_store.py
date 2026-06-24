from __future__ import annotations

import subprocess
import shutil
from uuid import uuid4
from pathlib import Path

from personal_agent.kernel.config import MicrosoftGraphRagConfig, Settings
from personal_agent.ms_graphrag import MicrosoftGraphRagStore


def _workspace_tmp() -> Path:
    path = Path("tests") / ".tmp_ms_graphrag" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_ms_graphrag_store_disabled_without_cli():
    tmp_path = _workspace_tmp()
    settings = Settings(
        ms_graphrag=MicrosoftGraphRagConfig(
            enabled=True,
            root=tmp_path,
            executable="definitely-missing-graphrag",
        )
    )

    store = MicrosoftGraphRagStore(settings)

    assert store.configured() is False
    assert store.ask("q", "u").enabled is False
    shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_ms_graphrag_query_output_becomes_graph_result(monkeypatch):
    tmp_path = _workspace_tmp()
    executable = tmp_path / "graphrag.exe"
    executable.write_text("", encoding="utf-8")
    settings = Settings(
        ms_graphrag=MicrosoftGraphRagConfig(
            enabled=True,
            root=tmp_path / "project",
            executable=str(executable),
        )
    )
    store = MicrosoftGraphRagStore(settings)

    def fake_run(*args, **kwargs):  # noqa: ARG001
        return subprocess.CompletedProcess(
            args=["graphrag"],
            returncode=0,
            stdout="SUCCESS: query complete\nThe answer is grounded.\nSecond fact.",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = store.ask("question", "user")

    assert result.enabled is True
    assert "grounded" in (result.answer or "")
    assert result.relation_facts[:2] == ["The answer is grounded.", "Second fact."]
    shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_ms_graphrag_executable_can_be_command_prefix(monkeypatch):
    tmp_path = _workspace_tmp()
    settings = Settings(
        ms_graphrag=MicrosoftGraphRagConfig(
            enabled=True,
            root=tmp_path / "project",
            executable="uvx --from graphrag graphrag",
        )
    )
    store = MicrosoftGraphRagStore(settings)
    monkeypatch.setattr("shutil.which", lambda name: "uvx.exe" if name == "uvx" else None)
    captured: dict[str, list[str]] = {}

    def fake_run(command, **kwargs):  # noqa: ARG001
        captured["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="Answer", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert store.configured() is True
    assert store.ask("question", "user").enabled is True
    assert captured["command"][:4] == ["uvx", "--from", "graphrag", "graphrag"]
    shutil.rmtree(tmp_path.parent, ignore_errors=True)
