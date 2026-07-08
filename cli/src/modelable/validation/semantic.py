from __future__ import annotations

import re
from pathlib import Path

from modelable.compat.diff import compare_model_versions
from modelable.diagnostics.model import Diagnostic
from modelable.parser.ir import (
    AnnWire,
    ChangeKind,
    ClassificationLevel,
    ComputedMapping,
    DecimalType,
    DomainDef,
    EnumType,
    FieldDef,
    FieldType,
    FixedBinaryType,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    SemanticTypeDecl,
)
from modelable.registry.resolver import resolve_model_ref

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
_VALID_TS_FIELD_CASE_VALUES = {
    "snake_case",
    "SCREAMING_SNAKE_CASE",
    "camelCase",
    "PascalCase",
}

_INTEGER_BOUNDS: dict[str, tuple[int, int]] = {
    "u8": (0, 2**8 - 1),
    "u16": (0, 2**16 - 1),
    "u32": (0, 2**32 - 1),
    "u64": (0, 2**64 - 1),
    "u128": (0, 2**128 - 1),
    "i8": (-(2**7), 2**7 - 1),
    "i16": (-(2**15), 2**15 - 1),
    "i32": (-(2**31), 2**31 - 1),
    "i64": (-(2**63), 2**63 - 1),
    "i128": (-(2**127), 2**127 - 1),
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
    for ch in expression[match.end() :]:
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
        _validate_projections(domain.name, domain.projections, diagnostics, path, mdl)
        _validate_semantic_types(domain, mdl, diagnostics, path)
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
                        f"{fqn}: versions must be strictly ascending, but found {previous} followed by {current}",
                        path,
                    )
                )

        for version in versions:
            if (
                version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event)
                and not version.has_version_header
            ):
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: {version.model_kind.value} must have a version header (e.g. @ 1 (additive))",
                        path,
                    )
                )
            elif (
                version.model_kind in (ModelKind.entity, ModelKind.aggregate, ModelKind.event)
                and not version.has_change_kind
            ):
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}@{version.version}: {version.model_kind.value} must have a change kind (additive) or (breaking)",
                        path,
                    )
                )
            _validate_declaration_wire_annotations(f"{fqn}@{version.version}", version, diagnostics, path)
            key_fields = [field for field in version.fields if field.is_key]
            if version.model_kind in (ModelKind.entity, ModelKind.aggregate):
                if len(key_fields) != 1:
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}@{version.version}: {version.model_kind.value} must have exactly one @key field",
                            path,
                        )
                    )
            elif key_fields:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}@{version.version}: {version.model_kind.value} must not have an @key field",
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
                    field_type=field.type,
                )
                _validate_default_value_range(f"{fqn}@{version.version}", field, diagnostics, path)
                _validate_fixed_binary_length(f"{fqn}@{version.version}", field, diagnostics, path)

        for index in range(1, len(versions)):
            previous = versions[index - 1]
            current = versions[index]
            _validate_change_kind(fqn, previous, current, diagnostics, path)


def _validate_projections(
    domain_name,
    projections,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    mdl: MdlFile,
) -> None:
    for projection_name, versions in projections.items():
        fqn = f"{domain_name}.{projection_name}"
        for version in versions:
            _validate_declaration_wire_annotations(f"{fqn}@{version.version}", version, diagnostics, path)
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
                source_type = _resolve_projection_field_type(field, version, mdl)
                _validate_field_annotations(
                    f"{fqn}@{version.version}",
                    field,
                    diagnostics,
                    path,
                    field_path=[field.name],
                    field_type=source_type,
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
    elif current.change_kind == ChangeKind.breaking and not incompatible_changes:
        diagnostics.append(
            _diag(
                "COMPAT",
                f"{context}: breaking declaration must include at least one incompatible change",
                path,
            )
        )


def _validate_declaration_wire_annotations(
    fqn: str,
    version,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    try:
        version.wire_targets()
    except ValueError as exc:
        diagnostics.append(_diag("SEM", f"{fqn}: has conflicting @wire annotations: {exc}", path))
        return
    for annotation in version.annotations:
        if annotation.kind != "wire":
            continue
        for target_name, hint in annotation.targets.items():
            if target_name not in _VALID_WIRE_TARGETS:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: has unknown wire target '{target_name}'. "
                        f"Valid targets are: {', '.join(sorted(_VALID_WIRE_TARGETS))}",
                        path,
                    )
                )
                continue
            if (
                target_name != "json"
                or hint.field_case is None
                or hint.encoding is not None
                or hint.type is not None
                or hint.case is not None
                or hint.overrides
            ):
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: only @wire(json.fieldCase: ...) is supported on model/projection declarations",
                        path,
                    )
                )
                continue
            if hint.field_case not in _VALID_TS_FIELD_CASE_VALUES:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{fqn}: unsupported json.fieldCase '{hint.field_case}'. "
                        f"Valid values are: {', '.join(sorted(_VALID_TS_FIELD_CASE_VALUES))}",
                        path,
                    )
                )


