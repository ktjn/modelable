from __future__ import annotations

import re
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import missing_metadata, type_loss
from modelable.parser.ir import (
    ArrayType,
    ComputedMapping,
    DecimalType,
    DirectMapping,
    DomainDef,
    EnumType,
    FieldDef,
    MapType,
    ModelVersion,
    NamedType,
    ObjectType,
    PrimitiveType,
    ProjectionVersion,
    RefType,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
)
from modelable.registry.resolver import ResolvedModelRef, resolve_model_ref


def emit_typescript(workspace: Workspace, out_dir: Path) -> list[EmittedArtifact]:
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for model_name, versions in domain.models.items():
            for version in versions:
                artifacts.append(_emit_model(domain, model_name, version, out_dir, workspace.mdl))
        for projection_name, versions in domain.projections.items():
            for version in versions:
                artifacts.append(_emit_projection(domain, projection_name, version, out_dir, workspace.mdl))
    return artifacts


def _artifact_id(domain: str, name: str, version: int) -> str:
    return f"{domain}.{name}.v{version}"


def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _stable_interface_name(domain: str, name: str, version: int) -> str:
    return f"{_pascalize(domain)}{_pascalize(name)}V{version}"


def _iface_to_artifact_id(iface_name: str) -> str:
    """Reverse _stable_interface_name heuristically to produce an artifact id like 'address.Address.v1'."""
    # Strip trailing Vn suffix
    m = re.match(r"^(.+?)V(\d+)$", iface_name)
    if not m:
        return iface_name.lower()
    body, ver = m.group(1), m.group(2)
    # Re-split PascalCase token pairs into domain + model
    parts = re.findall(r"[A-Z][a-z0-9]*", body)
    if len(parts) >= 2:
        domain = parts[0].lower()
        model = "".join(parts[1:])
        return f"{domain}.{model}.v{ver}"
    return f"{body.lower()}.v{ver}"


def _collect_ref_imports(field_type, mdl, resolved_refs: dict[str, str]) -> None:
    """Recursively collect resolved RefType targets into resolved_refs."""
    if isinstance(field_type, RefType):
        target = field_type.target
        if target not in resolved_refs:
            try:
                from modelable.parser.ir import VersionMin

                resolved: ResolvedModelRef = resolve_model_ref(mdl, target, VersionMin(min_inclusive=1))
                iface = _stable_interface_name(resolved.domain_name, resolved.model_name, resolved.version.version)
                resolved_refs[target] = iface
            except (LookupError, ValueError):
                pass
    elif isinstance(field_type, ArrayType):
        _collect_ref_imports(field_type.item, mdl, resolved_refs)
    elif isinstance(field_type, MapType):
        _collect_ref_imports(field_type.value, mdl, resolved_refs)
    elif isinstance(field_type, ObjectType):
        for f in field_type.fields:
            _collect_ref_imports(f.type, mdl, resolved_refs)


def _collect_named_imports(field_type, mdl, named_imports: dict[str, tuple[str, str]]) -> None:
    """Recursively resolve NamedType refs to (exported_alias, artifact_id) in named_imports."""
    if isinstance(field_type, NamedType):
        name = field_type.name
        if name not in named_imports and mdl is not None:
            for domain in mdl.domains:
                if name in domain.models:
                    versions = domain.models[name]
                    if versions:
                        latest = max(versions, key=lambda v: v.version)
                        aid = _artifact_id(domain.name, name, latest.version)
                        named_imports[name] = (name, aid)
                        return
    elif isinstance(field_type, ArrayType):
        _collect_named_imports(field_type.item, mdl, named_imports)
    elif isinstance(field_type, MapType):
        _collect_named_imports(field_type.value, mdl, named_imports)
    elif isinstance(field_type, ObjectType):
        for f in field_type.fields:
            _collect_named_imports(f.type, mdl, named_imports)


