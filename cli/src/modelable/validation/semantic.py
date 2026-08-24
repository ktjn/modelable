from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

from modelable.compat.diff import compare_model_versions, is_field_change_breaking, is_optionality_breaking
from modelable.diagnostics.model import Diagnostic
from modelable.emitters.naming import apply_case_style, find_identifier_collisions
from modelable.parser.ir import (
    AnnWire,
    ArrayType,
    ChangeKind,
    ClassificationLevel,
    ComputedMapping,
    DecimalType,
    DomainDef,
    EnumRefType,
    EnumType,
    FieldDef,
    FieldType,
    FixedBinaryType,
    MapType,
    MdlFile,
    ModelKind,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
    UnionType,
    WireTargetHint,
)
from modelable.registry.resolver import resolve_model_ref, resolve_ref_type, resolve_semantic_type_ref

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
        _validate_index_decls(domain, diagnostics, path)
        _validate_api_declarations(domain, diagnostics, path)
    return diagnostics


_API_PATH_RE = re.compile(r"^/(?:[^{}]|\{[A-Za-z_][A-Za-z0-9_]*\})*$")
_API_PATH_PARAMETER_RE = re.compile(r"\{([^{}]+)\}")


def _validate_api_declarations(
    domain: DomainDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    """Validate API declarations that can be checked before projection expansion."""
    seen_api_versions: set[tuple[str, int]] = set()
    for api in domain.apis:
        api_fqn = f"{domain.name}.{api.model}@{api.version}"
        api_key = (api.model, api.version)
        if api_key in seen_api_versions:
            diagnostics.append(_diag("SEM", f"{api_fqn}: duplicate API declaration", path))
        seen_api_versions.add(api_key)

        model_versions = domain.models.get(api.model, [])
        model = next((item for item in model_versions if item.version == api.version), None)
        if model is None:
            diagnostics.append(_diag("SEM", f"{api_fqn}: bound model version does not exist", path))
            key_names: set[str] = set()
        else:
            if model.model_kind not in (ModelKind.entity, ModelKind.aggregate):
                diagnostics.append(_diag("SEM", f"{api_fqn}: API must bind to an entity or aggregate", path))
            key_names = {field.name for field in model.fields if field.is_key}

        operation_names: set[str] = set()
        route_keys: set[tuple[str, str]] = set()
        for operation in api.operations:
            operation_fqn = f"{api_fqn} operation '{operation.name}'"
            if operation.name in operation_names:
                diagnostics.append(_diag("SEM", f"{operation_fqn}: duplicate operation name", path))
            operation_names.add(operation.name)
            route_key = (operation.method, operation.path)
            if route_key in route_keys:
                diagnostics.append(_diag("SEM", f"{operation_fqn}: duplicate method/path", path))
            route_keys.add(route_key)
            if not _API_PATH_RE.fullmatch(operation.path):
                diagnostics.append(_diag("SEM", f"{operation_fqn}: invalid path template", path))
            parameters = _API_PATH_PARAMETER_RE.findall(operation.path)
            if len(parameters) != len(set(parameters)):
                diagnostics.append(_diag("SEM", f"{operation_fqn}: duplicate path parameter", path))
            unknown = sorted(set(parameters) - key_names)
            if unknown:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{operation_fqn}: path parameter(s) not found among model keys: {', '.join(unknown)}",
                        path,
                    )
                )
            response_codes = [response.status_code for response in operation.responses]
            if not response_codes:
                diagnostics.append(_diag("SEM", f"{operation_fqn}: requires at least one response", path))
            if len(response_codes) != len(set(response_codes)):
                diagnostics.append(_diag("SEM", f"{operation_fqn}: duplicate response status code", path))
            for status_code in response_codes:
                if not 100 <= status_code <= 599:
                    diagnostics.append(
                        _diag("SEM", f"{operation_fqn}: invalid response status code {status_code}", path)
                    )


