from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib import error, request


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
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError


@dataclass(frozen=True)
class OllamaProvider:
    base_url: str
    model: str
    timeout: float = 120.0

    def complete(self, prompt: LLMRequest) -> LLMResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "stream": False,
            "options": {"temperature": prompt.temperature},
        }
        if prompt.response_format == "json" or prompt.schema is not None:
            payload["format"] = "json"

        response = self._post_json("/api/chat", payload)
        message = response.get("message") or {}
        content = str(message.get("content") or "")
        return LLMResponse(
            content=content,
            provider="ollama",
            model=self.model,
            prompt_tokens=_int_or_none(response.get("prompt_eval_count")),
            completion_tokens=_int_or_none(response.get("eval_count")),
        )

    def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.base_url.rstrip("/") + path,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except error.HTTPError as exc:  # pragma: no cover - thin transport wrapper
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed: {exc.code} {detail}") from exc
        except error.URLError as exc:  # pragma: no cover - thin transport wrapper
            raise RuntimeError(f"Ollama request failed: {exc.reason}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc


def build_provider(provider: str | None, *, model: str | None, base_url: str | None) -> LLMProvider | None:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    if normalized in {"local", "heuristic", "none"}:
        return None
    if normalized == "ollama":
        if not model:
            raise ValueError("ollama provider requires a model")
        return OllamaProvider(base_url=base_url or "http://localhost:11434", model=model)
    raise ValueError(f"Unsupported LLM provider: {provider}")


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
