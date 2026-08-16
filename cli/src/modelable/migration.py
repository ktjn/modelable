from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modelable.compat.checker import CompatibilityReport
from modelable.compiler.workspace import Workspace
from modelable.parser.ir import ModelVersion


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