def _find_field(version: ModelVersion, field_name: str):
    return next((field for field in version.fields if field.name == field_name), None)


def _validate_default_value_range(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    if field.default is None:
        return
    if not isinstance(field.type, PrimitiveType):
        return
    bounds = _INTEGER_BOUNDS.get(field.type.kind)
    if bounds is None:
        return
    try:
        value = int(field.default.strip())
    except ValueError:
        return
    low, high = bounds
    if not (low <= value <= high):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{field.name}' default {value} is out of range for {field.type.kind} "
                f"(valid range {low}..{high})",
                path,
            )
        )


def _validate_fixed_binary_length(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    if not isinstance(field.type, FixedBinaryType):
        return
    if not (1 <= field.type.length <= 4096):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{field.name}' binary({field.type.length}) length must be between 1 and 4096",
                path,
            )
        )


_SEMANTIC_UNDERLYING_TYPES = (PrimitiveType, DecimalType, FixedBinaryType, NamedType)
_SEMANTIC_CHAIN_DEPTH_LIMIT = 32


def _validate_semantic_types(
    domain: DomainDef,
    mdl: MdlFile,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    seen_names: set[str] = set()
    for decl in domain.semantic_types:
        if decl.name in seen_names:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' is declared more than once",
                    path,
                )
            )
        seen_names.add(decl.name)

        if decl.name in domain.models:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' collides with a model of the same name",
                    path,
                )
            )

        if not isinstance(decl.underlying, _SEMANTIC_UNDERLYING_TYPES):
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' has unsupported underlying type "
                    f"'{decl.underlying.kind}' (must be a primitive, decimal, binary(N), or another semantic type)",
                    path,
                )
            )

    all_semantic_types: dict[str, SemanticTypeDecl] = {
        other_decl.name: other_decl for other_domain in mdl.domains for other_decl in other_domain.semantic_types
    }

    for decl in domain.semantic_types:
        if not isinstance(decl.underlying, NamedType):
            continue
        visited: list[str] = [decl.name]
        current: FieldType = decl.underlying
        while isinstance(current, NamedType):
            next_name = current.name
            if next_name in visited:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' has a cycle in its underlying chain: "
                        f"{' -> '.join([*visited, next_name])}",
                        path,
                    )
                )
                break
            if next_name not in all_semantic_types:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' references undeclared semantic type '{next_name}'",
                        path,
                    )
                )
                break
            if len(visited) >= _SEMANTIC_CHAIN_DEPTH_LIMIT:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' underlying chain exceeds "
                        f"{_SEMANTIC_CHAIN_DEPTH_LIMIT} levels",
                        path,
                    )
                )
                break
            visited.append(next_name)
            current = all_semantic_types[next_name].underlying


def _validate_field_annotations(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_path: list[str],
    field_type=None,
) -> None:
    field_label = ".".join(field_path)
    try:
        field.wire_targets()
    except ValueError as exc:
        diagnostics.append(_diag("SEM", f"{fqn}: field '{field_label}' has conflicting @wire annotations: {exc}", path))
        return
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
                field_type=field_type,
            )
    if isinstance(field_type, ObjectType):
        for child in field_type.fields:
            _validate_field_annotations(
                fqn,
                child,
                diagnostics,
                path,
                field_path=[*field_path, child.name],
                field_type=child.type,
            )


