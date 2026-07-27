from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    temperature: float = 0.2
    response_format: str = "text"
    schema: dict[str, object] | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...
