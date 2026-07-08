from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import missing_metadata, type_loss
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import (
    ArrayType,
    DirectMapping,
    DomainDef,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    ProjectionVersion,
)
from modelable.registry.resolver import resolve_model_ref


@dataclass
class _FieldSpec:
    index: int
    name: str
    annotation: str
    optional: bool
    serde_attrs: list[str] = dc_field(default_factory=list)


def _append_cross_enum_from_impls(
    artifacts: list[EmittedArtifact],
    enum_registry: dict[str, dict],
) -> list[EmittedArtifact]:
    """For each pair of enum types with identical variants in the same domain,
    append From impl blocks into projection files without manual match arms.
    """
    # Group by domain: domain -> [(artifact_id, module_name, enums_dict, kind)]
    by_domain: dict[str, list[tuple[str, str, dict[str, list[str]], str]]] = {}
    for art_id, info in enum_registry.items():
        domain = info["domain"]
        by_domain.setdefault(domain, []).append((art_id, info["module_name"], info["enums"], info["kind"]))

    # Build: frozenset(raw_variants) -> [(artifact_id, module_name, enum_type_name)]
    # Per domain — From impls only work within the same Rust module tree (super:: path).
    extra: dict[str, list[str]] = {}  # artifact_id -> lines to append
    for _domain, entries in by_domain.items():
        variant_map: dict[frozenset, list[tuple[str, str, str, str]]] = {}
        for art_id, module_name, enums, kind in entries:
            for enum_type_name, raw_variants in enums.items():
                key = frozenset(raw_variants)
                variant_map.setdefault(key, []).append((art_id, module_name, enum_type_name, kind))

        for variant_set, enum_list in variant_map.items():
            if len(enum_list) < 2:
                continue
            sorted_variants = sorted(variant_set)
            # For each ordered pair (src → tgt): put From<src> for tgt in tgt's file.
            for src_art_id, src_module, src_enum, _src_kind in enum_list:
                for tgt_art_id, _tgt_module, tgt_enum, tgt_kind in enum_list:
                    if src_art_id == tgt_art_id and src_enum == tgt_enum:
                        continue
                    if tgt_kind == "model":
                        continue
                    lines: list[str] = [
                        "",
                        f"use super::{src_module}::{src_enum};",
                        f"impl From<{src_enum}> for {tgt_enum} {{",
                        f"    fn from(src: {src_enum}) -> Self {{",
                        "        match src {",
                    ]
                    for raw_v in sorted_variants:
                        member = _enum_member_name(raw_v)
                        lines.append(f"            {src_enum}::{member} => {tgt_enum}::{member},")
                    lines += ["        }", "    }", "}"]
                    extra.setdefault(tgt_art_id, []).extend(lines)

    if not extra:
        return artifacts

    result: list[EmittedArtifact] = []
    for artifact in artifacts:
        appendage = extra.get(artifact.artifact_id)
        if appendage:
            new_content = artifact.content.rstrip("\n") + "\n" + "\n".join(appendage) + "\n"
            result.append(
                EmittedArtifact(
                    target=artifact.target,
                    ref=artifact.ref,
                    artifact_id=artifact.artifact_id,
                    path=artifact.path,
                    content=new_content,
                    content_hash=compute_content_hash(new_content),
                    warnings=artifact.warnings,
                )
            )
        else:
            result.append(artifact)
    return result


