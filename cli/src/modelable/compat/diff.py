from __future__ import annotations

import json
from dataclasses import dataclass

from modelable.compat.projection_fields import resolve_projection_field_type_and_optionality
from modelable.parser.ir import (
    AccessBlock,
    AnnDeprecated,
    ClassificationLevel,
    ComputedMapping,
    DirectMapping,
    EnumType,
    FieldDef,
    FieldType,
    IndexDecl,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    RefType,
)


@dataclass(frozen=True)
class FieldChange:
    kind: str
    field_name: str
    previous_name: str | None = None
    replacement: str | None = None
    from_optional: bool | None = None
    to_optional: bool | None = None
    from_nullable: bool | None = None
    to_nullable: bool | None = None
    from_type: str | None = None
    to_type: str | None = None


@dataclass(frozen=True)
class ProjectionChange:
    dimension: str  # "shape" | "lineage" | "governance" | "wire" | "storage" | "source_version" | "materialisation"
    kind: str
    breaking: bool
    field_name: str | None = None
    message: str = ""


def compare_model_versions(old_version: ModelVersion, new_version: ModelVersion) -> list[FieldChange]:
    """Compare two published model versions field by field."""
    changes: list[FieldChange] = []
    old_fields = {field.name: field for field in old_version.fields}
    new_fields = {field.name: field for field in new_version.fields}
    matched_old: set[str] = set()
    matched_new: set[str] = set()

    for old_field in old_version.fields:
        replacement = _deprecated_replacement(old_field)
        if replacement is None:
            continue
        new_field = new_fields.get(replacement)
        if new_field is None or replacement in matched_new:
            continue
        changes.append(
            FieldChange(
                kind="renamed_field",
                field_name=old_field.name,
                previous_name=old_field.name,
                replacement=replacement,
                from_optional=old_field.optional,
                to_optional=new_field.optional,
                from_nullable=old_field.nullable,
                to_nullable=new_field.nullable,
                from_type=_type_signature(old_field),
                to_type=_type_signature(new_field),
            )
        )
        if old_field.optional != new_field.optional:
            changes.append(
                FieldChange(
                    kind="presence_changed",
                    field_name=replacement,
                    from_optional=old_field.optional,
                    to_optional=new_field.optional,
                    from_nullable=old_field.nullable,
                    to_nullable=new_field.nullable,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )
        if old_field.nullable != new_field.nullable:
            changes.append(
                FieldChange(
                    kind="nullability_changed",
                    field_name=replacement,
                    from_nullable=old_field.nullable,
                    to_nullable=new_field.nullable,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )
        if _type_signature(old_field) != _type_signature(new_field):
            if isinstance(old_field.type, EnumType) and isinstance(new_field.type, EnumType):
                kind = "enum_changed"
            else:
                kind = "type_changed"
            changes.append(
                FieldChange(
                    kind=kind,
                    field_name=replacement,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )
        matched_old.add(old_field.name)
        matched_new.add(replacement)

    for old_field in old_version.fields:
        if old_field.name in matched_old:
            continue
        if old_field.name not in new_fields:
            changes.append(
                FieldChange(
                    kind="removed_field",
                    field_name=old_field.name,
                    from_optional=old_field.optional,
                    from_type=_type_signature(old_field),
                )
            )

    for name in _sorted_common_field_names(old_fields, new_fields):
        old_field = old_fields[name]
        new_field = new_fields[name]

        if old_field.optional != new_field.optional:
            changes.append(
                FieldChange(
                    kind="presence_changed",
                    field_name=name,
                    from_optional=old_field.optional,
                    to_optional=new_field.optional,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )

        if old_field.nullable != new_field.nullable:
            changes.append(
                FieldChange(
                    kind="nullability_changed",
                    field_name=name,
                    from_nullable=old_field.nullable,
                    to_nullable=new_field.nullable,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )

        if old_field.is_key != new_field.is_key:
            changes.append(
                FieldChange(
                    kind="identity_changed",
                    field_name=name,
                    from_type=_type_signature(old_field),
                    to_type=_type_signature(new_field),
                )
            )

        old_sig = _type_signature(old_field)
        new_sig = _type_signature(new_field)
        if old_sig == new_sig:
            continue
        if isinstance(old_field.type, EnumType) and isinstance(new_field.type, EnumType):
            changes.append(
                FieldChange(
                    kind="enum_changed",
                    field_name=name,
                    from_type=old_sig,
                    to_type=new_sig,
                )
            )
        else:
            changes.append(
                FieldChange(
                    kind="type_changed",
                    field_name=name,
                    from_type=old_sig,
                    to_type=new_sig,
                )
            )

    for new_field in new_version.fields:
        if new_field.name in matched_new:
            continue
        if new_field.name not in old_fields:
            changes.append(
                FieldChange(
                    kind="added_field",
                    field_name=new_field.name,
                    to_optional=new_field.optional,
                    to_type=_type_signature(new_field),
                )
            )

    changes.extend(_compare_model_governance(old_version, new_version))
    return changes


def _compare_model_governance(old: ModelVersion, new: ModelVersion) -> list[FieldChange]:
    changes: list[FieldChange] = []
    old_grants = _access_grant_triples(old.access)
    new_grants = _access_grant_triples(new.access)
    for scope, principal, permission in sorted(old_grants - new_grants):
        changes.append(
            FieldChange(
                kind="access_grant_removed",
                field_name="entity" if scope == "entity" else scope,
                from_type=f"{principal} {permission}",
            )
        )
    for scope, principal, permission in sorted(new_grants - old_grants):
        changes.append(
            FieldChange(
                kind="access_grant_added",
                field_name="entity" if scope == "entity" else scope,
                to_type=f"{principal} {permission}",
            )
        )
    old_fields = {field.name: field for field in old.fields}
    new_fields = {field.name: field for field in new.fields}
    for name in sorted(set(old_fields) & set(new_fields)):
        old_field = old_fields[name]
        new_field = new_fields[name]
        if old_field.is_pii != new_field.is_pii:
            changes.append(
                FieldChange(
                    kind="pii_changed",
                    field_name=name,
                    from_type=str(old_field.is_pii).lower(),
                    to_type=str(new_field.is_pii).lower(),
                )
            )
        old_classification = old_field.classification.value if old_field.classification else None
        new_classification = new_field.classification.value if new_field.classification else None
        if old_classification != new_classification:
            changes.append(
                FieldChange(
                    kind="classification_changed",
                    field_name=name,
                    from_type=str(old_classification),
                    to_type=str(new_classification),
                )
            )
    return changes


def _sorted_common_field_names(
    old_fields: dict[str, FieldDef],
    new_fields: dict[str, FieldDef],
) -> list[str]:
    names = [field.name for field in old_fields.values() if field.name in new_fields]
    return names


def _deprecated_replacement(field: FieldDef) -> str | None:
    for annotation in field.annotations:
        if isinstance(annotation, AnnDeprecated):
            return annotation.replaced_by
    return None


def _ref_aware_type_dump(field_type: FieldType) -> object:
    """Serialize a field type for breaking-change detection.

    For ref<> specifically, only .target participates — pointing a ref at a
    different model is a real type change, but bumping the version it
    points at (target unchanged) is not breaking on its own.
    """
    if isinstance(field_type, RefType):
        return {"kind": "ref", "target": field_type.target}
    return field_type.model_dump(mode="json")


def _type_signature(field: FieldDef) -> str:
    return json.dumps(_ref_aware_type_dump(field.type), sort_keys=True)


def is_optionality_breaking(change: FieldChange) -> bool:
    """True when a presence change narrows a field from optional to required."""
    return change.kind == "presence_changed" and change.from_optional is True and change.to_optional is False


def is_nullability_breaking(change: FieldChange) -> bool:
    """True when a nullability change narrows a field from nullable to non-null."""
    return change.kind == "nullability_changed" and change.from_nullable is True and change.to_nullable is False


def is_field_change_breaking(change: FieldChange) -> bool:
    """True when a single FieldChange, on its own, breaks source compatibility.

    The one classifier for "is this model-version field change breaking";
    compat/checker.py's report-level rollup and compat/targets.py's
    source-compatibility axis both call this instead of re-deriving it.
    """
    if change.kind in {
        "removed_field",
        "renamed_field",
        "type_changed",
        "enum_changed",
        "identity_changed",
        "access_grant_removed",
        "pii_changed",
        "classification_changed",
    }:
        return True
    if change.kind == "added_field" and change.to_optional is False:
        return True
    return is_optionality_breaking(change) or is_nullability_breaking(change)


def describe_bool_word(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "optional" if value else "required"


def describe_nullable_word(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "nullable" if value else "non-null"


def describe_field_change(change: FieldChange) -> str:
    """Render a FieldChange as the one human-readable finding string.

    Shared by `modelable diff` (compat/checker.py) and the target-agnostic
    source-compatibility axis (compat/targets.py) so there is one wording,
    not two.
    """
    if change.kind == "index_changed":
        return f"index_changed {change.field_name}"
    if change.kind == "renamed_field":
        return f"renamed_field {change.field_name} -> {change.replacement}"
    if change.kind == "presence_changed":
        return (
            f"presence_changed {change.field_name}: "
            f"{describe_bool_word(change.from_optional)} -> {describe_bool_word(change.to_optional)}"
        )
    if change.kind == "nullability_changed":
        return (
            f"nullability_changed {change.field_name}: "
            f"{describe_nullable_word(change.from_nullable)} -> {describe_nullable_word(change.to_nullable)}"
        )
    if change.kind == "identity_changed":
        return f"identity_changed {change.field_name}"
    if change.kind == "enum_changed":
        return f"enum_changed {change.field_name}"
    if change.kind == "type_changed":
        return f"type_changed {change.field_name}"
    if change.kind == "removed_field":
        return f"removed_field {change.field_name}"
    if change.kind == "added_field":
        return f"added_field {change.field_name}"
    if change.kind == "access_grant_removed":
        return f"access_grant_removed {change.field_name or 'entity'} (governance): access grant removed: {change.from_type}"
    if change.kind == "access_grant_added":
        return f"access_grant_added {change.field_name or 'entity'} (governance): access grant added: {change.to_type}"
    if change.kind == "pii_changed":
        return f"pii_changed {change.field_name} (governance): {change.from_type} -> {change.to_type}"
    if change.kind == "classification_changed":
        return f"classification_changed {change.field_name} (governance): {change.from_type} -> {change.to_type}"
    return f"{change.kind} {change.field_name}"


def compare_index_decls(old_index: IndexDecl | None, new_index: IndexDecl | None) -> list[FieldChange]:
    """Surface index structure changes between two model versions.

    Callers classify breakingness themselves: compat/checker.py's model
    status treats any index change as informational (index changes alone
    don't flip a version to "breaking"), while compat/targets.py's
    storage_migration axis (Slice C3) classifies every index change as
    `migration_required`, since a changed index always needs a rebuild
    regardless of whether the model contract itself broke.
    """
    if old_index is None and new_index is None:
        return []

    changes: list[FieldChange] = []
    old_primary = old_index.primary if old_index else []
    new_primary = new_index.primary if new_index else []
    if old_primary != new_primary:
        changes.append(FieldChange(kind="index_changed", field_name="primary"))

    old_secondary = {s.name: s for s in (old_index.secondary if old_index else [])}
    new_secondary = {s.name: s for s in (new_index.secondary if new_index else [])}
    for name in sorted(set(old_secondary) | set(new_secondary)):
        if old_secondary.get(name) != new_secondary.get(name):
            changes.append(FieldChange(kind="index_changed", field_name=name))

    return changes


def _shape_type_signature(field_type: FieldType | None) -> str | None:
    if field_type is None:
        return None
    return json.dumps(_ref_aware_type_dump(field_type), sort_keys=True)


def _compare_shape(
    mdl: MdlFile,
    old: ProjectionVersion,
    new: ProjectionVersion,
) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) - set(new_fields)):
        changes.append(
            ProjectionChange(
                dimension="shape",
                kind="field_removed",
                breaking=True,
                field_name=name,
                message=f"field '{name}' was removed",
            )
        )

    for name in sorted(set(new_fields) - set(old_fields)):
        changes.append(
            ProjectionChange(
                dimension="shape",
                kind="field_added",
                breaking=False,
                field_name=name,
                message=f"field '{name}' was added",
            )
        )

    for name in sorted(set(old_fields) & set(new_fields)):
        old_field = old_fields[name]
        new_field = new_fields[name]
        old_type, old_optional = resolve_projection_field_type_and_optionality(old_field, old, mdl)
        new_type, new_optional = resolve_projection_field_type_and_optionality(new_field, new, mdl)

        if old_type is None or new_type is None:
            if old_type is not None or new_type is not None:
                changes.append(
                    ProjectionChange(
                        dimension="shape",
                        kind="type_unresolvable",
                        breaking=True,
                        field_name=name,
                        message=f"field '{name}' type can no longer be resolved (mapping became unresolvable)",
                    )
                )
        else:
            if _shape_type_signature(old_type) != _shape_type_signature(new_type):
                changes.append(
                    ProjectionChange(
                        dimension="shape",
                        kind="type_changed",
                        breaking=True,
                        field_name=name,
                        message=f"field '{name}' changed type",
                    )
                )

            if old_optional != new_optional:
                breaking = old_optional is True and new_optional is False
                changes.append(
                    ProjectionChange(
                        dimension="shape",
                        kind="optionality_changed",
                        breaking=breaking,
                        field_name=name,
                        message=f"field '{name}' optionality changed: {old_optional} -> {new_optional}",
                    )
                )

    return changes


def _compare_lineage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) & set(new_fields)):
        old_mapping = old_fields[name].mapping
        new_mapping = new_fields[name].mapping

        if isinstance(old_mapping, DirectMapping) and isinstance(new_mapping, DirectMapping):
            if (old_mapping.source_alias, old_mapping.source_field) != (
                new_mapping.source_alias,
                new_mapping.source_field,
            ):
                changes.append(
                    ProjectionChange(
                        dimension="lineage",
                        kind="source_remapped",
                        breaking=False,
                        field_name=name,
                        message=(
                            f"field '{name}' source remapped: "
                            f"{old_mapping.source_alias}.{old_mapping.source_field} -> "
                            f"{new_mapping.source_alias}.{new_mapping.source_field}"
                        ),
                    )
                )
        elif isinstance(old_mapping, ComputedMapping) and isinstance(new_mapping, ComputedMapping):
            if old_mapping.expression != new_mapping.expression:
                changes.append(
                    ProjectionChange(
                        dimension="lineage",
                        kind="expression_changed",
                        breaking=False,
                        field_name=name,
                        message=f"field '{name}' computed expression changed",
                    )
                )
        elif old_mapping.kind != new_mapping.kind:
            changes.append(
                ProjectionChange(
                    dimension="lineage",
                    kind="mapping_kind_changed",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' mapping changed from {old_mapping.kind} to {new_mapping.kind}",
                )
            )

    return changes


_CLASSIFICATION_ORDER = {level: index for index, level in enumerate(ClassificationLevel)}


def _classification_index(level: ClassificationLevel | None) -> int:
    if level is None:
        return -1
    return _CLASSIFICATION_ORDER[level]


def _access_grant_triples(access: AccessBlock | None) -> set[tuple[str, str, str]]:
    """Flatten a projection's AccessBlock into (scope, principal, permission) triples.

    scope is "entity" for entity-level grants, or the property name for
    per-property grants.
    """
    if access is None:
        return set()
    triples: set[tuple[str, str, str]] = set()
    for grant in access.entity:
        for permission in grant.permissions:
            triples.add(("entity", grant.principal, permission))
    for property_name, grants in access.properties.items():
        for grant in grants:
            for permission in grant.permissions:
                triples.add((property_name, grant.principal, permission))
    return triples


def _compare_governance(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []

    old_grants = _access_grant_triples(old.access)
    new_grants = _access_grant_triples(new.access)

    for scope, principal, permission in sorted(old_grants - new_grants):
        changes.append(
            ProjectionChange(
                dimension="governance",
                kind="access_grant_removed",
                breaking=True,
                field_name=None if scope == "entity" else scope,
                message=f"access grant removed: {scope} principal '{principal}' permission '{permission}'",
            )
        )
    for scope, principal, permission in sorted(new_grants - old_grants):
        changes.append(
            ProjectionChange(
                dimension="governance",
                kind="access_grant_added",
                breaking=False,
                field_name=None if scope == "entity" else scope,
                message=f"access grant added: {scope} principal '{principal}' permission '{permission}'",
            )
        )

    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}
    for name in sorted(set(old_fields) & set(new_fields)):
        old_field = old_fields[name]
        new_field = new_fields[name]

        if old_field.is_pii != new_field.is_pii:
            changes.append(
                ProjectionChange(
                    dimension="governance",
                    kind="pii_changed",
                    breaking=new_field.is_pii,
                    field_name=name,
                    message=f"field '{name}' @pii changed: {old_field.is_pii} -> {new_field.is_pii}",
                )
            )

        old_level = old_field.classification
        new_level = new_field.classification
        if old_level != new_level:
            tightened = _classification_index(new_level) > _classification_index(old_level)
            changes.append(
                ProjectionChange(
                    dimension="governance",
                    kind="classification_changed",
                    breaking=tightened,
                    field_name=name,
                    message=f"field '{name}' classification changed: {old_level} -> {new_level}",
                )
            )

    return changes


def _compare_wire(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []
    old_fields = {f.name: f for f in old.fields}
    new_fields = {f.name: f for f in new.fields}

    for name in sorted(set(old_fields) & set(new_fields)):
        old_targets = old_fields[name].wire_targets()
        new_targets = new_fields[name].wire_targets()

        for target in sorted(set(old_targets) & set(new_targets)):
            if old_targets[target] != new_targets[target]:
                changes.append(
                    ProjectionChange(
                        dimension="wire",
                        kind="wire_hint_changed",
                        breaking=True,
                        field_name=name,
                        message=f"field '{name}' @wire hint for '{target}' changed",
                    )
                )

        for target in sorted(set(new_targets) - set(old_targets)):
            changes.append(
                ProjectionChange(
                    dimension="wire",
                    kind="wire_hint_added",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' @wire hint added for '{target}'",
                )
            )

        for target in sorted(set(old_targets) - set(new_targets)):
            changes.append(
                ProjectionChange(
                    dimension="wire",
                    kind="wire_hint_removed",
                    breaking=False,
                    field_name=name,
                    message=f"field '{name}' @wire hint removed for '{target}'",
                )
            )

    return changes


def _compare_storage(old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    changes: list[ProjectionChange] = []

    if old.where != new.where:
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="where_changed",
                breaking=True,
                message=f"where clause changed: {old.where!r} -> {new.where!r}",
            )
        )

    if old.group_by != new.group_by:
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="group_by_changed",
                breaking=True,
                message=f"group by changed: {old.group_by!r} -> {new.group_by!r}",
            )
        )

    old_joins = {join.alias: join for join in old.joins}
    new_joins = {join.alias: join for join in new.joins}

    for alias in sorted(set(old_joins) - set(new_joins)):
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="join_removed",
                breaking=True,
                field_name=alias,
                message=f"join '{alias}' was removed",
            )
        )
    for alias in sorted(set(new_joins) - set(old_joins)):
        changes.append(
            ProjectionChange(
                dimension="storage",
                kind="join_added",
                breaking=True,
                field_name=alias,
                message=f"join '{alias}' was added",
            )
        )
    for alias in sorted(set(old_joins) & set(new_joins)):
        old_join = old_joins[alias]
        new_join = new_joins[alias]
        if (old_join.cardinality, old_join.join_kind, old_join.on) != (
            new_join.cardinality,
            new_join.join_kind,
            new_join.on,
        ):
            changes.append(
                ProjectionChange(
                    dimension="storage",
                    kind="join_changed",
                    breaking=True,
                    field_name=alias,
                    message=f"join '{alias}' cardinality/kind/predicate changed",
                )
            )

    return changes


def compare_projection_versions(mdl: MdlFile, old: ProjectionVersion, new: ProjectionVersion) -> list[ProjectionChange]:
    """Compare two published projection versions across the shape, lineage,
    governance, wire, and storage dimensions.

    Source-version comparison lives in compat/checker.py instead of here,
    since it delegates to check_model_version_compatibility() and this
    module must not import from checker.py (checker.py already imports
    from this module; the reverse would be circular).
    """
    changes: list[ProjectionChange] = []
    changes.extend(_compare_shape(mdl, old, new))
    changes.extend(_compare_lineage(old, new))
    changes.extend(_compare_governance(old, new))
    changes.extend(_compare_wire(old, new))
    changes.extend(_compare_storage(old, new))
    return changes
