from __future__ import annotations

import json
from dataclasses import dataclass

from modelable.parser.ir import AnnDeprecated, EnumType, FieldDef, ModelVersion


@dataclass(frozen=True)
class FieldChange:
    kind: str
    field_name: str
    previous_name: str | None = None
    replacement: str | None = None
    from_optional: bool | None = None
    to_optional: bool | None = None
    from_type: str | None = None
    to_type: str | None = None


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
                from_type=_type_signature(old_field),
                to_type=_type_signature(new_field),
            )
        )
        if old_field.optional != new_field.optional:
            changes.append(
                FieldChange(
                    kind="nullability_changed",
                    field_name=replacement,
                    from_optional=old_field.optional,
                    to_optional=new_field.optional,
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
                    kind="nullability_changed",
                    field_name=name,
                    from_optional=old_field.optional,
                    to_optional=new_field.optional,
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


def _type_signature(field: FieldDef) -> str:
    return json.dumps(field.type.model_dump(mode="json"), sort_keys=True)
