from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PromptSpec:
    name: str
    version: str
    template: str
    output_contract: str = "free_text"
    owner: str = "personal_agent"

    def render(self, **variables: Any) -> str:
        return self.template.format(**variables)
