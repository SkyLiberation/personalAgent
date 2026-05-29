from types import SimpleNamespace

import pytest
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

from personal_agent.core.config import GraphitiConfig, OpenAIConfig, Settings
from personal_agent.graphiti.llm_strategies import (
    GraphitiOpenAIClient,
    build_graphiti_llm_client,
)


class StructuredResponse(BaseModel):
    value: str


class FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"value": "ok"}'))
            ]
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions())


@pytest.mark.asyncio
async def test_graphiti_client_uses_json_schema_and_disables_thinking(monkeypatch):
    api_client = FakeOpenAIClient()
    llm_client = GraphitiOpenAIClient(
        config=LLMConfig(model="kimi-k2.5"),
        client=api_client,
    )

    async def no_wait() -> None:
        return None

    monkeypatch.setattr(llm_client, "_respect_min_interval", no_wait)

    result = await llm_client._generate_response(
        [Message(role="user", content="Return JSON.")],
        response_model=StructuredResponse,
    )

    request = api_client.chat.completions.kwargs
    assert result == {"value": "ok"}
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "StructuredResponse",
            "schema": StructuredResponse.model_json_schema(),
        },
    }
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_graphiti_client_prefers_llm_override_settings():
    settings = Settings(
        openai=OpenAIConfig(
            api_key="general-key",
            base_url="https://general.example/v1",
            model="general-model",
            small_model="general-small-model",
        ),
        graphiti=GraphitiConfig(
            llm_api_key="graph-key",
            llm_base_url="https://api.moonshot.cn/v1",
            llm_model="kimi-k2.5",
            llm_small_model="kimi-k2.5",
        ),
    )

    llm_client = build_graphiti_llm_client(settings)

    assert llm_client.model == "kimi-k2.5"
    assert str(llm_client.client.base_url) == "https://api.moonshot.cn/v1/"
