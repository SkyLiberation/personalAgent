from __future__ import annotations

from collections.abc import Iterable

from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig


class DashScopeCompatibleEmbedder(OpenAIEmbedder):
    def __init__(
        self,
        config: OpenAIEmbedderConfig | None = None,
        batch_limit: int = 10,
    ) -> None:
        super().__init__(config=config)
        self.batch_limit = batch_limit

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        return await super().create(input_data)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        if len(input_data_list) <= self.batch_limit:
            return await super().create_batch(input_data_list)

        results: list[list[float]] = []
        for index in range(0, len(input_data_list), self.batch_limit):
            chunk = input_data_list[index : index + self.batch_limit]
            chunk_result = await super().create_batch(chunk)
            results.extend(chunk_result)
        return results
