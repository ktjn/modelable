from __future__ import annotations

from dataclasses import dataclass
from os import environ

from modelable.parser.ir import WorkspaceDef


@dataclass(frozen=True)
class LlmConfig:
    provider: str | None
    model: str
    source: str


def resolve_llm_config(
    *,
    flag_model: str | None = None,
    workspace: WorkspaceDef | None = None,
    env: dict[str, str] | None = None,
    default_model: str = "modelable-local",
) -> LlmConfig:
    values = env or environ
    if flag_model:
        return LlmConfig(provider=_provider_from_model(flag_model), model=flag_model, source="flag")

    env_model = values.get("MODELABLE_LLM_MODEL")
    if env_model:
        return LlmConfig(
            provider=_provider_from_model(env_model),
            model=env_model,
            source="environment",
        )

    workspace_model = workspace.ai.model if workspace and workspace.ai and workspace.ai.model else None
    if workspace_model:
        return LlmConfig(
            provider=workspace.ai.provider if workspace and workspace.ai else None,
            model=workspace_model,
            source="workspace",
        )

    return LlmConfig(provider=None, model=default_model, source="default")


def _provider_from_model(model: str) -> str | None:
    if "/" in model or model.startswith("local:"):
        return "local"
    return None

