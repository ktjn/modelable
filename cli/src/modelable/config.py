from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from modelable.parser.ir import AutoProjectionDecl, AutoProjectionTarget, DomainDef, MdlFile

BUILTIN_DEFAULTS: dict[str, Any] = {
    "auto_projections": [],
    "generate_conversions": True,
}

REGISTRY_POLICY_ACTIONS = frozenset(
    {
        "breaking",
        "consumer_update",
        "data_backfill",
        "event_replay",
        "governance_review",
        "no_action",
        "projection_rebuild",
        "recompile",
        "regenerate",
        "storage_migration",
    }
)


@dataclass(frozen=True)
class ConfigValue:
    value: Any
    provenance: str

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "provenance": self.provenance}


@dataclass(frozen=True)
class ModelableConfig:
    path: Path | None
    values: dict[str, ConfigValue]

    def overlay_for_target(self, target: str) -> Path | None:
        """Return the workspace-relative overlay selected for a target."""
        configured = self.values.get(f"targets.{target}.overlay")
        if configured is None:
            return None
        if not isinstance(configured.value, str) or not configured.value:
            raise ValueError(f"[targets.{target}].overlay must be a non-empty workspace-relative path")
        path = Path(configured.value)
        if path.is_absolute():
            raise ValueError(f"[targets.{target}].overlay must be workspace-relative")
        return path

    def blocked_registry_actions(self) -> tuple[str, ...]:
        configured = self.values.get("registry.blocked_actions")
        if configured is None:
            return ()
        return tuple(configured.value)

    def explain(self, target: str | None = None) -> dict[str, Any]:
        result = {name: value.as_dict() for name, value in sorted(self.values.items())}
        if target is not None:
            result["target"] = {"value": target, "provenance": "cli"}
        return result


def load_config(path: str | Path) -> ModelableConfig:
    config_path = _find_config_path(Path(path))
    values = {name: ConfigValue(value=value, provenance="built-in default") for name, value in BUILTIN_DEFAULTS.items()}
    values["registry.blocked_actions"] = ConfigValue([], "built-in default")
    if config_path is None:
        return ModelableConfig(None, values)

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read {config_path}: {exc}") from exc

    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("[defaults] in modelable.toml must be a table")
    for name in BUILTIN_DEFAULTS:
        if name in defaults:
            values[name] = ConfigValue(defaults[name], f"{config_path} [defaults]")

    targets = data.get("targets", {})
    if isinstance(targets, dict):
        for target_name, target_values in targets.items():
            if isinstance(target_values, dict):
                for name, value in target_values.items():
                    values[f"targets.{target_name}.{name}"] = ConfigValue(
                        value, f"{config_path} [targets.{target_name}]"
                    )
    registry = data.get("registry", {})
    if not isinstance(registry, dict):
        raise ValueError("[registry] in modelable.toml must be a table")
    blocked_actions = registry.get("blocked_actions", [])
    if not isinstance(blocked_actions, list) or not all(isinstance(item, str) for item in blocked_actions):
        raise ValueError("[registry].blocked_actions must be an array of action names")
    unknown_actions = sorted(set(blocked_actions) - REGISTRY_POLICY_ACTIONS)
    if unknown_actions:
        raise ValueError(f"unsupported registry blocked action(s): {', '.join(unknown_actions)}")
    if len(set(blocked_actions)) != len(blocked_actions):
        raise ValueError("[registry].blocked_actions contains duplicate actions")
    values["registry.blocked_actions"] = ConfigValue(sorted(blocked_actions), f"{config_path} [registry]")
    target_entries = data.get("target", [])
    if not isinstance(target_entries, list):
        raise ValueError("[[target]] entries in modelable.toml must be tables")
    seen_targets: set[str] = set()
    for index, target_values in enumerate(target_entries, start=1):
        if not isinstance(target_values, dict):
            raise ValueError(f"[[target]] entry {index} in modelable.toml must be a table")
        target_name = target_values.get("name")
        if not isinstance(target_name, str) or not target_name:
            raise ValueError(f"[[target]] entry {index} requires a non-empty string 'name'")
        if target_name in seen_targets:
            raise ValueError(f"duplicate [[target]] entry for {target_name!r}")
        seen_targets.add(target_name)
        if "overlay" in target_values:
            values[f"targets.{target_name}.overlay"] = ConfigValue(
                target_values["overlay"], f"{config_path} [[target]] ({target_name})"
            )
    return ModelableConfig(config_path, values)


def apply_config_defaults(mdl: MdlFile, config: ModelableConfig) -> None:
    """Lower configured auto-projection defaults into ordinary planner input."""
    configured_targets = config.values["auto_projections"].value
    if not configured_targets:
        return
    if not isinstance(configured_targets, list) or not all(isinstance(item, str) for item in configured_targets):
        raise ValueError("defaults.auto_projections must be an array of db, request, reply, or event")
    allowed = {"db", "request", "reply", "event"}
    unknown = sorted(set(configured_targets) - allowed)
    if unknown:
        raise ValueError(f"defaults.auto_projections contains unsupported target(s): {', '.join(unknown)}")

    for domain in mdl.domains:
        _apply_domain_defaults(domain, configured_targets)


def _apply_domain_defaults(domain: DomainDef, configured_targets: list[str]) -> None:
    declared = {(decl.model, decl.version) for decl in domain.auto_projections}
    for model_name, versions in domain.models.items():
        for version in versions:
            if (model_name, version.version) in declared:
                continue
            domain.auto_projections.append(
                AutoProjectionDecl(
                    model=model_name,
                    version=version.version,
                    targets=[
                        AutoProjectionTarget(kind=cast(Literal["db", "request", "reply", "event"], target))
                        for target in configured_targets
                    ],
                )
            )


def _find_config_path(path: Path) -> Path | None:
    root = path if path.is_dir() else path.parent
    candidate = root / "modelable.toml"
    return candidate if candidate.exists() else None