def _emit_model(domain: DomainDef, model_name: str, version: ModelVersion, out_dir: Path, mdl=None) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    interface_name = _stable_interface_name(domain.name, model_name, version.version)

    # Resolve ref<X> fields to stable interface names; collect imports.
    resolved_refs: dict[str, str] = {}  # ref target → stable interface name
    named_imports: dict[str, tuple[str, str]] = {}  # bare name → (stable iface name, artifact_id)
    if mdl is not None:
        for field in version.fields:
            _collect_ref_imports(field.type, mdl, resolved_refs)
            _collect_named_imports(field.type, mdl, named_imports)

    declaration_json_wire = version.wire_targets().get("json")
    field_case = declaration_json_wire.field_case if declaration_json_wire is not None else None

    import_lines: list[str] = []
    for iface in sorted(set(resolved_refs.values())):
        iface_id = _iface_to_artifact_id(iface)
        import_lines.append(f'import type {{ {iface} }} from "./{iface_id}";')
    for name in sorted(named_imports):
        iface, aid = named_imports[name]
        import_lines.append(f'import type {{ {iface} }} from "./{aid}";')

    meta_lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            model_name,
            version.version,
            version.model_kind.value,
            version.change_kind.value,
        )
    )
    body_lines: list[str] = []
    body_lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        if isinstance(field.type, NamedType) and field.type.name not in named_imports:
            warnings.append(missing_metadata(f"{domain.name}.{model_name}.{field.name}"))
        field_name = _apply_case(field.name, field_case) if field_case else field.name
        body_lines.append(
            f"  {field_name}{'?' if field.optional else ''}: {_type_to_ts(field.type, wire_targets=field.wire_targets(), resolved_refs=resolved_refs, named_imports=named_imports)};"
        )
    body_lines.append("}")
    body_lines.append(f"export type {model_name} = {interface_name};")

    all_lines = meta_lines + ([*import_lines, ""] if import_lines else []) + body_lines
    content = "\n".join(all_lines) + "\n"
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content=content,
        content_hash=compute_content_hash(content),
        warnings=warnings,
    )


