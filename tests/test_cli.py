from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from personal_agent.adapters.cli import main as cli_module
from personal_agent.application.conversation import ConversationMessage, ConversationTurnView


@pytest.fixture
def cli_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    def converse(**kwargs) -> ConversationTurnView:
        message = kwargs["messages"][0]
        assert isinstance(message, ConversationMessage)
        return ConversationTurnView(
            interaction_run_ref="irun_cli",
            conversation_id=kwargs["conversation_id"],
            disposition="answer",
            message=ConversationMessage(role="assistant", content=f"收到：{message.content}"),
        )

    monkeypatch.setattr(
        cli_module,
        "_build_service",
        lambda: SimpleNamespace(converse=converse),
    )
    return CliRunner()


def test_entry_uses_canonical_conversation_contract(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(
        cli_module.app,
        ["entry", "什么是测试？", "--session-id", "cli-question"],
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["interaction_run_ref"] == "irun_cli"
    assert payload["conversation_id"] == "cli-question"
    assert payload["disposition"] == "answer"
    assert payload["message"]["content"] == "收到：什么是测试？"
    assert not any(key in payload for key in ("task", "goal_graph", "run_id"))


def test_removed_specialized_commands_are_not_registered(cli_runner: CliRunner) -> None:
    result = cli_runner.invoke(cli_module.app, ["--help"])

    assert result.exit_code == 0
    assert "entry" in result.stdout
    assert " capture " not in result.stdout
    assert " ask " not in result.stdout
