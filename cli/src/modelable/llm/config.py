from __future__ import annotations

from dataclasses import dataclass
from os import environ

from modelable.parser.ir import WorkspaceDef


@dataclass(frozen=True)
class LlmConfig:
    provider: str | None
    model: str | None
    base_url: str | None
    source: str


def resolve_llm_config(
    *,
    flag_provider: str | None = None,
    flag_model: str | None = None,
    flag_base_url: str | None = None,
    workspace: WorkspaceDef | None = None,
    env: dict[str, str] | None = None,
    default_model: str = "modelable-local",
) -> LlmConfig:
    values = env or environ

    provider = (
        flag_provider
        or values.get("MODELABLE_LLM_PROVIDER")
        or (workspace.ai.provider if workspace and workspace.ai and workspace.ai.provider else None)
    )

    model = (
        flag_model
        or values.get("MODELABLE_LLM_MODEL")
        or (workspace.ai.model if workspace and workspace.ai and workspace.ai.model else None)
    )

    base_url = (
        flag_base_url
        or values.get("MODELABLE_LLM_BASE_URL")
        or values.get("OLLAMA_HOST")
    )

    source = "default"
    if flag_provider or flag_model or flag_base_url:
        source = "flag"
    elif values.get("MODELABLE_LLM_PROVIDER") or values.get("MODELABLE_LLM_MODEL") or values.get("MODELABLE_LLM_BASE_URL"):
        source = "environment"
    elif workspace and workspace.ai:
        source = "workspace"

    if provider is None and model is None:
        model = default_model

    return LlmConfig(provider=provider, model=model, base_url=base_url, source=source)