def emit_rust(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Rust source files for every model and projection version."""
    postgres_sources = _adapter_bound_sources(workspace.mdl, "postgres")
    clickhouse_sources = _adapter_bound_sources(workspace.mdl, "clickhouse")
    enum_registry: dict[str, dict] = {}
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(
                    _emit_model(domain, model_name, version, out_dir, enum_registry=enum_registry, mdl=workspace.mdl)
                )
        for projection_name, versions in domain.projections.items():
            for version in versions:
                source = version.source.model
                artifacts.append(
                    _emit_projection(
                        domain,
                        projection_name,
                        version,
                        out_dir,
                        workspace.mdl,
                        sqlx_fromrow=source in postgres_sources,
                        clickhouse_row=source in clickhouse_sources,
                        enum_registry=enum_registry,
                    )
                )
    return _append_cross_enum_from_impls(artifacts, enum_registry)


def _adapter_bound_sources(mdl: MdlFile, adapter_type: str) -> set[str]:
    """Return fully-qualified model names (domain.Model) bound to the given adapter type.

    Handles two-level indirection: a model binding may reference a connector binding by
    name (e.g. adapter: my-ch-conn), and the connector binding carries the actual
    adapter type (e.g. adapter: clickhouse).
    """
    adapter_types: dict[str, str] = {b.name: b.adapter for b in mdl.bindings if b.adapter}
    sources: set[str] = set()
    for b in mdl.bindings:
        if not b.model:
            continue
        resolved = adapter_types.get(b.adapter, b.adapter)
        if resolved == adapter_type:
            sources.add(b.model)
    return sources


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"


def _snake_case(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = text.strip("_").lower()
    return text or "generated"


def _stable_type_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _collect_named_type_refs(field_type, result: set) -> None:
    """Recursively collect NamedType names from a field type."""
    if isinstance(field_type, NamedType):
        result.add(field_type.name)
    elif isinstance(field_type, ArrayType):
        _collect_named_type_refs(field_type.item, result)
    elif isinstance(field_type, MapType):
        _collect_named_type_refs(field_type.key, result)
        _collect_named_type_refs(field_type.value, result)


def _resolve_named_type_map(named_refs: set, mdl: MdlFile | None) -> tuple[dict[str, str], list[str]]:
    """Resolve NamedType references to Rust type names from the workspace.

    Returns (name -> rust_type_name, list of use statements).
    """
    if not named_refs or mdl is None:
        return {}, []
    resolved_map: dict[str, str] = {}
    use_statements: list[str] = []
    for name in named_refs:
        for domain in mdl.domains:
            if name in domain.models:
                versions = domain.models[name]
                if versions:
                    latest = versions[-1]
                    rust_name = _stable_type_name(domain.name, name, latest.version)
                    module = _snake_case(rust_name)
                    resolved_map[name] = rust_name
                    use_statements.append(f"use super::{module}::{rust_name};")
                    break
    return resolved_map, use_statements


def _emit_model(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    *,
    enum_registry: dict[str, dict] | None = None,
    mdl: MdlFile | None = None,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    local_enum_info: dict[str, list[str]] = {}

    # Resolve NamedType references from the workspace
    named_refs: set[str] = set()
    for field in version.fields:
        _collect_named_type_refs(field.type, named_refs)
    named_type_map, use_statements = _resolve_named_type_map(named_refs, mdl)

    field_specs = _field_specs_from_model_fields(
        version.fields,
        owner_type=type_name,
        path=[],
        definitions=nested_definitions,
        enum_info=local_enum_info,
        named_type_map=named_type_map,
    )
    if enum_registry is not None:
        enum_registry[artifact_id] = {
            "enums": local_enum_info,
            "module_name": _snake_case(type_name),
            "domain": domain.name,
            "kind": "model",
        }

    warnings: list[str] = []
    for field in version.fields:
        if isinstance(field.type, NamedType) and field.type.name not in named_type_map:
            warnings.append(missing_metadata(f"{domain.name}.{model_name}.{field.name}"))

    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    needs_serde_json = _any_needs_serde_json(field_specs)
    lines = _header_lines(
        serde_with=needs_serde_with, uuid=needs_uuid, serde_json=needs_serde_json, extra_uses=use_statements
    )
    lines.extend(_render_struct_definition(type_name, field_specs))
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="rust",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl,
    *,
    sqlx_fromrow: bool = False,
    clickhouse_row: bool = False,
    enum_registry: dict[str, dict] | None = None,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    local_enum_info: dict[str, list[str]] = {}

    field_specs: list[_FieldSpec] = []
    warnings: list[str] = []
    for index, field in enumerate(version.fields):
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            field_specs.append(_FieldSpec(index=index, name=field.name, annotation="String", optional=False))
            continue
        wire = _resolve_merged_projection_wire(field, version, mdl)
        if clickhouse_row and field_shape.kind == "enum":
            # clickhouse-rs 0.15 panics on serialize_unit_variant for typed enums;
            # force String for all ClickHouse-bound enum fields.
            annotation = "String"
        else:
            annotation = _shape_annotation(
                field_shape,
                owner_type=type_name,
                path=[field.name],
                definitions=nested_definitions,
                rust_hint=wire.get("rust"),
                clickhouse_hint=wire.get("clickhouse"),
                enum_info=local_enum_info,
            )
        optional = field_shape.optional or field_shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, field_shape, clickhouse=clickhouse_row)
        if field_shape.optional and not clickhouse_row:
            serde_attrs = ['#[serde(skip_serializing_if = "Option::is_none")]', *serde_attrs]
        field_specs.append(
            _FieldSpec(index=index, name=field.name, annotation=annotation, optional=optional, serde_attrs=serde_attrs)
        )

    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    needs_serde_json = _any_needs_serde_json(field_specs) or any(
        _projection_field_is_json_passthrough_to_string(f, version, mdl) for f in version.fields
    )
    storage_gated = sqlx_fromrow or clickhouse_row
    extra_derives: list[str] = []
    if sqlx_fromrow:
        extra_derives.append("sqlx::FromRow")
    if clickhouse_row:
        extra_derives.append("clickhouse::Row")
    lines = _header_lines(
        serde_with=needs_serde_with,
        sqlx=sqlx_fromrow,
        clickhouse=clickhouse_row,
        uuid=needs_uuid,
        serde_json=needs_serde_json,
    )
    lines.extend(
        _render_struct_definition(type_name, field_specs, extra_derives=extra_derives, storage_gated=storage_gated)
    )
    lines.extend(_render_nested_definitions(nested_definitions))
    lines.extend(
        _emit_from_impl(
            type_name, domain.name, version, mdl, storage_gated=storage_gated, clickhouse_row=clickhouse_row
        )
    )

    if enum_registry is not None:
        enum_registry[artifact_id] = {
            "enums": local_enum_info,
            "module_name": _snake_case(type_name),
            "domain": domain.name,
            "kind": "projection",
        }

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="rust",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / _module_path(domain.name, type_name),
        content=text,
        content_hash=compute_content_hash(text),
        warnings=warnings,
    )


def _projection_field_is_json_passthrough_to_string(proj_field, version: ProjectionVersion, mdl: MdlFile) -> bool:
    """True if this projection field maps a map<K, json> (or bare json) source
    field to a @wire(clickhouse: "string") String target — i.e. needs a
    generated serde_json::to_string conversion in the From impl, and a
    serde_json::Value-shaped header requirement even though the projection's
    own field type is plain String.
    """
    if not isinstance(proj_field.mapping, DirectMapping):
        return False
    field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
    if field_shape is None:
        return False
    is_json_value = (field_shape.kind == "primitive" and field_shape.ref == "json") or (
        field_shape.kind == "map"
        and field_shape.value is not None
        and field_shape.value.kind == "primitive"
        and field_shape.value.ref == "json"
    )
    if not is_json_value:
        return False
    wire = _resolve_merged_projection_wire(proj_field, version, mdl)
    ch_hint = wire.get("clickhouse")
    return ch_hint is not None and getattr(ch_hint, "encoding", None) == "string"


def _emit_from_impl(
    proj_type_name: str,
    proj_domain: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    *,
    storage_gated: bool = False,
    clickhouse_row: bool = False,
) -> list[str]:
    """Emit impl From<SourceModel> for Projection.

    Only generated for single-source projections (no joins) where the source model
    is in the same domain as the projection. The caller is responsible for placing
    both modules under a common parent so that super:: paths resolve.
    """
    if version.joins:
        return []

    try:
        src_domain_str, src_model_name = version.source.model.rsplit(".", 1)
    except ValueError:
        return []

    # Only generate when source and projection share the same domain (super:: path is valid)
    if src_domain_str != proj_domain:
        return []

    try:
        resolved = resolve_model_ref(mdl, version.source.model, version.source.version)
    except LookupError:
        return []

    src_version = resolved.version
    src_type_name = _stable_type_name(src_domain_str, src_model_name, src_version.version)
    src_module = _snake_case(src_type_name)

    lines: list[str] = [""]
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.append(f"use super::{src_module}::{src_type_name};")
    if clickhouse_row:
        for proj_field in version.fields:
            if not isinstance(proj_field.mapping, DirectMapping):
                continue
            field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
            if field_shape is not None and field_shape.kind == "enum":
                enum_type = _nested_type_name(src_type_name, [proj_field.mapping.source_field])
                if storage_gated:
                    lines.append('#[cfg(feature = "storage")]')
                lines.append(f"use super::{src_module}::{enum_type};")
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.append(f"impl From<{src_type_name}> for {proj_type_name} {{")
    lines.append(f"    fn from(src: {src_type_name}) -> Self {{")
    lines.append("        Self {")

    for proj_field in version.fields:
        rust_name = _field_name(proj_field.name)
        if isinstance(proj_field.mapping, DirectMapping):
            src_rust_name = _field_name(proj_field.mapping.source_field)
            field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
            if clickhouse_row and field_shape is not None and field_shape.kind == "enum":
                # ClickHouse-bound enum fields are stored as String; generate explicit match.
                src_enum_type = _nested_type_name(src_type_name, [proj_field.mapping.source_field])
                lines.append(f"            {rust_name}: match src.{src_rust_name} {{")
                for raw_v in field_shape.enum_values:
                    member = _enum_member_name(raw_v)
                    lines.append(f'                {src_enum_type}::{member} => "{raw_v}".to_string(),')
                lines.append("            },")
            elif _projection_field_is_json_passthrough_to_string(proj_field, version, mdl):
                lines.append(
                    f"            {rust_name}: serde_json::to_string(&src.{src_rust_name}).unwrap_or_default(),"
                )
            elif field_shape is not None and _shape_involves_object(field_shape):
                lines.append(f"            {rust_name}: Default::default(), // nested struct — provide manual impl")
            else:
                lines.append(f"            {rust_name}: src.{src_rust_name}.into(),")
        else:
            lines.append(f"            {rust_name}: Default::default(), // computed — provide manual impl")

    lines.append("        }")
    lines.append("    }")
    lines.append("}")
    return lines


def _serde_attrs_for_field(wire: dict, shape: TypeShape, *, clickhouse: bool = False) -> list[str]:
    """Return per-field #[serde(...)] attributes derived from @wire hints."""
    rust_hint = wire.get("rust")
    json_hint = wire.get("json")
    # u64-as-string: rust.type is overridden to u64 and json serialization is string.
    if (
        rust_hint is not None
        and getattr(rust_hint, "type", None)
        and json_hint is not None
        and getattr(json_hint, "encoding", None) == "string"
        and shape.kind == "primitive"
    ):
        return ['#[serde(with = "serde_with::rust::display_fromstr")]']
    # ClickHouse UUID encoding hint.
    if clickhouse:
        ch_hint = wire.get("clickhouse")
        if ch_hint is not None and getattr(ch_hint, "encoding", None) == "uuid":
            return ['#[serde(with = "clickhouse::serde::uuid")]']
    return []


def _any_needs_serde_with(field_specs: list[_FieldSpec]) -> bool:
    return any(any("serde_with" in attr for attr in spec.serde_attrs) for spec in field_specs)


def _any_needs_uuid(field_specs: list[_FieldSpec]) -> bool:
    return any("uuid::Uuid" in spec.annotation for spec in field_specs)


def _any_needs_serde_json(field_specs: list[_FieldSpec]) -> bool:
    return any("serde_json::Value" in spec.annotation for spec in field_specs)


def _shape_involves_object(shape: TypeShape) -> bool:
    """Return True if the shape contains an inline object type.

    Inline object fields generate distinct named types per-struct (e.g.
    CustomerV1Address vs CustomerViewV1Address). Those types don't implement
    From/Into for each other, so the generated From impl must fall back to
    Default::default() rather than emitting .into().
    """
    if shape.kind == "object":
        return True
    if shape.element is not None and _shape_involves_object(shape.element):
        return True
    return bool(shape.value is not None and _shape_involves_object(shape.value))


def _header_lines(
    *,
    serde_with: bool = False,
    sqlx: bool = False,
    clickhouse: bool = False,
    uuid: bool = False,
    serde_json: bool = False,
    extra_uses: list[str] | None = None,
) -> list[str]:
    lines = [
        "// @generated by Modelable",
        "use std::collections::HashMap;",
        "",
    ]
    if clickhouse:
        lines.insert(1, "// requires: clickhouse (https://docs.rs/clickhouse)")
    if sqlx:
        lines.insert(1, "// requires: sqlx (https://docs.rs/sqlx)")
    if serde_with:
        lines.insert(1, "// requires: serde_with (https://docs.rs/serde_with)")
    if uuid:
        lines.insert(1, "// requires: uuid (https://docs.rs/uuid)")
    if serde_json:
        lines.insert(1, "// requires: serde_json (https://docs.rs/serde_json)")
    if extra_uses:
        # Insert use statements just before the trailing empty string
        lines[-1:-1] = extra_uses
    return lines


def _render_nested_definitions(definitions: dict[str, list[str]]) -> list[str]:
    lines: list[str] = []
    for definition in definitions.values():
        lines.append("")
        lines.extend(definition)
    return lines


def _module_path(domain: str, type_name: str) -> Path:
    return Path(*_package_name(domain).split(".")) / _module_filename(type_name)


def _package_name(domain: str) -> str:
    parts = [part.lower() for part in re.split(r"[^A-Za-z0-9]+", domain) if part]
    return ".".join(parts) or "modelable"


def _module_filename(type_name: str) -> str:
    return f"{_snake_case(type_name)}.rs"


def _render_struct_definition(
    type_name: str,
    field_specs: list[_FieldSpec],
    *,
    extra_derives: list[str] | None = None,
    storage_gated: bool = False,
) -> list[str]:
    derives = ["Debug", "Clone", "PartialEq", "serde::Serialize", "serde::Deserialize"]
    if extra_derives:
        derives.extend(extra_derives)
    lines = []
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.append(f"#[derive({', '.join(derives)})]")
    lines.append(f"pub struct {type_name} {{")

    for spec in sorted(field_specs, key=lambda s: (s.optional, s.index)):
        for attr in spec.serde_attrs:
            lines.append(f"    {attr}")
        annotation = spec.annotation
        if spec.optional and not annotation.startswith("Option<"):
            annotation = f"Option<{annotation}>"
        lines.append(f"    pub {_field_name(spec.name)}: {annotation},")
    lines.append("}")
    if not field_specs:
        lines[-1] = f"pub struct {type_name} {{}}"
    return lines


def _field_name(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = text.strip("_").lower()
    return text or "field"


def _enum_member_name(value: str) -> str:
    name = _pascalize(value)
    if name and name[0].isdigit():
        name = f"_{name}"
    return name or "Unknown"


def _render_enum_definition(type_name: str, values: list[str]) -> list[str]:
    derives = ["Debug", "Clone", "PartialEq", "serde::Serialize", "serde::Deserialize"]
    lines = [
        f"#[derive({', '.join(derives)})]",
        f"pub enum {type_name} {{",
    ]
    for v in values:
        member = _enum_member_name(v)
        if member != v:
            lines.append(f'    #[serde(rename = "{v}")]')
        lines.append(f"    {member},")
    lines.append("}")
    return lines


def _field_specs_from_model_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    enum_info: dict[str, list[str]] | None = None,
    named_type_map: dict[str, str] | None = None,
) -> list[_FieldSpec]:
    specs: list[_FieldSpec] = []
    for index, field in enumerate(fields):
        shape = TypeShape.from_field_type(field.type, optional=field.optional)
        wire = field.wire_targets()
        annotation = _shape_annotation(
            shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            rust_hint=wire.get("rust"),
            enum_info=enum_info,
            named_type_map=named_type_map,
        )
        is_optional = shape.optional or shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, shape)
        # Optional arrays use Vec<T> + #[serde(default)] — Option<Vec<T>> forces unwrap before iteration.
        if is_optional and shape.kind == "array":
            is_optional = False
            serde_attrs = ["#[serde(default)]", *serde_attrs]
            annotation = _shape_base_annotation(
                shape,
                owner_type=owner_type,
                path=[*path, field.name],
                definitions=definitions,
                rust_hint=wire.get("rust"),
            )
        elif shape.optional:
            # Omittable field: skip during serialization when None.
            # Nullable-only fields must always be serialized (as null), so no skip attr.
            serde_attrs = ['#[serde(skip_serializing_if = "Option::is_none")]', *serde_attrs]
        specs.append(
            _FieldSpec(
                index=index, name=field.name, annotation=annotation, optional=is_optional, serde_attrs=serde_attrs
            )
        )
    return specs


