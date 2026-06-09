from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import type_loss
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import DirectMapping, DomainDef, MdlFile, ModelVersion, ProjectionVersion
from modelable.registry.resolver import resolve_model_ref


@dataclass
class _FieldSpec:
    index: int
    name: str
    annotation: str
    optional: bool
    serde_attrs: list[str] = dc_field(default_factory=list)


def emit_rust(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    """Emit Rust source files for every model and projection version."""
    postgres_sources = _adapter_bound_sources(workspace.mdl, "postgres")
    clickhouse_sources = _adapter_bound_sources(workspace.mdl, "clickhouse")
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir))
        for projection_name, versions in domain.projections.items():
            for version in versions:
                source = version.source.model
                artifacts.append(_emit_projection(
                    domain, projection_name, version, out_dir, workspace.mdl,
                    sqlx_fromrow=source in postgres_sources,
                    clickhouse_row=source in clickhouse_sources,
                ))
    return artifacts


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


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    field_specs = _field_specs_from_model_fields(version.fields, owner_type=type_name, path=[], definitions=nested_definitions)

    needs_serde_with = _any_needs_serde_with(field_specs)
    lines = _header_lines(serde_with=needs_serde_with)
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
        warnings=[],
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
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    nested_definitions: dict[str, list[str]] = {}

    field_specs: list[_FieldSpec] = []
    warnings: list[str] = []
    for index, field in enumerate(version.fields):
        field_shape = _resolve_projection_field_shape(field, version, mdl)
        if field_shape is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
            field_specs.append(_FieldSpec(index=index, name=field.name, annotation="String", optional=False))
            continue
        wire = field.wire_targets()
        annotation = _shape_annotation(
            field_shape,
            owner_type=type_name,
            path=[field.name],
            definitions=nested_definitions,
            rust_hint=wire.get("rust"),
        )
        optional = field_shape.optional or field_shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, field_shape, clickhouse=clickhouse_row)
        field_specs.append(_FieldSpec(index=index, name=field.name, annotation=annotation, optional=optional, serde_attrs=serde_attrs))

    needs_serde_with = _any_needs_serde_with(field_specs)
    storage_gated = sqlx_fromrow or clickhouse_row
    extra_derives: list[str] = []
    if sqlx_fromrow:
        extra_derives.append("sqlx::FromRow")
    if clickhouse_row:
        extra_derives.append("clickhouse::Row")
    lines = _header_lines(serde_with=needs_serde_with, sqlx=sqlx_fromrow, clickhouse=clickhouse_row)
    lines.extend(_render_struct_definition(type_name, field_specs, extra_derives=extra_derives, storage_gated=storage_gated))
    lines.extend(_render_nested_definitions(nested_definitions))
    lines.extend(_emit_from_impl(type_name, domain.name, version, mdl, storage_gated=storage_gated))

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


def _emit_from_impl(
    proj_type_name: str,
    proj_domain: str,
    version: ProjectionVersion,
    mdl: MdlFile,
    *,
    storage_gated: bool = False,
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
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.append(f"impl From<{src_type_name}> for {proj_type_name} {{")
    lines.append(f"    fn from(src: {src_type_name}) -> Self {{")
    lines.append("        Self {")

    for proj_field in version.fields:
        rust_name = _field_name(proj_field.name)
        if isinstance(proj_field.mapping, DirectMapping):
            src_rust_name = _field_name(proj_field.mapping.source_field)
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
    return any(
        any("serde_with" in attr for attr in spec.serde_attrs)
        for spec in field_specs
    )


def _header_lines(*, serde_with: bool = False, sqlx: bool = False, clickhouse: bool = False) -> list[str]:
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


def _field_specs_from_model_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
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
        )
        default_none = shape.optional or shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, shape)
        specs.append(_FieldSpec(index=index, name=field.name, annotation=annotation, optional=default_none, serde_attrs=serde_attrs))
    return specs


def _field_specs_from_object_fields(
    fields,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
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
        )
        default_none = field.optional or field.shape.optional or field.shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, field.shape)
        specs.append(_FieldSpec(index=index, name=field.name, annotation=annotation, optional=default_none, serde_attrs=serde_attrs))
    return specs


def _shape_annotation(
    shape: TypeShape,
    *,
    owner_type: str,
    path: list[str],
    definitions: dict[str, list[str]],
    rust_hint=None,
) -> str:
    base = _shape_base_annotation(
        shape,
        owner_type=owner_type,
        path=path,
        definitions=definitions,
        rust_hint=rust_hint,
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
) -> str:
    if shape.kind == "primitive":
        if rust_hint is not None and getattr(rust_hint, "type", None) and (shape.ref or "string") == "int":
            return rust_hint.type
        return _primitive_to_rust(shape.ref or "string")
    if shape.kind == "decimal":
        return "String"
    if shape.kind == "array":
        element = shape.element or TypeShape(kind="primitive", ref="object")
        element_type = _shape_annotation(
            element,
            owner_type=owner_type,
            path=path + ["Item"],
            definitions=definitions,
        )
        return f"Vec<{element_type}>"
    if shape.kind == "map":
        value = shape.value or TypeShape(kind="primitive", ref="object")
        value_type = _shape_annotation(
            value,
            owner_type=owner_type,
            path=path + ["Value"],
            definitions=definitions,
        )
        return f"HashMap<String, {value_type}>"
    if shape.kind == "ref":
        return "String"
    if shape.kind == "enum":
        return "String"
    if shape.kind == "named":
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
        "uuid": "String",
        "timestamp": "String",
        "date": "String",
        "time": "String",
        "duration": "String",
        "binary": "Vec<u8>",
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
