from __future__ import annotations

import json

import pytest
from pathlib import Path
from typer.testing import CliRunner

from personal_agent.cli.main import app


@pytest.fixture
def cli_runner(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    # Ensure no real LLM/Graphiti calls happen
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_URI", "")
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_AGENT_LANGGRAPH_CHECKPOINT_BACKEND", "memory")
    from personal_agent.core import config as config_module

    monkeypatch.setattr(config_module, "load_dotenv", lambda override=True: False)
    return CliRunner()


class TestCLIEntry:
    def test_capture_instruction_flows_through_entry(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["entry", "记一下：测试采集JSON输出"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["intent"] == "capture_text"
        assert data["reply"]
        assert data["run_id"]

    def test_question_flows_through_entry(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["entry", "什么是测试？", "--session-id", "cli-question"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["intent"] == "ask"
        assert data["reply"]
        assert data["run_id"]

    def test_removed_specialized_commands_are_not_registered(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "entry" in result.stdout
        assert " capture " not in result.stdout
        assert " ask " not in result.stdout
        assert " digest " not in result.stdout