def _validate_wire_hints(
    fqn: str,
    field: FieldDef,
    annotation: AnnWire,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
    field_type=None,
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
            _validate_json_wire_hint(
                fqn,
                field,
                hint,
                diagnostics,
                path,
                field_label=label,
                field_type=field_type,
            )
        elif target_name == "rust":
            _validate_rust_wire_hint(
                fqn,
                field,
                hint,
                diagnostics,
                path,
                field_label=label,
                field_type=field_type,
            )
        elif target_name == "clickhouse":
            _validate_clickhouse_wire_hint(
                fqn,
                field,
                hint,
                diagnostics,
                path,
                field_label=label,
                field_type=field_type,
            )


def _validate_json_wire_hint(
    fqn: str,
    field: FieldDef,
    hint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_label: str | None = None,
    field_type=None,
) -> None:
    label = field_label or field.name
    if hint.field_case is not None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use @wire(json.fieldCase: ...) — "
                "json.fieldCase is only valid on model/projection declarations",
                path,
            )
        )
        return
    is_enum = isinstance(field_type, EnumType)

    if hint.encoding is None:
        # json.case / json.overrides on enum fields are valid without an encoding
        if is_enum and (hint.case is not None or hint.overrides):
            return
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
    # hint.type is a Rust-specific modifier that doesn't belong on the json target
    if hint.type is not None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use rust.type on a json wire hint",
                path,
            )
        )
        return
    # json.case / json.overrides are valid JSON modifiers but only on enum fields
    if (hint.case is not None or hint.overrides) and not is_enum:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' uses @wire(json.case / json.overrides) on a non-enum field",
                path,
            )
        )
        return
    if (
        field_type is not None
        and not is_enum
        and not (
            (isinstance(field_type, PrimitiveType) and field_type.kind == "int") or isinstance(field_type, DecimalType)
        )
    ):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' only supports @wire(json: ...) on int, decimal, or enum fields",
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
    field_type=None,
) -> None:
    label = field_label or field.name
    if hint.encoding is not None:
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' may not use an encoding on rust wire hints",
                path,
            )
        )
        return
    if (
        hint.type is not None
        and field_type is not None
        and not (isinstance(field_type, PrimitiveType) and field_type.kind == "int")
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
    field_type=None,
) -> None:
    label = field_label or field.name
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
        return


def _resolve_projection_field_type(field, projection, mdl):
    if not hasattr(field, "mapping"):
        return getattr(field, "type", None)
    mapping = field.mapping
    if isinstance(mapping, ComputedMapping):
        return None
    if mapping.source_alias == projection.source.alias:
        source_ref = projection.source
    else:
        source_ref = next((j for j in projection.joins if j.alias == mapping.source_alias), None)
        if source_ref is None:
            return None
    try:
        source_domain, source_model = source_ref.model.rsplit(".", 1)
    except ValueError:
        return None
    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", source_ref.version)
    except LookupError:
        return None
    return _resolve_field_type_from_version(
        mdl,
        resolved.version,
        mapping.source_field,
    )


def _resolve_field_type_from_version(mdl: MdlFile, version, field_name: str):
    if hasattr(version, "fields"):
        field = next((item for item in version.fields if item.name == field_name), None)
        if field is None:
            return None
        field_type = getattr(field, "type", None)
        if field_type is not None:
            return field_type
        mapping = getattr(field, "mapping", None)
        if mapping is None or mapping.kind != "direct":
            return None
        try:
            source_domain, source_model = version.source.model.rsplit(".", 1)
        except ValueError, AttributeError:
            return None
        try:
            resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", version.source.version)
        except LookupError:
            return None
        return _resolve_field_type_from_version(mdl, resolved.version, mapping.source_field)
    return None


def _diag(code: str, message: str, path: str | Path | None) -> Diagnostic:
    return Diagnostic(code=code, message=message, severity="error", path=str(path or "<workspace>"))