def _emit_projection(
    domain: DomainDef,
    projection_name: str,
    version: ProjectionVersion,
    out_dir: Path,
    mdl,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    interface_name = _stable_interface_name(domain.name, projection_name, version.version)
    lines = _metadata_lines(
        _domain_metadata_entries(
            domain,
            projection_name,
            version.version,
            "projection",
            source=f"{version.source.model}@{_version_label(version.source.version)}",
            where=version.where,
            group_by=", ".join(version.group_by) if version.group_by else None,
        )
    )
    declaration_json_wire = version.wire_targets().get("json")
    field_case = declaration_json_wire.field_case if declaration_json_wire is not None else None
    lines.append(f"export interface {interface_name} {{")
    warnings: list[str] = []
    for field in version.fields:
        field_type = _resolve_projection_field_type(field, version, mdl)
        if field_type is None:
            warnings.append(type_loss(f"{domain.name}.{projection_name}.{field.name}"))
        elif isinstance(field_type, NamedType):
            warnings.append(missing_metadata(f"{domain.name}.{projection_name}.{field.name}"))
        field_name = _apply_case(field.name, field_case) if field_case else field.name
        lines.append(f"  {field_name}: {_type_to_ts(field_type, wire_targets=field.wire_targets())};")
    lines.append("}")
    lines.append(f"export type {projection_name} = {interface_name};")
    return EmittedArtifact(
        target="typescript",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / f"{artifact_id}.ts",
        content="\n".join(lines) + "\n",
        content_hash=compute_content_hash("\n".join(lines) + "\n"),
        warnings=warnings,
    )


def _metadata_lines(entries: list[str]) -> list[str]:
    lines = ["/**"]
    lines.extend(f" * {entry}" for entry in entries)
    lines.append(" */")
    return lines


def _domain_metadata_entries(
    domain: DomainDef,
    name: str,
    version: int,
    kind: str,
    change_kind: str | None = None,
    source: str | None = None,
    where: str | None = None,
    group_by: str | None = None,
) -> list[str]:
    entries = [f"@modelable domain: {domain.name}", f"@modelable name: {name}"]
    if domain.owner is not None:
        entries.append(f"@modelable owner: {domain.owner}")
    if domain.contact is not None:
        entries.append(f"@modelable contact: {domain.contact}")
    if domain.description is not None:
        entries.append(f"@modelable description: {domain.description}")
    if change_kind is not None:
        entries.append(f"@modelable kind: {kind}")
        entries.append(f"@modelable version: {version}")
        entries.append(f"@modelable changeKind: {change_kind}")
    else:
        entries.append(f"@modelable kind: {kind}")
        entries.append(f"@modelable version: {version}")
    if source is not None:
        entries.append(f"@modelable source: {source}")
    if where is not None:
        entries.append(f"@modelable where: {where}")
    if group_by is not None:
        entries.append(f"@modelable groupBy: {group_by}")
    return entries


def _resolve_projection_field_type(
    field: FieldDef,
    projection: ProjectionVersion,
    mdl,
):
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
            return src_field.type
    return None


def _version_label(version_spec) -> str:
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"


def _apply_case(value: str, case: str) -> str:
    """Convert an enum value string to the specified wire case convention."""
    words = re.sub(r"([a-z])([A-Z])", r"\1_\2", value)
    words_list = [w for w in re.split(r"[^A-Za-z0-9]+", words) if w]
    if not words_list:
        return value
    if case == "SCREAMING_SNAKE_CASE":
        return "_".join(w.upper() for w in words_list)
    if case == "snake_case":
        return "_".join(w.lower() for w in words_list)
    if case == "camelCase":
        return words_list[0].lower() + "".join(w.capitalize() for w in words_list[1:])
    if case == "PascalCase":
        return "".join(w.capitalize() for w in words_list)
    return value


def _type_to_ts(
    field_type,
    *,
    wire_targets: dict[str, object] | None = None,
    resolved_refs: dict[str, str] | None = None,
    named_imports: dict[str, tuple[str, str]] | None = None,
) -> str:
    json_wire = None
    if wire_targets is not None:
        json_wire = wire_targets.get("json")
    if isinstance(field_type, PrimitiveType):
        if (
            json_wire is not None
            and getattr(json_wire, "encoding", None) == "string"
            and field_type.kind in {"int", "float"}
        ):
            return "string"
        mapping = {
            "string": "string",
            "int": "number",
            "float": "number",
            "bool": "boolean",
            "date": "string",
            "time": "string",
            "timestamp": "string",
            "uuid": "string",
            "duration": "string",
            "binary": "string",
            "json": "unknown",
        }
        return mapping.get(field_type.kind, "unknown")
    if isinstance(field_type, DecimalType):
        return "string"
    if isinstance(field_type, ArrayType):
        item_ts = _type_to_ts(field_type.item, resolved_refs=resolved_refs, named_imports=named_imports)
        if isinstance(field_type.item, EnumType):
            return f"({item_ts})[]"
        return f"{item_ts}[]"
    if isinstance(field_type, MapType):
        return (
            f"Record<string, {_type_to_ts(field_type.value, resolved_refs=resolved_refs, named_imports=named_imports)}>"
        )
    if isinstance(field_type, RefType):
        if resolved_refs and field_type.target in resolved_refs:
            return resolved_refs[field_type.target]
        return "string"
    if isinstance(field_type, EnumType):
        case = getattr(json_wire, "case", None) if json_wire is not None else None
        overrides = getattr(json_wire, "overrides", {}) if json_wire is not None else {}
        wire_values = []
        for v in field_type.values:
            if v in overrides:
                wire_values.append(overrides[v])
            elif case:
                wire_values.append(_apply_case(v, case))
            else:
                wire_values.append(v)
        values = " | ".join(repr(v) for v in wire_values)
        return values or "string"
    if isinstance(field_type, ObjectType):
        inner = "; ".join(
            f"{field.name}{'?' if field.optional else ''}: {_type_to_ts(field.type, wire_targets=field.wire_targets(), resolved_refs=resolved_refs, named_imports=named_imports)}"
            for field in field_type.fields
        )
        return f"{{ {inner} }}"
    if isinstance(field_type, NamedType):
        if named_imports and field_type.name in named_imports:
            return named_imports[field_type.name][0]
        return field_type.name
    if field_type is None:
        return "unknown"
    if isinstance(field_type, ComputedMapping):
        return "unknown"
    return "unknown"
