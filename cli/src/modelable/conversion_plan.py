"""Parser-free conversion classification for ``modelable.plan/v1`` documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from modelable.planner.protocol import PlanDocument, validate_plan

CONVERSION_TOTAL_REVERSIBLE = "total_reversible"
CONVERSION_TOTAL_IRREVERSIBLE = "total_irreversible"
CONVERSION_PARTIAL_FALLIBLE = "partial_fallible"
CONVERSION_REQUIRES_HOOK = "requires_hook"
CONVERSION_IMPOSSIBLE = "impossible"


@dataclass(frozen=True)
class ConversionPlan:
    source: str
    target: str
    classification: str
    fields: tuple[str, ...]
    hook_required: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "classification": self.classification,
            "fields": list(self.fields),
            "hook_required": self.hook_required,
            "reason": self.reason,
        }


def build_conversion_plan(plan: PlanDocument) -> ConversionPlan:
    """Classify one projection conversion from validated plan facts."""
    document = validate_plan(plan)
    source = _mapping(document.get("source"))
    resolved = _mapping(source.get("resolved"))
    if not resolved:
        raise LookupError(f"source model {source.get('model', '')!r} could not be resolved")
    source_ref = f"{_string(resolved, 'domain')}.{_string(resolved, 'name')}@{_integer(resolved, 'version')}"
    target_ref = f"{_string(document, 'domain')}.{_string(document, 'projection')}@{_integer(document, 'version')}"
    fields = _mappings(document.get("fields"))
    field_names = tuple(_string(field, "name") for field in fields)
    if not fields:
        return ConversionPlan(source_ref, target_ref, CONVERSION_IMPOSSIBLE, (), True, "projection has no fields")

    source_names = {_string(field, "name") for field in _mappings(resolved.get("fields"))}
    mapped_source_names: set[str] = set()
    for field in fields:
        if _string(field, "kind") != "direct":
            return ConversionPlan(
                source_ref,
                target_ref,
                CONVERSION_PARTIAL_FALLIBLE,
                field_names,
                True,
                "computed mappings require validation or a user hook",
            )
        mapped_source_names.add(_string(field, "source_field"))
    if not mapped_source_names <= source_names:
        return ConversionPlan(
            source_ref, target_ref, CONVERSION_IMPOSSIBLE, field_names, True, "mapping references unknown fields"
        )
    target_names = set(field_names)
    if mapped_source_names == source_names and target_names == source_names:
        return ConversionPlan(
            source_ref,
            target_ref,
            CONVERSION_TOTAL_REVERSIBLE,
            field_names,
            False,
            "one-to-one direct mapping preserves every source field",
        )
    return ConversionPlan(
        source_ref,
        target_ref,
        CONVERSION_TOTAL_IRREVERSIBLE,
        field_names,
        False,
        "direct mapping drops or renames source information",
    )


def _mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _mappings(value: object) -> list[dict[str, object]]:
    return (
        [cast(dict[str, object], item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )


def _string(mapping: dict[str, object], key: str) -> str:
    return str(mapping.get(key, ""))


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"plan {key} must be an integer")
    return value
