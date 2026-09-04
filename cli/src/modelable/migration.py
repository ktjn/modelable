from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from modelable.compat.checker import CompatibilityReport
from modelable.compiler.workspace import Workspace
from modelable.identity import DeclarationReference
from modelable.parser.ir import ModelVersion

MIGRATION_SCHEMA = "modelable.migration/v1"
MIGRATION_KINDS = frozenset({"rename", "move", "field_move", "split", "merge", "replacement"})


class MigrationError(ValueError):
    """Raised when external migration metadata is invalid."""


def parse_migration_document(value: object) -> dict[str, Any]:
    """Validate and normalize an explicit declaration/path migration document."""
    if not isinstance(value, dict):
        raise MigrationError("migration document must be an object")
    if set(value) != {"$schema", "mappings"} or value.get("$schema") != MIGRATION_SCHEMA:
        raise MigrationError(f"migration document must contain only $schema={MIGRATION_SCHEMA!r} and mappings")
    mappings = value.get("mappings")
    if not isinstance(mappings, list):
        raise MigrationError("migration mappings must be an array")
    normalized: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for index, raw in enumerate(mappings):
        if not isinstance(raw, dict) or set(raw) != {"kind", "sources", "targets"}:
            raise MigrationError(f"migration mapping {index} must contain kind, sources, and targets")
        kind = raw.get("kind")
        if not isinstance(kind, str) or kind not in MIGRATION_KINDS:
            raise MigrationError(f"migration mapping {index} has unsupported kind {kind!r}")
        sources = _canonical_references(raw.get("sources"), f"migration mapping {index} sources")
        targets = _canonical_references(raw.get("targets"), f"migration mapping {index} targets")
        _validate_cardinality(kind, sources, targets, index)
        if kind == "field_move":
            if any("#" not in reference for reference in (*sources, *targets)):
                raise MigrationError(f"migration mapping {index} field_move must use semantic paths")
        elif any("#" in reference for reference in (*sources, *targets)):
            raise MigrationError(f"migration mapping {index} {kind} must use declaration identities")
        duplicate_sources = seen_sources.intersection(sources)
        if duplicate_sources:
            raise MigrationError(f"migration mappings contain ambiguous source {sorted(duplicate_sources)[0]!r}")
        seen_sources.update(sources)
        normalized.append({"kind": kind, "sources": list(sources), "targets": list(targets)})
    _reject_cycles(normalized)
    normalized.sort(key=lambda item: (item["kind"], tuple(item["sources"]), tuple(item["targets"])))
    return {"$schema": MIGRATION_SCHEMA, "mappings": normalized}


def load_migration(path: Path) -> dict[str, Any]:
    """Load strict JSON migration metadata from PATH."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MigrationError(f"cannot read migration metadata {path}: {error}") from error
    return parse_migration_document(value)


def serialize_migration(document: object) -> str:
    """Serialize canonical migration metadata."""
    return json.dumps(parse_migration_document(document), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def migration_edges(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return deterministic direct and ultimate lineage edges."""
    normalized = parse_migration_document(document)
    direct: list[dict[str, Any]] = [
        {"kind": mapping["kind"], "source": source, "target": target}
        for mapping in normalized["mappings"]
        for source in mapping["sources"]
        for target in mapping["targets"]
    ]
    parents: dict[str, set[str]] = {}
    for edge in direct:
        parents.setdefault(edge["target"], set()).add(edge["source"])
    edges: list[dict[str, Any]] = []
    for edge in direct:
        ancestors = sorted(_ancestors(edge["source"], parents))
        edges.append(
            {
                **edge,
                "immediate": edge["source"],
                "ultimate": ancestors[0] if ancestors else edge["source"],
                "ultimate_sources": ancestors or [edge["source"]],
            }
        )
    return sorted(edges, key=lambda edge: (edge["source"], edge["target"], edge["kind"]))


def validate_migration_references(document: Mapping[str, Any], available: set[str]) -> None:
    """Reject mappings whose declaration roots are absent from a snapshot pair."""
    normalized = parse_migration_document(document)
    for mapping in normalized["mappings"]:
        for reference in [*mapping["sources"], *mapping["targets"]]:
            declaration = reference.split("#", 1)[0]
            if declaration not in available:
                raise MigrationError(f"dangling migration reference {reference!r}")


