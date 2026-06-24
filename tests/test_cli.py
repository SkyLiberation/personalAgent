from __future__ import annotations

import json

import pytest
from pathlib import Path
from typer.testing import CliRunner

from personal_agent.planning.router import DefaultIntentRouter
from personal_agent.cli.main import app
from tests.conftest import POSTGRES_URL, stub_router_decision

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


@pytest.fixture
def cli_runner(temp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("PERSONAL_AGENT_DATA_DIR", str(temp_dir))
    # Ensure no real LLM/Graphiti calls happen
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("PERSONAL_AGENT_POSTGRES_URL", POSTGRES_URL)
    monkeypatch.setenv("PERSONAL_AGENT_GRAPHITI_URI", "")
    monkeypatch.setenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")
    from personal_agent.kernel import config_env as config_env_module

    monkeypatch.setattr(config_env_module, "load_dotenv", lambda override=True: False)
    monkeypatch.setattr(
        DefaultIntentRouter,
        "_classify_with_llm",
        lambda _self, text, messages=None: stub_router_decision(text, messages),
    )
    return CliRunner()


class TestCLIEntry:
    def test_capture_instruction_flows_through_entry(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["entry", "记一下：测试采集JSON输出"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["intents"] == ["capture_text"]
        assert data["reply"]
        assert data["run_id"]

    def test_question_flows_through_entry(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["entry", "什么是测试？", "--session-id", "cli-question"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["intents"] == ["ask"]
        assert data["reply"]
        assert data["run_id"]

    def test_removed_specialized_commands_are_not_registered(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "entry" in result.stdout
        # The legacy standalone capture/ask commands were folded into `entry`.
        # (`digest` remains a valid command — review digest delivery job.)
        assert " capture " not in result.stdout
        assert " ask " not in result.stdout
