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
    return CliRunner()


class TestCLICapture:
    def test_capture_text_exits_zero(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["capture", "测试采集内容"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"

    def test_capture_text_outputs_json(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["capture", "测试采集JSON输出"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "note_id" in data
        assert "summary" in data
        assert "tags" in data

    def test_capture_with_source_type(self, cli_runner: CliRunner):
        result = cli_runner.invoke(
            app, ["capture", "链接来源内容", "--source-type", "link"]
        )
        assert result.exit_code == 0, f"stderr: {result.stderr}"


class TestCLIAsk:
    def test_ask_exits_zero(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["ask", "什么是测试？"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"

    def test_ask_outputs_json(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["ask", "测试问题"])
        assert result.exit_code == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "answer" in data
        assert "session_id" in data
        assert "citations" in data


class TestCLIDigest:
    def test_digest_exits_zero(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["digest"])
        assert result.exit_code == 0

    def test_digest_produces_output(self, cli_runner: CliRunner):
        result = cli_runner.invoke(app, ["digest"])
        assert result.exit_code == 0
        assert len(result.stdout.strip()) > 0