def _field_specs_from_object_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    enum_info: dict[str, list[str]] | None = None,
) -> list[_FieldSpec]:
    specs: list[_FieldSpec] = []
    for index, field in enumerate(fields):
        wire = field.wire_targets or {}
        annotation = _shape_annotation(
            field.shape,
            owner_type=owner_type,
            path=[*path, field.name],
            definitions=definitions,
            rust_hint=wire.get("rust"),
            enum_info=enum_info,
        )
        default_none = field.optional or field.shape.optional or field.shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, field.shape)
        specs.append(
            _FieldSpec(
                index=index, name=field.name, annotation=annotation, optional=default_none, serde_attrs=serde_attrs
            )
        )
    return specs


def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
    clickhouse_hint=None,
    enum_info: dict[str, list[str]] | None = None,
    named_type_map: dict[str, str] | None = None,
) -> str:
    base = _shape_base_annotation(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        rust_hint=rust_hint,
        clickhouse_hint=clickhouse_hint,
        enum_info=enum_info,
        named_type_map=named_type_map,
    )
    if shape.optional or shape.nullable:
        return f"Option<{base}>"
    return base


def _shape_base_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
    clickhouse_hint=None,
    enum_info: dict[str, list[str]] | None = None,
    named_type_map: dict[str, str] | None = None,
) -> str:
    clickhouse_string = clickhouse_hint is not None and getattr(clickhouse_hint, "encoding", None) == "string"
    if shape.kind == "primitive":
        if rust_hint is not None and getattr(rust_hint, "type", None) and (shape.ref or "string") == "int":
            return rust_hint.type
        if shape.ref == "json" and clickhouse_string:
            return "String"
        return _primitive_to_rust(shape.ref or "string")
    if shape.kind == "decimal":
        return "String"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
            element,
            owner_type=owner_type,
            path=[*path, "Item"],
            definitions=definitions,
            rust_hint=rust_hint,
            enum_info=enum_info,
            named_type_map=named_type_map,
        )
        return f"Vec<{element_type}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        if value.kind == "primitive" and value.ref == "json" and clickhouse_string:
            return "String"
        value_type = _shape_annotation(
            value,
            owner_type=owner_type,
            path=[*path, "Value"],
            definitions=definitions,
            enum_info=enum_info,
            named_type_map=named_type_map,
        )
        return f"HashMap<String, {value_type}>"
    if shape.kind == "ref":
        return "String"
    if shape.kind == "enum":
        enum_type_name = _nested_type_name(owner_type, path)
        if enum_type_name not in definitions:
            definitions[enum_type_name] = _render_enum_definition(enum_type_name, list(shape.enum_values))
        if enum_info is not None and enum_type_name not in enum_info:
            enum_info[enum_type_name] = list(shape.enum_values)
        return enum_type_name
    if shape.kind == "named":
        if named_type_map is not None and shape.ref in named_type_map:
            return named_type_map[shape.ref]
        return _pascalize(shape.ref or "Named")
    if shape.kind == "object":
        type_name = _nested_type_name(owner_type, path)
        if type_name not in definitions:
            definitions[type_name] = _render_struct_definition(
                type_name,
                _field_specs_from_object_fields(
                    shape.fields,
                    owner_type=owner_type,
                    path=path,
                    definitions=definitions,
                    enum_info=enum_info,
                ),
            )
        return type_name
    return "String"