def _canonical_references(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise MigrationError(f"{label} must be a non-empty array of canonical identities")
    result = tuple(sorted(set(value)))
    if len(result) != len(value):
        raise MigrationError(f"{label} contains duplicate references")
    for reference in result:
        try:
            if DeclarationReference.parse(reference).render() != reference:
                raise ValueError(f"non-canonical reference: {reference!r}")
        except ValueError as error:
            raise MigrationError(f"{label} contains non-canonical reference {reference!r}") from error
    return result


def _validate_cardinality(kind: str, sources: Sequence[str], targets: Sequence[str], index: int) -> None:
    if kind in {"rename", "move", "field_move", "replacement"}:
        if len(sources) != 1:
            raise MigrationError(f"migration mapping {index} {kind} requires exactly one source")
        if len(targets) != 1:
            raise MigrationError(f"migration mapping {index} {kind} requires exactly one target")
    elif kind == "split" and len(sources) != 1:
        raise MigrationError(f"migration mapping {index} split requires exactly one source")
    elif kind == "split" and len(targets) < 2:
        raise MigrationError(f"migration mapping {index} split requires at least two targets")
    elif kind == "merge" and len(sources) < 2:
        raise MigrationError(f"migration mapping {index} merge requires at least two sources")
    elif kind == "merge" and len(targets) != 1:
        raise MigrationError(f"migration mapping {index} merge requires exactly one target")


def _reject_cycles(mappings: Sequence[Mapping[str, Any]]) -> None:
    graph: dict[str, set[str]] = {}
    for mapping in mappings:
        for source in mapping["sources"]:
            graph.setdefault(source, set()).update(mapping["targets"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise MigrationError(f"migration mappings contain a cycle at {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for target in sorted(graph.get(node, ())):
            visit(target)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)


def _ancestors(node: str, parents: Mapping[str, set[str]]) -> set[str]:
    result: set[str] = set()
    pending = list(parents.get(node, ()))
    while pending:
        parent = pending.pop()
        if parent in result:
            continue
        result.add(parent)
        pending.extend(parents.get(parent, ()))
    return result


@dataclass(frozen=True)
class MigrationFact:
    kind: str
    action: str
    subject: str
    deterministic: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "action": self.action,
            "subject": self.subject,
            "deterministic": self.deterministic,
            "reason": self.reason,
        }


def build_migration_facts(workspace: Workspace, report: CompatibilityReport) -> list[MigrationFact]:
    new = _find_model(workspace, report.domain_name, report.model_name, report.to_version)
    facts: list[MigrationFact] = []
    subject = f"{report.domain_name}.{report.model_name}"
    for change in report.changes:
        if change.kind == "removed_field":
            facts.append(
                MigrationFact(
                    "field_removal",
                    "manual_migration",
                    f"{subject}.{change.field_name}",
                    False,
                    "removed data requires an explicit policy",
                )
            )
        elif change.kind == "added_field" and change.to_optional is False:
            field = next((item for item in new.fields if item.name == change.field_name), None)
            deterministic = field is not None and field.default is not None
            facts.append(
                MigrationFact(
                    "required_field",
                    "data_backfill",
                    f"{subject}.{change.field_name}",
                    deterministic,
                    "field default is available" if deterministic else "no deterministic backfill source",
                )
            )
        elif change.kind in {"type_changed", "enum_changed", "identity_changed"}:
            facts.append(
                MigrationFact(
                    "field_shape_change",
                    "manual_migration",
                    f"{subject}.{change.field_name}",
                    False,
                    "type or identity conversion requires review",
                )
            )
        elif change.kind in {"presence_changed", "nullability_changed"}:
            facts.append(
                MigrationFact(
                    "presence_change",
                    "review",
                    f"{subject}.{change.field_name}",
                    True,
                    "storage and wire semantics must be reviewed",
                )
            )
    if not facts and report.status == "compatible":
        facts.append(MigrationFact("none", "no_action", subject, True, "no storage migration facts were found"))
    return facts


def _find_model(workspace: Workspace, domain_name: str, model_name: str, version: int) -> ModelVersion:
    for domain in workspace.mdl.domains:
        if domain.name == domain_name:
            for candidate in domain.models.get(model_name, []):
                if candidate.version == version:
                    return candidate
    raise LookupError(f"unresolved model {domain_name}.{model_name}@{version}")
