from __future__ import annotations

from pathlib import Path
import re

from modelable.compat.diff import compare_model_versions
from modelable.diagnostics.model import Diagnostic
from modelable.parser.ir import (
    AnnWire,
    ChangeKind,
    ClassificationLevel,
    ComputedMapping,
    MdlFile,
    ModelKind,
    ModelVersion,
    EnumType,
    FieldDef,
    ObjectType,
    PrimitiveType,
    DecimalType,
)

_VALID_CLASSIFICATION_LEVELS = {level.value for level in ClassificationLevel}
_CLASSIFICATION_LEVELS_DISPLAY = ", ".join(sorted(_VALID_CLASSIFICATION_LEVELS))
_VALID_WIRE_TARGETS = {"json", "rust", "clickhouse"}
_VALID_JSON_ENCODINGS = {"string"}
_VALID_CLICKHOUSE_ENCODINGS = {"uuid", "string", "u8"}
_VALID_RUST_CASE_VALUES = {
    "snake_case",
    "SCREAMING_SNAKE_CASE",
    "camelCase",
    "PascalCase",
    "kebab-case",
    "lowercase",
    "UPPERCASE",
}

_AGGREGATE_FUNCTIONS = ("count", "sum", "min", "max", "avg")
_AGGREGATE_PATTERN = re.compile(
    r"\b(" + "|".join(_AGGREGATE_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)
_SCALAR_MAX_MIN = frozenset({"max", "min"})


def _is_scalar_max_min(expression: str, match: re.Match) -> bool:
    """Return True when max/min is called with 2+ args (scalar greatest/least)."""
    if match.group(1).lower() not in _SCALAR_MAX_MIN:
        return False
    depth = 1
    for ch in expression[match.end():]:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return False
        elif ch == "," and depth == 1:
            return True
    return False


def validate(mdl: MdlFile) -> list[str]:
    """Return semantic validation errors. An empty list means the file is valid."""
    return [diagnostic.message for diagnostic in validate_diagnostics(mdl)]


def validate_diagnostics(mdl: MdlFile, path: str | Path | None = None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for domain in mdl.domains:
        if not domain.owner:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"domain '{domain.name}' must have an owner attribute",
                    path,
                )
            )
        _validate_models(domain.name, domain.models, diagnostics, path)
        _validate_projections(domain.name, domain.projections, diagnostics, path)
    return diagnostics


def _validate_classification_level(
    fqn: str,
    field_name: str,
    level: str,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    if level not in _VALID_CLASSIFICATION_LEVELS:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{field_name}' has invalid classification level '{level}'. "
                f"Valid levels are: {_CLASSIFICATION_LEVELS_DISPLAY}",
                path,
            )
        )


def _validate_models(
    domain_name,
    models,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    for model_name, versions in models.items():
        fqn = f"{domain_name}.{model_name}"
        version_numbers = [version.version for version in versions]

        for index in range(1, len(version_numbers)):
            previous = version_numbers[index - 1]
            current = version_numbers[index]
            if current <= previous:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: versions must be strictly ascending, "
                        f"but found {previous} followed by {current}",
                        path,
                    )
                )

        for version in versions:
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event) and not version.has_version_header:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: {version.model_kind.value} must have a version header (e.g. @ 1 (additive))",
                        path,
                    )
                )
            elif version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event) and not version.has_change_kind:
                 diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}@{version.version}: {version.model_kind.value} must have a change kind (additive) or (breaking)",
                        path,
                    )
                )
            key_fields = [field for field in version.fields if field.is_key]
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate):
                if len(key_fields) != 1:
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}@{version.version}: {version.model_kind.value} "
                            "must have exactly one @key field",
                            path,
                        )
                    )
            elif key_fields:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}@{version.version}: {version.model_kind.value} "
                        "must not have an @key field",
                        path,
                    )
                )
            for field in version.fields:
                _validate_field_annotations(
                    f"{fqn}@{version.version}",
                    field,
                    diagnostics,
                    path,
                    field_path=[field.name],
                )

        for index in range(1, len(versions)):
            previous = versions[index - 1]
            current = versions[index]
            _validate_change_kind(fqn, previous, current, diagnostics, path)


def _validate_projections(
    domain_name,
    projections,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    for projection_name, versions in projections.items():
        fqn = f"{domain_name}.{projection_name}"
        for version in versions:
            has_group_by = bool(version.group_by)
            for field in version.fields:
                mapping = field.mapping
                if not isinstance(mapping, ComputedMapping):
                    continue

                aggregate_match = _AGGREGATE_PATTERN.search(mapping.expression)
                if aggregate_match and not has_group_by and not _is_scalar_max_min(mapping.expression, aggregate_match):
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}@{version.version}: field '{field.name}' uses "
                            f"aggregation function '{aggregate_match.group(1)}' "
                            "but the projection has no group by clause",
                            path,
                        )
                    )
            for field in version.fields:
                _validate_field_annotations(
                    f"{fqn}@{version.version}",
                    field,
                    diagnostics,
                    path,
                    field_path=[field.name],
                )