def _primitive_to_rust(kind: str) -> str:
    mapping = {
        "string": "String",
        "bool": "bool",
        "int": "i64",
        "float": "f64",
        "uuid": "uuid::Uuid",
        "timestamp": "String",
        "date": "String",
        "time": "String",
        "duration": "String",
        "binary": "Vec<u8>",
        "json": "serde_json::Value",
        "u8": "u8",
        "u16": "u16",
        "u32": "u32",
        "u64": "u64",
        "u128": "u128",
        "i8": "i8",
        "i16": "i16",
        "i32": "i32",
        "i64": "i64",
        "i128": "i128",
    }
    return mapping.get(kind, "String")


def _nested_type_name(owner_type: str, path: list[str]) -> str:
    suffix = "".join(_pascalize(part) for part in path)
    return f"{owner_type}{suffix}" if suffix else owner_type


def _resolve_projection_field_shape(field, projection: ProjectionVersion, mdl):
    if not isinstance(field.mapping, DirectMapping):
        return None
    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
    except ValueError:
        return None
    try:
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except LookupError:
        return None
    source_mv = resolved.version
    for src_field in source_mv.fields:
        if src_field.name == field.mapping.source_field:
            return TypeShape.from_field_type(src_field.type, optional=src_field.optional)
    return None


def _resolve_merged_projection_wire(field, projection: ProjectionVersion, mdl) -> dict:
    """Merge wire targets from the source entity field and the projection field.

    Projection-level annotations win; entity-level annotations provide defaults.
    This ensures e.g. @wire(rust.type: "u64") on an entity timestamp field is
    inherited by projection fields that map it, without repeating the hint.
    """
    if not isinstance(field.mapping, DirectMapping):
        return field.wire_targets()
    try:
        source_domain, source_model = projection.source.model.rsplit(".", 1)
        resolved = resolve_model_ref(mdl, f"{source_domain}.{source_model}", projection.source.version)
    except ValueError, LookupError:
        return field.wire_targets()
    for src_field in resolved.version.fields:
        if src_field.name == field.mapping.source_field:
            return {**src_field.wire_targets(), **field.wire_targets()}
    return field.wire_targets()