def _validate_enum_members(
    fqn: str,
    label: str,
    field_type: FieldType,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    """Recursively validate anonymous `enum(...)` members (evolution plan F2).

    Canonical identity is the authored member text, independent of any target
    spelling: an empty member set or duplicate canonical members are rejected
    before emitters run. Recurses through arrays, maps, inline objects, and
    discriminated-union variants so no parsed enum bypasses the check.
    """
    if isinstance(field_type, EnumType):
        if not field_type.values:
            diagnostics.append(_diag("SEM", f"{fqn}: field '{label}' has an empty enum member set", path))
            return
        seen: set[str] = set()
        duplicates: list[str] = []
        for value in field_type.values:
            if value in seen and value not in duplicates:
                duplicates.append(value)
            seen.add(value)
        for value in duplicates:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: field '{label}' has duplicate enum member '{value}'",
                    path,
                )
            )
        return
    if isinstance(field_type, ArrayType):
        _validate_enum_members(fqn, f"{label}[]", field_type.item, diagnostics, path)
        return
    if isinstance(field_type, MapType):
        _validate_enum_members(fqn, f"{label}{{}}", field_type.value, diagnostics, path)
        return
    if isinstance(field_type, ObjectType):
        for sub_field in field_type.fields:
            _validate_enum_members(fqn, f"{label}.{sub_field.name}", sub_field.type, diagnostics, path)
        return
    if isinstance(field_type, UnionType):
        for variant in field_type.variants:
            _validate_enum_members(fqn, f"{label}.{variant.tag}", variant.type, diagnostics, path)


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
                _validate_value_constraints(f"{fqn}@{version.version}", field, diagnostics, path)
                _validate_enum_members(f"{fqn}@{version.version}", field.name, field.type, diagnostics, path)

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
                _validate_value_constraints(
                    f"{fqn}@{version.version}", field, diagnostics, path, field_type=source_type
                )
                if source_type is not None:
                    _validate_enum_members(f"{fqn}@{version.version}", field.name, source_type, diagnostics, path)


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
        if not is_field_change_breaking(change):
            continue

        if change.kind == "added_field":
            field = _find_field(current, change.field_name)
            if field is None or not field.optional:
                incompatible_changes.append(f"added required field {change.field_name}")
            continue

        if change.kind == "presence_changed":
            if not is_optionality_breaking(change):
                continue
            incompatible_changes.append(f"presence change {change.field_name}")
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