def _validate_change_kind(
    fqn: str,
    previous: ModelVersion,
    current: ModelVersion,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    changes = compare_model_versions(previous, current)
    incompatible_changes: list[str] = []

    for change in changes:
        if change.kind == "added_field":
            field = _find_field(current, change.field_name)
            if field is None or not field.optional:
                incompatible_changes.append(f"added required field {change.field_name}")
            continue

        if change.kind == "nullability_changed":
            if change.from_optional is False and change.to_optional is True:
                continue
            incompatible_changes.append(f"nullability change {change.field_name}")
            continue

        incompatible_changes.append(f"{change.kind} {change.field_name}")

    context = f"{fqn}@{current.version}"
    if current.change_kind == ChangeKind.additive:
        if incompatible_changes:
            diagnostics.append(
                _diag(
                    "COMPAT",
                    f"{context}: additive declaration includes incompatible changes: "
                    + ", ".join(incompatible_changes),
                    path,
                )
            )
    elif current.change_kind == ChangeKind.breaking:
        if not incompatible_changes:
            diagnostics.append(
                _diag(
                    "COMPAT",
                    f"{context}: breaking declaration must include at least one incompatible change",
                    path,
                )
            )


def _find_field(version: ModelVersion, field_name: str):
    return next((field for field in version.fields if field.name == field_name), None)


def _validate_field_annotations(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_path: list[str],
) -> None:
    field_label = ".".join(field_path)
    for annotation in field.annotations:
        if annotation.kind == "classification":
            _validate_classification_level(
                fqn,
                field_label,
                annotation.level,
                diagnostics,
                path,
            )
        elif annotation.kind == "wire":
            _validate_wire_hints(
                fqn,
                field,
                annotation,
                diagnostics,
                path,
                field_label=field_label,
            )
    field_type = getattr(field, "type", None)
    if isinstance(field_type, ObjectType):
        for child in field_type.fields:
            _validate_field_annotations(
                fqn,
                child,
                diagnostics,
                path,
                field_path=[*field_path, child.name],
            )


def _validate_wire_hints(
    fqn: str,
    field: FieldDef,
    annotation: AnnWire,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
) -> None:
    label = field_label or field.name
    for target_name, hint in annotation.targets.items():
        if target_name not in _VALID_WIRE_TARGETS:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: field '{label}' has unknown wire target '{target_name}'. "
                    f"Valid targets are: {', '.join(sorted(_VALID_WIRE_TARGETS))}",
                    path,
                )
            )
            continue

        if target_name == "json":
            _validate_json_wire_hint(fqn, field, hint, diagnostics, path, field_label=label)
        elif target_name == "rust":
            _validate_rust_wire_hint(fqn, field, hint, diagnostics, path, field_label=label)
        elif target_name == "clickhouse":
            _validate_clickhouse_wire_hint(
                fqn,
                field,
                hint,
                diagnostics,
                path,
                field_label=label,
            )


def _validate_json_wire_hint(
    fqn: str,
    field: FieldDef,
    hint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
) -> None:
    label = field_label or field.name
    field_type = getattr(field, "type", None)
    if hint.encoding is None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has @wire(json: ...) without an encoding",
                path,
            )
        )
        return
    if hint.encoding not in _VALID_JSON_ENCODINGS:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has unsupported json wire encoding '{hint.encoding}'. "
                f"Valid encodings are: {', '.join(sorted(_VALID_JSON_ENCODINGS))}",
                path,
            )
        )
        return
    if hint.type is not None or hint.case is not None or hint.overrides:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use rust-style modifiers on json wire hints",
                path,
            )
        )
    if field_type is not None and not (
        (isinstance(field_type, PrimitiveType) and field_type.kind == "int")
        or isinstance(field_type, DecimalType)
    ):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' only supports @wire(json: ...) on int or decimal fields",
                path,
            )
        )


def _validate_rust_wire_hint(
    fqn: str,
    field: FieldDef,
    hint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
) -> None:
    label = field_label or field.name
    field_type = getattr(field, "type", None)
    if hint.encoding is not None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use an encoding on rust wire hints",
                path,
            )
        )
        return
    if hint.type is not None and field_type is not None and not (
        isinstance(field_type, PrimitiveType) and field_type.kind == "int"
    ):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' only supports rust.type on int fields",
                path,
            )
        )
    if hint.case is not None and hint.case not in _VALID_RUST_CASE_VALUES:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has unsupported rust.case '{hint.case}'. "
                f"Valid values are: {', '.join(sorted(_VALID_RUST_CASE_VALUES))}",
                path,
            )
        )
    if hint.overrides:
        if field_type is None or not isinstance(field_type, EnumType):
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: field '{label}' only supports rust.overrides on enum fields",
                    path,
                )
            )
        else:
            invalid_keys = sorted(set(hint.overrides) - set(field_type.values))
            if invalid_keys:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: field '{label}' has rust.overrides entries for unknown enum members: "
                        + ", ".join(invalid_keys),
                        path,
                    )
                )


def _validate_clickhouse_wire_hint(
    fqn: str,
    field: FieldDef,
    hint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
) -> None:
    label = field_label or field.name
    field_type = getattr(field, "type", None)
    if hint.encoding is None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has @wire(clickhouse: ...) without an encoding",
                path,
            )
        )
        return
    if hint.encoding not in _VALID_CLICKHOUSE_ENCODINGS:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has unsupported clickhouse wire encoding '{hint.encoding}'. "
                f"Valid encodings are: {', '.join(sorted(_VALID_CLICKHOUSE_ENCODINGS))}",
                path,
            )
        )


def _diag(code: str, message: str, path: str | Path | None) -> Diagnostic:
    return Diagnostic(code=code, message=message, severity="error", path=str(path or "<workspace>"))
