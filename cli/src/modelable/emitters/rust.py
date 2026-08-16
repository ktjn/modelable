from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

from modelable.compiler.workspace import Workspace
from modelable.emitters.base import EmittedArtifact, compute_content_hash
from modelable.emitters.diagnostics import missing_metadata, type_loss
from modelable.emitters.naming import pascalize_titlecase as _pascalize
from modelable.emitters.naming import snake_case as _snake_case
from modelable.emitters.package_graph import PackageGraph, build_package_graph
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import (
    ArrayType,
    DecimalType,
    DirectMapping,
    DomainDef,
    FieldType,
    FixedBinaryType,
    MapType,
    MdlFile,
    ModelVersion,
    NamedType,
    PackageConfig,
    PrimitiveType,
    ProjectionVersion,
    SemanticTypeDecl,
    latest_semantic_types,
)
from modelable.registry.resolver import AmbiguousSemanticTypeError, resolve_model_ref, resolve_semantic_type_ref
from modelable.registry.signature import compute_version_signature


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
    # A projection may convert from a model owned by another domain in the flat crate.
    entries: list[tuple[str, str, str, dict[str, list[str]], str]] = []
    for art_id, info in enum_registry.items():
        entries.append((art_id, info["domain"], info["module_name"], info["enums"], info["kind"]))

    # Build: frozenset(raw_variants) -> [(artifact_id, domain, module_name, enum_type_name, kind)]
    extra: dict[str, list[str]] = {}  # artifact_id -> lines to append
    variant_map: dict[frozenset[str], list[tuple[str, str, str, str, str]]] = {}
    for art_id, domain, module_name, enums, kind in entries:
        for enum_type_name, raw_variants in enums.items():
            variant_map.setdefault(frozenset(raw_variants), []).append(
                (art_id, domain, module_name, enum_type_name, kind)
            )

    for variant_set, enum_list in variant_map.items():
        if len(enum_list) < 2:
            continue
        sorted_variants = sorted(variant_set)
        for src_art_id, src_domain, src_module, src_enum, _src_kind in enum_list:
            for tgt_art_id, tgt_domain, _tgt_module, tgt_enum, tgt_kind in enum_list:
                if (src_art_id == tgt_art_id and src_enum == tgt_enum) or tgt_kind == "model":
                    continue
                source_path = (
                    f"super::{_domain_mod_name(src_domain)}::{src_module}"
                    if src_domain != tgt_domain
                    else f"super::{src_module}"
                )
                lines: list[str] = [
                    "",
                    f"use {source_path}::{src_enum};",
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
            if not isinstance(artifact.content, str):
                raise TypeError(f"Rust artifact {artifact.artifact_id} content must be text")
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


def emit_rust(
    workspace: Workspace, out_dir: Path, *, registry_ids: dict[str, int] | None = None
) -> list[EmittedArtifact]:
    """Emit Rust source files for every model and projection version.

    When the workspace has no ``package {}`` blocks, this emits the flat
    single-crate layout unchanged. When packages are configured, each
    package's domains are emitted under their own ``src/`` tree with a
    generated Cargo.toml, lib.rs, and per-domain mod.rs.
    """
    package_graph = build_package_graph(workspace.mdl)
    if package_graph.package_for_domain:
        return _emit_rust_packages(workspace, out_dir, package_graph, registry_ids=registry_ids)
    return _emit_rust_single_crate(workspace, out_dir, registry_ids=registry_ids)


def _emit_rust_single_crate(
    workspace: Workspace, out_dir: Path, *, registry_ids: dict[str, int] | None = None
) -> list[EmittedArtifact]:
    postgres_sources = _adapter_bound_sources(workspace.mdl, "postgres")
    clickhouse_sources = _adapter_bound_sources(workspace.mdl, "clickhouse")
    enum_registry: dict[str, dict] = {}
    artifacts: list[EmittedArtifact] = []
    for domain in workspace.mdl.domains:
        for decl in latest_semantic_types(domain):
            qualified_name = f"{domain.name}.{decl.name}"
            allocated_id = (registry_ids or {}).get(qualified_name) if decl.registry else None
            artifacts.append(_emit_semantic_type(domain, decl, out_dir, allocated_id=allocated_id))
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


def _emit_rust_packages(
    workspace: Workspace,
    out_dir: Path,
    package_graph: PackageGraph,
    *,
    registry_ids: dict[str, int] | None = None,
) -> list[EmittedArtifact]:
    mdl = workspace.mdl
    assert mdl.workspace is not None
    postgres_sources = _adapter_bound_sources(mdl, "postgres")
    clickhouse_sources = _adapter_bound_sources(mdl, "clickhouse")
    package_for_domain = package_graph.package_for_domain
    domains_by_name = {domain.name: domain for domain in mdl.domains}

    enum_registry: dict[str, dict] = {}
    artifacts: list[EmittedArtifact] = []
    domain_modules: dict[str, dict[str, list[str]]] = {}  # pkg -> domain -> [module names]

    for pkg in mdl.workspace.packages:
        pkg_dir = out_dir / pkg.name / "src"
        for domain_name in pkg.include:
            domain = domains_by_name.get(domain_name)
            if domain is None:
                continue
            modules: list[str] = []
            for decl in latest_semantic_types(domain):
                qualified_name = f"{domain.name}.{decl.name}"
                allocated_id = (registry_ids or {}).get(qualified_name) if decl.registry else None
                artifact = _emit_semantic_type(
                    domain,
                    decl,
                    pkg_dir,
                    allocated_id=allocated_id,
                    mdl=mdl,
                    current_pkg=pkg.name,
                    package_for_domain=package_for_domain,
                )
                artifacts.append(artifact)
                modules.append(artifact.path.stem)
            for model_name, versions in domain.models.items():
                for version in versions:
                    artifact = _emit_model(
                        domain,
                        model_name,
                        version,
                        pkg_dir,
                        enum_registry=enum_registry,
                        mdl=mdl,
                        current_pkg=pkg.name,
                        package_for_domain=package_for_domain,
                    )
                    artifacts.append(artifact)
                    modules.append(artifact.path.stem)
            for projection_name, versions in domain.projections.items():
                for version in versions:
                    source = version.source.model
                    artifact = _emit_projection(
                        domain,
                        projection_name,
                        version,
                        pkg_dir,
                        mdl,
                        sqlx_fromrow=source in postgres_sources,
                        clickhouse_row=source in clickhouse_sources,
                        enum_registry=enum_registry,
                        current_pkg=pkg.name,
                        package_for_domain=package_for_domain,
                    )
                    artifacts.append(artifact)
                    modules.append(artifact.path.stem)
            domain_modules.setdefault(pkg.name, {})[domain.name] = sorted(modules)

    artifacts = _append_cross_enum_from_impls(artifacts, enum_registry)

    for pkg in mdl.workspace.packages:
        pkg_dir = out_dir / pkg.name
        pkg_domains = domain_modules.get(pkg.name, {})
        if not pkg_domains:
            continue
        for domain_name, modules in pkg_domains.items():
            artifacts.append(_emit_domain_mod_rs(pkg.name, domain_name, modules, pkg_dir / "src"))
        artifacts.append(_emit_lib_rs(pkg.name, sorted(pkg_domains), pkg_dir / "src"))
        deps = sorted(package_graph.edges.get(pkg.name, set()))
        pkg_artifacts = [a for a in artifacts if a.path.is_relative_to(pkg_dir)]
        artifacts.append(_emit_cargo_toml(pkg, deps, pkg_artifacts, pkg_dir))

    return artifacts


def _emit_domain_mod_rs(pkg_name: str, domain_name: str, modules: list[str], src_dir: Path) -> EmittedArtifact:
    domain_mod = _domain_mod_name(domain_name)
    lines = ["// @generated by Modelable"]
    lines.extend(f"pub mod {module};" for module in modules)
    text = "\n".join(lines) + "\n"
    artifact_id = f"{pkg_name}.{domain_name}.mod"
    return EmittedArtifact(
        target="rust",
        ref=f"package:{pkg_name}#{domain_name}",
        artifact_id=artifact_id,
        path=src_dir / domain_mod / "mod.rs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _emit_lib_rs(pkg_name: str, domains: list[str], src_dir: Path) -> EmittedArtifact:
    lines = ["// @generated by Modelable"]
    lines.extend(f"pub mod {_domain_mod_name(domain)};" for domain in domains)
    text = "\n".join(lines) + "\n"
    artifact_id = f"{pkg_name}.lib"
    return EmittedArtifact(
        target="rust",
        ref=f"package:{pkg_name}#lib",
        artifact_id=artifact_id,
        path=src_dir / "lib.rs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _emit_cargo_toml(
    pkg: PackageConfig, deps: list[str], pkg_artifacts: list[EmittedArtifact], pkg_dir: Path
) -> EmittedArtifact:
    needs_uuid = any("requires: uuid" in _artifact_text(a) for a in pkg_artifacts)
    needs_serde_json = any("requires: serde_json" in _artifact_text(a) for a in pkg_artifacts)
    needs_serde_with = any("requires: serde_with" in _artifact_text(a) for a in pkg_artifacts)
    needs_sqlx = any("requires: sqlx" in _artifact_text(a) for a in pkg_artifacts)
    needs_clickhouse = any("requires: clickhouse" in _artifact_text(a) for a in pkg_artifacts)
    needs_chrono = any("requires: chrono" in _artifact_text(a) for a in pkg_artifacts)

    lines = [
        "[package]",
        f'name = "{pkg.name}"',
        'version = "0.1.0"',
        'edition = "2021"',
        "",
        "[dependencies]",
        'serde = { version = "1", features = ["derive"] }',
    ]
    if needs_uuid:
        lines.append('uuid = { version = "1", features = ["v4", "serde"] }')
    if needs_serde_json:
        lines.append('serde_json = "1"')
    if needs_serde_with:
        lines.append('serde_with = "3"')
    if needs_sqlx:
        lines.append('sqlx = "0.8"')
    if needs_clickhouse:
        lines.append('clickhouse = "0.13"')
    if needs_chrono:
        lines.append('chrono = { version = "0.4", features = ["serde"] }')
    for dep in deps:
        # Cargo dependency table keys can contain hyphens directly; the key IS
        # the package name unless a `package = "..."` override is given, and
        # cargo maps it to the underscored `use` identifier automatically.
        lines.append(f'{dep} = {{ path = "../{dep}" }}')

    text = "\n".join(lines) + "\n"
    artifact_id = f"{pkg.name}.Cargo.toml"
    return EmittedArtifact(
        target="rust",
        ref=f"package:{pkg.name}#manifest",
        artifact_id=artifact_id,
        path=pkg_dir / "Cargo.toml",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _artifact_text(artifact: EmittedArtifact) -> str:
    return artifact.content if isinstance(artifact.content, str) else ""


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


def _collect_named_type_refs_from_shape(shape: TypeShape, result: set[str]) -> None:
    """Recursively collect NamedType references from a resolved TypeShape."""
    if shape.kind == "named" and shape.ref:
        result.add(shape.ref)
    elif shape.kind == "array" and shape.element is not None:
        _collect_named_type_refs_from_shape(shape.element, result)
    elif shape.kind == "map" and shape.value is not None:
        _collect_named_type_refs_from_shape(shape.value, result)


def _crate_ident(package_name: str) -> str:
    """Rust `use` paths can't contain hyphens; Cargo maps a hyphenated package
    name to this identifier automatically."""
    return package_name.replace("-", "_")


def _domain_mod_name(domain: str) -> str:
    return _snake_case(domain)


def _import_prefix(
    target_domain: str,
    current_domain: str | None,
    current_pkg: str | None,
    package_for_domain: dict[str, str] | None,
) -> str:
    """Choose the `use` path prefix for a reference to `target_domain`'s module.

    Single-crate mode (package_for_domain is None) always uses `super::`,
    preserving existing behavior exactly. In package mode: same domain still
    uses `super::` (sibling file within the same domain directory); same
    package but a different domain uses `crate::{domain}::`; a different
    package uses `{other_pkg}::{domain}::`.
    """
    if package_for_domain is None or target_domain == current_domain:
        return "super"
    domain_mod = _domain_mod_name(target_domain)
    target_pkg = package_for_domain.get(target_domain)
    if target_pkg is None or target_pkg == current_pkg:
        return f"crate::{domain_mod}"
    return f"{_crate_ident(target_pkg)}::{domain_mod}"


def _domain_for_named_type(name: str, current_domain: str | None, mdl: MdlFile) -> str | None:
    """Which domain `name` resolves to: a same-named model in any domain wins
    first (matching _resolve_named_type_map's model-match branch), then a
    semantic type declaration (matching its semantic-match branch)."""
    for domain in mdl.domains:
        if name in domain.models:
            return domain.name
    try:
        resolved_domain, _decl = resolve_semantic_type_ref(mdl, current_domain or "", name)
    except AmbiguousSemanticTypeError, LookupError:
        return None
    return resolved_domain


def _resolve_named_type_map(
    named_refs: set,
    mdl: MdlFile | None,
    *,
    current_domain: str | None = None,
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """Resolve NamedType references to Rust type names from the workspace.

    Returns (name -> rust_type_name, list of use statements).
    """
    if not named_refs or mdl is None:
        return {}, []
    resolved_map: dict[str, str] = {}
    use_statements: list[str] = []
    for name in sorted(named_refs):
        resolved = False
        for domain in mdl.domains:
            if name in domain.models:
                versions = domain.models[name]
                if versions:
                    latest = versions[-1]
                    rust_name = _stable_type_name(domain.name, name, latest.version)
                    module = _snake_case(rust_name)
                    prefix = _import_prefix(domain.name, current_domain, current_pkg, package_for_domain)
                    resolved_map[name] = rust_name
                    use_statements.append(f"use {prefix}::{module}::{rust_name};")
                    resolved = True
                    break
        if resolved:
            continue
        try:
            domain_name, semantic_decl = resolve_semantic_type_ref(mdl, current_domain or "", name)
        except AmbiguousSemanticTypeError:
            raise
        except LookupError:
            continue
        module = _snake_case(semantic_decl.name)
        prefix = _import_prefix(domain_name, current_domain, current_pkg, package_for_domain)
        resolved_map[name] = semantic_decl.name
        use_statements.append(f"use {prefix}::{module}::{semantic_decl.name};")
    return resolved_map, use_statements


def _rust_type_for_semantic_underlying(
    underlying: FieldType,
    *,
    mdl: MdlFile | None = None,
    current_domain: str | None = None,
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> tuple[str, list[str], str | None]:
    """Resolve a semantic type's underlying FieldType to (rust_type, derive_traits, use_statement).

    derive_traits excludes Copy/Eq/Hash for underlying Rust types that don't
    support them (String, Vec<u8>, f64, serde_json::Value).
    """
    if isinstance(underlying, PrimitiveType):
        rust_type = _primitive_to_rust(underlying.kind)
        if rust_type == "f64":
            return rust_type, ["Debug", "Clone", "Copy", "PartialEq"], None
        if rust_type in ("String", "serde_json::Value"):
            return rust_type, ["Debug", "Clone", "PartialEq"], None
        return rust_type, ["Debug", "Clone", "Copy", "PartialEq", "Eq", "Hash"], None
    if isinstance(underlying, DecimalType):
        return "String", ["Debug", "Clone", "PartialEq"], None
    if isinstance(underlying, FixedBinaryType):
        rust_type = f"[u8; {underlying.length}]"
        return rust_type, ["Debug", "Clone", "Copy", "PartialEq", "Eq", "Hash"], None
    if isinstance(underlying, NamedType):
        module = _snake_case(underlying.name)
        prefix = "super"
        if mdl is not None:
            target_domain = _domain_for_named_type(underlying.name, current_domain, mdl)
            if target_domain is not None:
                prefix = _import_prefix(target_domain, current_domain, current_pkg, package_for_domain)
        return underlying.name, ["Debug", "Clone", "PartialEq"], f"use {prefix}::{module}::{underlying.name};"
    # Not reachable once validation has run; keep a safe, non-crashing fallback.
    return "String", ["Debug", "Clone", "PartialEq"], None


def _render_registry_id_impl(type_name: str, allocated_id: int) -> list[str]:
    _validate_rust_u32_constant("REGISTRY_ID", allocated_id, minimum=1)
    return [
        "",
        f"impl {type_name} {{",
        f"    pub const REGISTRY_ID: u32 = {allocated_id};",
        "}",
    ]


def _validate_rust_u32_constant(name: str, value: int, *, minimum: int) -> None:
    maximum = 2**32 - 1
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _signature_bytes(signature: str) -> bytes:
    if re.fullmatch(r"[0-9a-fA-F]{64}", signature) is None:
        raise ValueError("canonical Modelable signature must contain exactly 64 hexadecimal characters")
    return bytes.fromhex(signature)


def _render_schema_identity_impl(
    type_name: str,
    version: int,
    signature: str,
    *,
    storage_gated: bool = False,
) -> list[str]:
    _validate_rust_u32_constant("SCHEMA_VERSION", version, minimum=0)
    values = _signature_bytes(signature)
    lines = [""]
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.extend(
        [
            f"impl {type_name} {{",
            f"    pub const SCHEMA_VERSION: u32 = {version};",
            "    pub const SCHEMA_CONTENT_SIGNATURE: [u8; 32] = [",
        ]
    )
    for offset in range(0, len(values), 8):
        row = ", ".join(f"0x{value:02x}" for value in values[offset : offset + 8])
        lines.append(f"        {row},")
    lines.extend(["    ];", "}"])
    return lines


def _emit_semantic_type(
    domain: DomainDef,
    decl: SemanticTypeDecl,
    out_dir: Path,
    *,
    allocated_id: int | None = None,
    mdl: MdlFile | None = None,
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> EmittedArtifact:
    artifact_id = f"{domain.name}.{decl.name}"
    struct_name = decl.name
    rust_type, base_derives, use_statement = _rust_type_for_semantic_underlying(
        decl.underlying,
        mdl=mdl,
        current_domain=domain.name,
        current_pkg=current_pkg,
        package_for_domain=package_for_domain,
    )
    derives = [*base_derives, "serde::Serialize", "serde::Deserialize"]

    needs_uuid = rust_type == "uuid::Uuid"
    needs_serde_json = rust_type == "serde_json::Value"
    needs_chrono = rust_type.startswith("chrono::")
    lines = _header_lines(
        uuid=needs_uuid,
        serde_json=needs_serde_json,
        chrono=needs_chrono,
        extra_uses=[use_statement] if use_statement else None,
    )
    if allocated_id is not None:
        lines.append(f"/// registry id: {allocated_id}")
    lines.append(f"#[derive({', '.join(derives)})]")
    lines.append("#[serde(transparent)]")
    lines.append(f"pub struct {struct_name}(pub {rust_type});")
    if allocated_id is not None:
        lines.extend(_render_registry_id_impl(struct_name, allocated_id))
    lines.append("")
    lines.append(f"impl From<{rust_type}> for {struct_name} {{")
    lines.append(f"    fn from(value: {rust_type}) -> Self {{")
    lines.append(f"        {struct_name}(value)")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append(f"impl From<{struct_name}> for {rust_type} {{")
    lines.append(f"    fn from(value: {struct_name}) -> Self {{")
    lines.append("        value.0")
    lines.append("    }")
    lines.append("}")
    lines.append("")
    lines.append(f"impl std::ops::Deref for {struct_name} {{")
    lines.append(f"    type Target = {rust_type};")
    lines.append("")
    lines.append(f"    fn deref(&self) -> &{rust_type} {{")
    lines.append("        &self.0")
    lines.append("    }")
    lines.append("}")

    text = "\n".join(lines) + "\n"
    return EmittedArtifact(
        target="rust",
        ref=artifact_id,
        artifact_id=artifact_id,
        path=out_dir / _snake_case(domain.name) / f"{_snake_case(decl.name)}.rs",
        content=text,
        content_hash=compute_content_hash(text),
        warnings=[],
    )


def _emit_model(
    domain: DomainDef,
    model_name: str,
    version: ModelVersion,
    out_dir: Path,
    *,
    enum_registry: dict[str, dict] | None = None,
    mdl: MdlFile | None = None,
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, model_name, version.version)
    type_name = _stable_type_name(domain.name, model_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    local_enum_info: dict[str, list[str]] = {}

    # Resolve NamedType references from the workspace
    named_refs: set[str] = set()
    for field in version.fields:
        _collect_named_type_refs(field.type, named_refs)
    named_type_map, use_statements = _resolve_named_type_map(
        named_refs,
        mdl,
        current_domain=domain.name,
        current_pkg=current_pkg,
        package_for_domain=package_for_domain,
    )

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
    needs_hashmap = _any_needs_hashmap(field_specs, nested_definitions)
    needs_chrono = _any_needs_chrono(field_specs)
    lines = _header_lines(
        serde_with=needs_serde_with,
        uuid=needs_uuid,
        serde_json=needs_serde_json,
        hashmap=needs_hashmap,
        chrono=needs_chrono,
        extra_uses=use_statements,
    )
    if _any_needs_duration_serde(field_specs):
        lines.extend(_render_duration_serde_module())
    lines.extend(_render_struct_definition(type_name, field_specs))
    lines.extend(
        _render_schema_identity_impl(
            type_name,
            version.version,
            compute_version_signature(domain.name, model_name, version),
        )
    )
    lines.extend(_render_nested_definitions(nested_definitions))

    text = "\n".join(lines) + "\n"
    module_path = (
        Path(_domain_mod_name(domain.name)) / _module_filename(type_name)
        if package_for_domain is not None
        else _module_path(domain.name, type_name)
    )
    return EmittedArtifact(
        target="rust",
        ref=f"{domain.name}.{model_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / module_path,
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
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> EmittedArtifact:
    artifact_id = _artifact_id(domain.name, projection_name, version.version)
    type_name = _stable_type_name(domain.name, projection_name, version.version)
    nested_definitions: dict[str, list[str]] = {}
    local_enum_info: dict[str, list[str]] = {}

    field_shapes: dict[str, TypeShape | None] = {
        field.name: _resolve_projection_field_shape(field, version, mdl) for field in version.fields
    }
    named_refs: set[str] = set()
    for field_shape in field_shapes.values():
        if field_shape is not None:
            _collect_named_type_refs_from_shape(field_shape, named_refs)
    named_type_map, use_statements = _resolve_named_type_map(
        named_refs,
        mdl,
        current_domain=domain.name,
        current_pkg=current_pkg,
        package_for_domain=package_for_domain,
    )

    field_specs: list[_FieldSpec] = []
    warnings: list[str] = []
    for index, field in enumerate(version.fields):
        field_shape = field_shapes[field.name]
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
                named_type_map=named_type_map,
            )
        optional = field_shape.optional or field_shape.nullable
        serde_attrs = _serde_attrs_for_field(wire, field_shape, clickhouse=clickhouse_row)
        if field_shape.optional and not clickhouse_row:
            serde_attrs = ["#[serde(default)]", '#[serde(skip_serializing_if = "Option::is_none")]', *serde_attrs]
        field_specs.append(
            _FieldSpec(index=index, name=field.name, annotation=annotation, optional=optional, serde_attrs=serde_attrs)
        )

    needs_serde_with = _any_needs_serde_with(field_specs)
    needs_uuid = _any_needs_uuid(field_specs)
    needs_serde_json = _any_needs_serde_json(field_specs) or any(
        _projection_field_is_json_passthrough_to_string(f, version, mdl) for f in version.fields
    )
    needs_hashmap = _any_needs_hashmap(field_specs, nested_definitions)
    needs_chrono = _any_needs_chrono(field_specs)
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
        hashmap=needs_hashmap,
        chrono=needs_chrono,
        extra_uses=use_statements,
    )
    if _any_needs_duration_serde(field_specs):
        lines.extend(_render_duration_serde_module())
    lines.extend(
        _render_struct_definition(type_name, field_specs, extra_derives=extra_derives, storage_gated=storage_gated)
    )
    lines.extend(
        _render_schema_identity_impl(
            type_name,
            version.version,
            compute_version_signature(domain.name, projection_name, version),
            storage_gated=storage_gated,
        )
    )
    lines.extend(_render_nested_definitions(nested_definitions))
    lines.extend(
        _emit_from_impl(
            type_name,
            domain.name,
            version,
            mdl,
            storage_gated=storage_gated,
            clickhouse_row=clickhouse_row,
            current_pkg=current_pkg,
            package_for_domain=package_for_domain,
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
    module_path = (
        Path(_domain_mod_name(domain.name)) / _module_filename(type_name)
        if package_for_domain is not None
        else _module_path(domain.name, type_name)
    )
    return EmittedArtifact(
        target="rust",
        ref=f"{domain.name}.{projection_name}@{version.version}",
        artifact_id=artifact_id,
        path=out_dir / module_path,
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
    current_pkg: str | None = None,
    package_for_domain: dict[str, str] | None = None,
) -> list[str]:
    """Emit impl From<SourceModel> for Projection.

    Only generated for single-source projections (no joins). In single-crate
    mode (package_for_domain is None) this is still restricted to a source
    model in the same domain as the projection, preserving prior behavior
    exactly. In package mode, a cross-domain source is allowed as long as both
    domains are assigned to a package, and the `use` path is computed via
    _import_prefix so it resolves whether the source lives in the same
    package (crate::domain::) or a different one (other_pkg::domain::).
    """
    if version.joins:
        return []

    try:
        src_domain_str, src_model_name = version.source.model.rsplit(".", 1)
    except ValueError:
        return []

    if package_for_domain is None:
        # Only generate when source and projection share the same domain (super:: path is valid)
        if src_domain_str != proj_domain:
            return []
    elif src_domain_str not in package_for_domain or proj_domain not in package_for_domain:
        return []

    try:
        resolved = resolve_model_ref(mdl, version.source.model, version.source.version)
    except LookupError:
        return []

    src_version = resolved.version
    src_type_name = _stable_type_name(src_domain_str, src_model_name, src_version.version)
    src_module = _snake_case(src_type_name)
    prefix = _import_prefix(src_domain_str, proj_domain, current_pkg, package_for_domain)

    lines: list[str] = [""]
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    lines.append(f"use {prefix}::{src_module}::{src_type_name};")
    if clickhouse_row:
        for proj_field in version.fields:
            if not isinstance(proj_field.mapping, DirectMapping):
                continue
            field_shape = _resolve_projection_field_shape(proj_field, version, mdl)
            if field_shape is not None and field_shape.kind == "enum":
                enum_type = _nested_type_name(src_type_name, [proj_field.mapping.source_field])
                if storage_gated:
                    lines.append('#[cfg(feature = "storage")]')
                lines.append(f"use {prefix}::{src_module}::{enum_type};")
    if storage_gated:
        lines.append('#[cfg(feature = "storage")]')
    # Direct-mapped fields always go through `.into()` below, which is a no-op
    # (and a clippy lint) when the source and projected field share a type.
    lines.append("#[allow(clippy::useless_conversion)]")
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
    temporal = (
        shape.ref if shape.kind == "primitive" and shape.ref in {"date", "time", "timestamp", "duration"} else None
    )
    if temporal == "duration" and (rust_hint is None or getattr(rust_hint, "type", None) is None):
        module = "modelable_duration::option" if shape.optional or shape.nullable else "modelable_duration"
        return [f'#[serde(with = "{module}")]']
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


def _any_needs_chrono(field_specs: list[_FieldSpec]) -> bool:
    return any(
        "chrono::" in spec.annotation or "modelable_duration" in attr
        for spec in field_specs
        for attr in spec.serde_attrs
    )


def _any_needs_duration_serde(field_specs: list[_FieldSpec]) -> bool:
    return any("modelable_duration" in attr for spec in field_specs for attr in spec.serde_attrs)


def _render_duration_serde_module() -> list[str]:
    """Render a dependency-light ISO-8601 serde adapter for chrono durations."""
    return [
        "",
        "mod modelable_duration {",
        "    use serde::{Deserialize, Deserializer, Serializer};",
        "",
        "    pub fn serialize<S>(value: &chrono::Duration, serializer: S) -> Result<S::Ok, S::Error>",
        "    where",
        "        S: Serializer,",
        "    {",
        "        serializer.serialize_str(&value.to_string())",
        "    }",
        "",
        "    pub fn deserialize<'de, D>(deserializer: D) -> Result<chrono::Duration, D::Error>",
        "    where",
        "        D: Deserializer<'de>,",
        "    {",
        "        let value = String::deserialize(deserializer)?;",
        "        parse(&value).map_err(serde::de::Error::custom)",
        "    }",
        "",
        "    pub mod option {",
        "        use super::parse;",
        "        use serde::{Deserialize, Deserializer, Serialize, Serializer};",
        "",
        "        pub fn serialize<S>(value: &Option<chrono::Duration>, serializer: S) -> Result<S::Ok, S::Error>",
        "        where",
        "            S: Serializer,",
        "        {",
        "            value.as_ref().map(ToString::to_string).serialize(serializer)",
        "        }",
        "",
        "        pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<chrono::Duration>, D::Error>",
        "        where",
        "            D: Deserializer<'de>,",
        "        {",
        "            Option::<String>::deserialize(deserializer)?",
        "                .map(|value| parse(&value).map_err(serde::de::Error::custom))",
        "                .transpose()",
        "        }",
        "    }",
        "",
        "    fn parse(value: &str) -> Result<chrono::Duration, String> {",
        "        let (negative, body) = value.strip_prefix('-').map_or((false, value), |rest| (true, rest));",
        "        let body = body.strip_prefix('P').ok_or_else(|| \"duration must start with P\".to_string())?;",
        "        let mut total_nanos: i128 = 0;",
        "        let mut number = String::new();",
        "        let mut in_time = false;",
        "        for ch in body.chars() {",
        "            if ch.is_ascii_digit() || ch == '.' {",
        "                number.push(ch);",
        "                continue;",
        "            }",
        "            if ch == 'T' && number.is_empty() && !in_time {",
        "                in_time = true;",
        "                continue;",
        "            }",
        "            if number.is_empty() || (!in_time && ch != 'D') || (in_time && !matches!(ch, 'H' | 'M' | 'S')) {",
        '                return Err(format!("unsupported ISO-8601 duration component: {ch}"));',
        "            }",
        "            let unit_nanos: i128 = match ch { 'D' => 86_400_000_000_000, 'H' => 3_600_000_000_000, 'M' => 60_000_000_000, 'S' => 1_000_000_000, _ => unreachable!() };",
        "            let component = if ch == 'S' && number.contains('.') {",
        "                let (whole, fraction) = number.split_once('.').unwrap();",
        '                let nanos = format!("{fraction:0<9}").chars().take(9).collect::<String>().parse::<i128>().map_err(|_| "invalid duration fraction".to_string())?;',
        '                whole.parse::<i128>().map_err(|_| "invalid duration seconds".to_string())? * unit_nanos + nanos',
        "            } else {",
        '                number.parse::<i128>().map_err(|_| "invalid duration component".to_string())? * unit_nanos',
        "            };",
        '            total_nanos = total_nanos.checked_add(component).ok_or_else(|| "duration is out of range".to_string())?;',
        "            number.clear();",
        "        }",
        "        if !number.is_empty() || total_nanos == 0 && body.is_empty() {",
        '            return Err("duration has an incomplete component".to_string());',
        "        }",
        "        let total_nanos = if negative { -total_nanos } else { total_nanos };",
        '        let total_nanos = i64::try_from(total_nanos).map_err(|_| "duration is out of range".to_string())?;',
        "        Ok(chrono::Duration::nanoseconds(total_nanos))",
        "    }",
        "}",
    ]


def _any_needs_serde_json(field_specs: list[_FieldSpec]) -> bool:
    return any("serde_json::Value" in spec.annotation for spec in field_specs)


def _any_needs_hashmap(field_specs: list[_FieldSpec], nested_definitions: dict[str, list[str]] | None = None) -> bool:
    if any("HashMap<" in spec.annotation for spec in field_specs):
        return True
    if nested_definitions:
        for lines in nested_definitions.values():
            if any("HashMap<" in line for line in lines):
                return True
    return False


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
    hashmap: bool = False,
    chrono: bool = False,
    extra_uses: list[str] | None = None,
) -> list[str]:
    lines = ["// @generated by Modelable"]
    if hashmap:
        lines.append("use std::collections::HashMap;")
    lines.append("")
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
    if chrono:
        lines.insert(1, "// requires: chrono (https://docs.rs/chrono)")
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
                named_type_map=named_type_map,
            )
        elif is_optional:
            serde_attrs = ["#[serde(default)]", *serde_attrs]
        if shape.optional and shape.kind != "array":
            # Omittable field: skip during serialization when None.
            # Nullable-only fields must always be serialized (as null), so no skip attr.
            serde_attrs = ["#[serde(default)]", '#[serde(skip_serializing_if = "Option::is_none")]', *serde_attrs]
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
        if default_none:
            serde_attrs = ["#[serde(default)]", *serde_attrs]
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
        if rust_hint is not None and getattr(rust_hint, "type", None):
            return rust_hint.type
        if shape.ref == "json" and clickhouse_string:
            return "String"
        return _primitive_to_rust(shape.ref or "string")
    if shape.kind == "decimal":
        return "String"
    if shape.kind == "fixed_binary":
        return f"[u8; {shape.length}]"
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
        "timestamp": "chrono::DateTime<chrono::Utc>",
        "date": "chrono::NaiveDate",
        "time": "chrono::NaiveTime",
        "duration": "chrono::Duration",
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