def _validate_value_constraints(
    fqn: str,
    field: FieldDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
    *,
    field_type: FieldType | None = None,
) -> None:
    constraints = getattr(field, "constraints", [])
    if not constraints:
        return
    field_type = field_type or field.type
    is_numeric = isinstance(field_type, DecimalType) or (
        isinstance(field_type, PrimitiveType)
        and field_type.kind in {"int", "float", "u8", "u16", "u32", "u64", "u128", "i8", "i16", "i32", "i64", "i128"}
    )
    is_string = isinstance(field_type, PrimitiveType) and field_type.kind == "string"
    is_array = isinstance(field_type, ArrayType)
    for constraint in constraints:
        kind = constraint.kind
        if kind not in {
            "min",
            "max",
            "min_length",
            "max_length",
            "pattern",
            "format",
            "min_items",
            "max_items",
            "unique_items",
        }:
            diagnostics.append(_diag("SEM", f"{fqn}: field '{field.name}' uses unknown constraint '{kind}'", path))
            continue
        if kind in {"min", "max"} and not is_numeric:
            diagnostics.append(
                _diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' requires a numeric type", path)
            )
        elif kind in {"min_length", "max_length", "pattern"} and not is_string:
            diagnostics.append(_diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' requires string", path))
        elif kind in {"min_items", "max_items", "unique_items"} and not is_array:
            diagnostics.append(_diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' requires an array", path))
        if kind in {"min_length", "max_length", "min_items", "max_items"} and (
            not isinstance(constraint.value, int) or constraint.value < 0
        ):
            diagnostics.append(
                _diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' must be a non-negative integer", path)
            )
        if kind in {"min", "max"} and not isinstance(constraint.value, (int, float)):
            diagnostics.append(_diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' must be numeric", path))
        if kind in {"pattern", "format"} and not isinstance(constraint.value, str):
            diagnostics.append(_diag("SEM", f"{fqn}: field '{field.name}' constraint '{kind}' must be a string", path))
        if kind == "unique_items" and not isinstance(constraint.value, bool):
            diagnostics.append(
                _diag("SEM", f"{fqn}: field '{field.name}' constraint 'unique_items' must be boolean", path)
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


_SEMANTIC_UNDERLYING_TYPES = (PrimitiveType, DecimalType, FixedBinaryType, EnumType, NamedType, EnumRefType)
_SEMANTIC_CHAIN_DEPTH_LIMIT = 32


def _validate_semantic_types(
    domain: DomainDef,
    mdl: MdlFile,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    seen_names: set[str] = set()
    for decl in domain.semantic_types:
        same_name = [item for item in domain.semantic_types if item.name == decl.name]
        same_version = [item for item in same_name if item.version == decl.version]
        if len(same_version) > 1:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}@{decl.version}' is declared more than once",
                    path,
                )
            )
        seen_names.add(decl.name)

        if decl.has_version_header and decl.version < 1:
            diagnostics.append(
                _diag("SEM", f"{domain.name}: semantic type '{decl.name}' must have a positive version", path)
            )
        if decl.has_change_kind and not decl.has_version_header:
            diagnostics.append(
                _diag("SEM", f"{domain.name}: semantic type '{decl.name}' change kind requires a version header", path)
            )

        if decl.name in domain.models:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' collides with a model of the same name",
                    path,
                )
            )
        if decl.name in domain.projections:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' collides with a projection of the same name",
                    path,
                )
            )

        if not isinstance(decl.underlying, _SEMANTIC_UNDERLYING_TYPES):
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{domain.name}: semantic type '{decl.name}' has unsupported underlying type "
                    f"'{decl.underlying.kind}' (must be a primitive, decimal, enum, binary(N), or another semantic type)",
                    path,
                )
            )

        # Member-identity checks specific to enum-backed declarations (E1):
        # reuse the anonymous-enum member rules on the declared member set.
        if isinstance(decl.underlying, EnumType):
            if not decl.underlying.values:
                diagnostics.append(
                    _diag("SEM", f"{domain.name}: semantic type '{decl.name}' has an empty enum member set", path)
                )
            duplicates = sorted({value for value in decl.underlying.values if decl.underlying.values.count(value) > 1})
            for value in duplicates:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' has duplicate enum member '{value}'",
                        path,
                    )
                )

    for name in sorted(seen_names):
        versions = sorted((item for item in domain.semantic_types if item.name == name), key=lambda item: item.version)
        for previous, current_version in pairwise(versions):
            fqn = f"{domain.name}.{name}@{current_version.version}"
            if (
                current_version.change_kind == "additive"
                and isinstance(previous.underlying, EnumType)
                and isinstance(current_version.underlying, EnumType)
            ):
                removed = sorted(set(previous.underlying.values) - set(current_version.underlying.values))
                if removed:
                    diagnostics.append(
                        _diag("SEM", f"{fqn}: additive enum evolution removes values: {', '.join(removed)}", path)
                    )
            if (
                current_version.change_kind == "additive"
                and not isinstance(previous.underlying, EnumType)
                and previous.underlying.model_dump() != current_version.underlying.model_dump()
            ):
                diagnostics.append(_diag("SEM", f"{fqn}: additive evolution cannot change the underlying type", path))

    for decl in domain.semantic_types:
        if not isinstance(decl.underlying, NamedType):
            continue
        visited: list[str] = [f"{domain.name}.{decl.name}"]
        current: FieldType = decl.underlying
        current_domain_name = domain.name
        while isinstance(current, NamedType):
            next_name = current.name
            try:
                next_domain_name, next_decl = resolve_semantic_type_ref(mdl, current_domain_name, next_name)
            except LookupError as exc:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' references {exc}",
                        path,
                    )
                )
                break
            qualified = f"{next_domain_name}.{next_decl.name}"
            if qualified in visited:
                diagnostics.append(
                    _diag(
                        "SEM",
                        f"{domain.name}: semantic type '{decl.name}' has a cycle in its underlying chain: "
                        f"{' -> '.join([*visited, qualified])}",
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
            visited.append(qualified)
            current = next_decl.underlying
            current_domain_name = next_domain_name


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


def _validate_json_wire_value_collisions(
    fqn: str,
    label: str,
    field_type: EnumType,
    hint: WireTargetHint,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    """Reject @wire(json.case/overrides) mappings that collapse two canonical
    enum members onto one wire value (evolution plan F3, item 3)."""

    def _wire_value(member: str) -> str:
        override = hint.overrides.get(member)
        if override is not None:
            return override
        if hint.case is not None:
            return apply_case_style(member, hint.case)
        return member

    for value, members in find_identifier_collisions(list(field_type.values), _wire_value).items():
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' maps enum members "
                + ", ".join(f"'{member}'" for member in members)
                + f" to the same json wire value '{value}'",
                path,
            )
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
        # json.case / json.overrides on enum fields are valid without an encoding,
        # but two canonical members must never map to the same wire value.
        if is_enum and (hint.case is not None or hint.overrides):
            _validate_json_wire_value_collisions(fqn, label, field_type, hint, diagnostics, path)
            return
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' has @wire(json: ...) without an encoding",
                path,
            )
        )
        return
    if not isinstance(hint.encoding, str) or hint.encoding not in _VALID_JSON_ENCODINGS:
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
        and not (
            isinstance(field_type, PrimitiveType)
            and field_type.kind in {"int", "date", "time", "timestamp", "duration"}
        )
    ):
        diagnostics.append(
            _diag(
                "SEM",
                f"{fqn}: field '{label}' only supports rust.type on int and temporal fields",
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


def _validate_index_decls(
    domain: DomainDef,
    diagnostics: list[Diagnostic],
    path: str | Path | None,
) -> None:
    seen_model_versions: set[tuple[str, int]] = set()
    for decl in domain.index_decls:
        fqn = f"{domain.name}.{decl.model}@{decl.version}"

        if (decl.model, decl.version) in seen_model_versions:
            diagnostics.append(_diag("SEM", f"{fqn}: index is declared more than once for this model version", path))
        seen_model_versions.add((decl.model, decl.version))

        model_versions = domain.models.get(decl.model)
        if model_versions is None:
            diagnostics.append(_diag("SEM", f"{fqn}: index references unknown model '{decl.model}'", path))
            continue
        model_version = next((mv for mv in model_versions if mv.version == decl.version), None)
        if model_version is None:
            diagnostics.append(
                _diag("SEM", f"{fqn}: index references {decl.model}@{decl.version} which does not exist", path)
            )
            continue

        if model_version.model_kind not in (ModelKind.entity, ModelKind.aggregate):
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: index may only target 'entity' or 'aggregate' models, "
                    f"but '{decl.model}' is '{model_version.model_kind.value}'",
                    path,
                )
            )
            continue

        field_names = {field.name for field in model_version.fields}
        key_field_names = {field.name for field in model_version.fields if field.is_key}

        if set(decl.primary) != key_field_names:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: index primary {sorted(decl.primary)} must exactly match "
                    f"the model's @key field(s) {sorted(key_field_names)}",
                    path,
                )
            )

        seen_secondary_names: set[str] = set()
        for secondary in decl.secondary:
            if secondary.name in seen_secondary_names:
                diagnostics.append(
                    _diag("SEM", f"{fqn}: secondary index '{secondary.name}' is declared more than once", path)
                )
            seen_secondary_names.add(secondary.name)

            for field_name in secondary.key:
                if field_name not in field_names:
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}: secondary index '{secondary.name}' references undeclared field "
                            f"'{field_name}' in 'key'",
                            path,
                        )
                    )
            for sort_field in secondary.sort:
                if sort_field.field not in field_names:
                    diagnostics.append(
                        _diag(
                            "SEM",
                            f"{fqn}: secondary index '{secondary.name}' references undeclared field "
                            f"'{sort_field.field}' in 'sort'",
                            path,
                        )
                    )


