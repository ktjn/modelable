"""Compiler-owned complete-version-to-delta representation (evolution plan
A2, instruction #1): the inverse of `workspace.py::_expand_model_evolutions`
-- given two consecutive full-form `ModelVersion`s, compute the
`add`/`remove`/`rename`/`replace` operations that reproduce ``target``
exactly from ``base``.

Deliberately conservative on two axes:

- **Rename evidence.** A field is only proposed as a rename when the base
  field carries `@deprecated(replacedBy: "newName")` naming a field that
  exists in the target and does not itself exist in the base -- the exact
  same evidence `compat/diff.py::_deprecated_replacement` already uses to
  recognize a rename during compatibility comparison. Any other removed/
  added pair, however similar in shape, stays a `remove` plus an `add`;
  this module never guesses a rename from name or type similarity.
- **Field order.** `add` always appends in the grammar/expansion semantics
  (`workspace.py::_expand_model_evolutions` calls `new_fields.append(...)`,
  never inserts), so an operation sequence can only reproduce a target
  whose field order is exactly "base's surviving fields, in base's
  original relative order, followed by newly-added fields in target's
  trailing order." A target that inserted a new field in the *middle* of
  the field list cannot be reproduced by any operation sequence without
  reordering fields -- and since Protobuf field numbers and struct/record
  field order in every codegen target are assigned by declaration order,
  silently reordering would be a real generated-artifact change, which A2's
  own exit criteria forbids ("no canonical contract or generated artifact
  changes"). `compute_delta_operations` returns ``None`` in that case
  rather than reorder.
"""

from __future__ import annotations

from modelable.compat.diff import _deprecated_replacement
from modelable.parser.ir import (
    AddFieldOp,
    EvolutionOperation,
    FieldDef,
    ModelVersion,
    RemoveFieldOp,
    RenameFieldOp,
    ReplaceFieldOp,
)


def compute_delta_operations(base: ModelVersion, target: ModelVersion) -> list[EvolutionOperation] | None:
    """Return operations that expand ``base`` into exactly ``target``, or
    ``None`` if no operation sequence can reproduce ``target``'s field order
    without reordering fields."""
    base_by_name = {field.name: field for field in base.fields}
    target_by_name = {field.name: field for field in target.fields}

    renames: dict[str, str] = {}
    for old_field in base.fields:
        if old_field.name in target_by_name:
            continue
        replacement = _deprecated_replacement(old_field)
        if replacement is not None and replacement in target_by_name and replacement not in base_by_name:
            renames[old_field.name] = replacement

    kept_sequence: list[tuple[str, str]] = []
    for old_field in base.fields:
        if old_field.name in target_by_name:
            kept_sequence.append((old_field.name, old_field.name))
        elif old_field.name in renames:
            kept_sequence.append((old_field.name, renames[old_field.name]))

    kept_target_names = [new_name for _old_name, new_name in kept_sequence]
    target_names_in_order = [field.name for field in target.fields]
    if target_names_in_order[: len(kept_target_names)] != kept_target_names:
        return None

    added_names = target_names_in_order[len(kept_target_names) :]
    if set(added_names) != set(target_by_name) - set(kept_target_names):
        return None

    operations: list[EvolutionOperation] = []
    for old_field in base.fields:
        if old_field.name not in target_by_name and old_field.name not in renames:
            operations.append(RemoveFieldOp(field_name=old_field.name))

    for old_name, new_name in kept_sequence:
        old_field = base_by_name[old_name]
        new_field = target_by_name[new_name]
        if old_name == new_name:
            if not _fields_equal_ignoring_name(old_field, new_field):
                operations.append(ReplaceFieldOp(field=new_field))
            continue
        operations.append(RenameFieldOp(old_name=old_name, new_name=new_name))
        renamed_view = old_field.model_copy(update={"name": new_name})
        if not _fields_equal_ignoring_name(renamed_view, new_field):
            operations.append(ReplaceFieldOp(field=new_field))

    for name in added_names:
        operations.append(AddFieldOp(field=target_by_name[name]))

    return operations


def _fields_equal_ignoring_name(left: FieldDef, right: FieldDef) -> bool:
    return left.model_copy(update={"name": right.name}) == right
