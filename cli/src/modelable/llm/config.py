from __future__ import annotations

from dataclasses import dataclass
from os import environ

from modelable.parser.ir import WorkspaceDef


@dataclass(frozen=True)
class LlmConfig:
    provider: str | None
    model: str | None
    base_url: str | None
    repair_attempts: int
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

    repair_attempts = _resolve_repair_attempts(
        flag_repair_attempts=None,
        env_repair_attempts=values.get("MODELABLE_LLM_REPAIR_ATTEMPTS"),
        workspace_repair_attempts=workspace.ai.repair_attempts if workspace and workspace.ai else None,
    )

    source = "default"
    if flag_provider or flag_model or flag_base_url:
        source = "flag"
    elif (
        values.get("MODELABLE_LLM_PROVIDER")
        or values.get("MODELABLE_LLM_MODEL")
        or values.get("MODELABLE_LLM_BASE_URL")
        or values.get("MODELABLE_LLM_REPAIR_ATTEMPTS")
    ):
        source = "environment"
    elif workspace and workspace.ai:
        source = "workspace"

    if provider is None and model is None:
        model = default_model

    return LlmConfig(provider=provider, model=model, base_url=base_url, repair_attempts=repair_attempts, source=source)


def _resolve_repair_attempts(
    *,
    flag_repair_attempts: int | None,
    env_repair_attempts: str | None,
    workspace_repair_attempts: int | None,
) -> int:
    if flag_repair_attempts is not None:
        if flag_repair_attempts < 0:
            raise ValueError("MODELABLE_LLM_REPAIR_ATTEMPTS must be >= 0")
        return flag_repair_attempts
    if env_repair_attempts is not None:
        value = int(env_repair_attempts)
        if value < 0:
            raise ValueError("MODELABLE_LLM_REPAIR_ATTEMPTS must be >= 0")
        return value
    if workspace_repair_attempts is not None:
        if workspace_repair_attempts < 0:
            raise ValueError("workspace ai.repair_attempts must be >= 0")
        return workspace_repair_attempts
    return 1