def _iter_ref_types(field_type: FieldType) -> list[RefType]:
    if isinstance(field_type, RefType):
        return [field_type]
    if isinstance(field_type, ArrayType):
        return _iter_ref_types(field_type.item)
    if isinstance(field_type, MapType):
        return _iter_ref_types(field_type.value)
    if isinstance(field_type, ObjectType):
        found: list[RefType] = []
        for nested_field in field_type.fields:
            found.extend(_iter_ref_types(nested_field.type))
        return found
    return []


def validate_ref_type_field(
    fqn: str,
    field: FieldDef,
    mdl: MdlFile,
    diagnostics: list[Diagnostic],
    warnings: list[Diagnostic],
    path: str | Path | None,
) -> None:
    """Validate every ref<> nested anywhere in one field's type.

    `mdl` must be the fully MERGED multi-file workspace, never a single
    source file's own MdlFile — a ref<> can legitimately point at a model
    declared in a different source file (the normal pattern throughout
    samples/scenarios/), so resolution has to happen after all sources are
    merged. This function is intentionally NOT wired into
    validate_diagnostics/_validate_models (which only ever see one source
    file at a time) — it is called from compiler/workspace.py instead,
    exactly like the existing validate_references/_validate_merged_workspace
    machinery already does for projection source/join references. It is
    public (no leading underscore) because it is called across the
    validation/semantic.py -> compiler/workspace.py module boundary.
    """
    for ref_type in _iter_ref_types(field.type):
        if "." not in ref_type.target:
            # An unqualified (no-dot) ref<> target is not a Modelable
            # domain.model reference at all — it's the established pattern
            # for pointing at an external, unmodeled resource type (e.g.
            # ref<Organization> in FHIR profiles, consumed as a bare
            # targetProfile name by emitters/fhir.py). resolve_model_ref's
            # _split_model_ref already categorically rejects non-dotted
            # names, and that was true before this task — nothing ever
            # asked it to resolve one before. Skip validation rather than
            # flag every external reference as a SEM error.
            continue
        try:
            resolved = resolve_ref_type(ref_type, mdl)
        except LookupError as exc:
            diagnostics.append(
                _diag(
                    "SEM",
                    f"{fqn}: field '{field.name}' has an unresolvable ref<{ref_type.target}>: {exc}",
                    path,
                )
            )
            continue

        if ref_type.version is None:
            warnings.append(
                Diagnostic(
                    code="REF",
                    message=(
                        f"{fqn}: field '{field.name}' has ref<{ref_type.target}> with no version "
                        f"constraint; resolved to version {resolved.version.version} at compile time. "
                        f"Add '@ {resolved.version.version}' (or a version range) where durable "
                        f"identity matters."
                    ),
                    severity="warning",
                    path=str(path or "<workspace>"),
                )
            )


def _diag(code: str, message: str, path: str | Path | None) -> Diagnostic:
    return Diagnostic(code=code, message=message, severity="error", path=str(path or "<workspace>"))
