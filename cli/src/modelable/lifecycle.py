"""External, deterministic lifecycle metadata for immutable declarations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from modelable.identity import parse_declaration_id

LIFECYCLE_SCHEMA = "modelable.lifecycle/v1"


class LifecycleError(ValueError):
    """Raised when lifecycle metadata or a state transition is invalid."""


class LifecycleState(StrEnum):
    candidate = "candidate"
    published = "published"
    deprecated = "deprecated"
    retired = "retired"


_TRANSITIONS: dict[LifecycleState, LifecycleState | None] = {
    LifecycleState.candidate: LifecycleState.published,
    LifecycleState.published: LifecycleState.deprecated,
    LifecycleState.deprecated: LifecycleState.retired,
    LifecycleState.retired: None,
}


def parse_lifecycle_document(document: object) -> dict[str, Any]:
    """Validate and canonically sort one ``modelable.lifecycle/v1`` document."""
    if not isinstance(document, dict):
        raise LifecycleError("lifecycle document must be an object")
    if set(document) != {"$schema", "entries"}:
        raise LifecycleError("lifecycle document must contain only '$schema' and 'entries'")
    if document["$schema"] != LIFECYCLE_SCHEMA:
        raise LifecycleError(f"lifecycle document schema must be {LIFECYCLE_SCHEMA!r}")
    entries = document["entries"]
    if not isinstance(entries, list):
        raise LifecycleError("lifecycle entries must be an array")

    canonical: list[dict[str, str]] = []
    identities: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise LifecycleError("lifecycle entry must be an object")
        if set(entry) - {"identity", "state", "replacement"} or {"identity", "state"} - set(entry):
            raise LifecycleError("lifecycle entry has invalid fields")
        identity = entry["identity"]
        if not isinstance(identity, str):
            raise LifecycleError("lifecycle identity must be a string")
        _validate_identity(identity, "lifecycle identity")
        if identity in identities:
            raise LifecycleError(f"duplicate lifecycle identity {identity!r}")
        identities.add(identity)
        state_value = entry["state"]
        try:
            state = LifecycleState(state_value)
        except ValueError as error:
            raise LifecycleError(f"unsupported lifecycle state {state_value!r}") from error
        normalized: dict[str, str] = {"identity": identity, "state": state.value}
        if "replacement" in entry:
            replacement = entry["replacement"]
            if not isinstance(replacement, str):
                raise LifecycleError("lifecycle replacement must be a string")
            _validate_identity(replacement, "lifecycle replacement")
            if replacement == identity:
                raise LifecycleError("lifecycle replacement must differ from identity")
            normalized["replacement"] = replacement
        canonical.append(normalized)

    canonical.sort(key=lambda item: item["identity"])
    return {"$schema": LIFECYCLE_SCHEMA, "entries": canonical}


def load_lifecycle(path: str | Path) -> dict[str, Any]:
    """Load and validate external lifecycle metadata from JSON."""
    lifecycle_path = Path(path)
    try:
        document = json.loads(
            lifecycle_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, LifecycleError) as error:
        raise LifecycleError(f"cannot read lifecycle metadata {lifecycle_path}: {error}") from error
    return parse_lifecycle_document(document)


def serialize_lifecycle(document: object) -> str:
    """Serialize validated lifecycle metadata deterministically."""
    return json.dumps(parse_lifecycle_document(document), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def validate_lifecycle_transition(previous: LifecycleState | str, current: LifecycleState | str) -> None:
    """Require a lifecycle state to stay put or advance exactly one step."""
    try:
        previous_state = LifecycleState(previous)
        current_state = LifecycleState(current)
    except ValueError as error:
        raise LifecycleError("unknown lifecycle state in transition") from error
    if previous_state == current_state:
        return
    if _TRANSITIONS[previous_state] != current_state:
        raise LifecycleError(f"cannot transition lifecycle from {previous_state.value!r} to {current_state.value!r}")


def find_lifecycle_reference_findings(
    objects: Sequence[Mapping[str, Any]], lifecycle: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Return deterministic findings for dependencies targeting non-live declarations."""
    document = parse_lifecycle_document(lifecycle)
    states = {
        entry["identity"]: entry["state"]
        for entry in document["entries"]
        if entry["state"] in {LifecycleState.deprecated.value, LifecycleState.retired.value}
    }
    findings: list[dict[str, str]] = []
    for obj in objects:
        source = obj.get("identity")
        dependencies = obj.get("dependencies")
        if not isinstance(source, str) or not isinstance(dependencies, list):
            continue
        for target in dependencies:
            if isinstance(target, str) and target in states:
                findings.append({"source": source, "target": target, "state": states[target]})
    return sorted(findings, key=lambda item: (item["source"], item["target"], item["state"]))


def _validate_identity(value: str, label: str) -> None:
    try:
        parse_declaration_id(value)
    except ValueError as error:
        raise LifecycleError(f"{label} must be a canonical declaration identity") from error


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise LifecycleError(f"non-finite JSON number {value!r} is not allowed")
