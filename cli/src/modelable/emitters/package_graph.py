from __future__ import annotations

from dataclasses import dataclass, field

from modelable.parser.ir import (
    ArrayType,
    DomainDef,
    FieldType,
    MapType,
    MdlFile,
    NamedType,
    ObjectType,
    RefType,
)
from modelable.registry.resolver import AmbiguousSemanticTypeError, resolve_semantic_type_ref


@dataclass(frozen=True)
class PackageGraph:
    """Inter-package dependency edges for a workspace with ``package {}`` blocks.

    ``edges`` holds only direct dependencies -- a target's package manifest
    (e.g. Cargo path deps) is responsible for transitive resolution, the same
    way ``cargo`` resolves B's deps when A depends on B.
    """

    edges: dict[str, set[str]] = field(default_factory=dict)
    package_for_domain: dict[str, str] = field(default_factory=dict)


def build_package_graph(mdl: MdlFile) -> PackageGraph:
    if mdl.workspace is None or not mdl.workspace.packages:
        return PackageGraph()

    package_for_domain: dict[str, str] = {}
    for pkg in mdl.workspace.packages:
        for domain_name in pkg.include:
            package_for_domain[domain_name] = pkg.name

    edges: dict[str, set[str]] = {pkg.name: set() for pkg in mdl.workspace.packages}

    for domain in mdl.domains:
        current_pkg = package_for_domain.get(domain.name)
        if current_pkg is None:
            continue
        into = edges[current_pkg]

        for versions in domain.models.values():
            for version in versions:
                for model_field in version.fields:
                    _collect_field_deps(model_field.type, domain, mdl, package_for_domain, current_pkg, into)

        for semantic_decl in domain.semantic_types:
            _collect_field_deps(semantic_decl.underlying, domain, mdl, package_for_domain, current_pkg, into)

        for projection_versions in domain.projections.values():
            for pv in projection_versions:
                _add_dep_from_model_ref(pv.source.model, package_for_domain, current_pkg, into)
                for join in pv.joins:
                    _add_dep_from_model_ref(join.model, package_for_domain, current_pkg, into)

    _detect_cycles(edges)
    return PackageGraph(edges=edges, package_for_domain=package_for_domain)


def _collect_field_deps(
    field_type: FieldType,
    domain: DomainDef,
    mdl: MdlFile,
    package_for_domain: dict[str, str],
    current_pkg: str,
    into: set[str],
) -> None:
    if isinstance(field_type, RefType):
        _add_dep_from_model_ref(field_type.target, package_for_domain, current_pkg, into)
    elif isinstance(field_type, NamedType):
        ref_domain = _resolve_named_type_domain(field_type.name, domain.name, mdl)
        if ref_domain is not None:
            _add_dep(ref_domain, package_for_domain, current_pkg, into)
    elif isinstance(field_type, ArrayType):
        _collect_field_deps(field_type.item, domain, mdl, package_for_domain, current_pkg, into)
    elif isinstance(field_type, MapType):
        _collect_field_deps(field_type.key, domain, mdl, package_for_domain, current_pkg, into)
        _collect_field_deps(field_type.value, domain, mdl, package_for_domain, current_pkg, into)
    elif isinstance(field_type, ObjectType):
        for nested_field in field_type.fields:
            _collect_field_deps(nested_field.type, domain, mdl, package_for_domain, current_pkg, into)


def _resolve_named_type_domain(name: str, current_domain: str, mdl: MdlFile) -> str | None:
    """Mirrors emitters/rust.py::_resolve_named_type_map's resolution order:
    a same-named model in any domain wins first, then semantic types."""
    for candidate_domain in mdl.domains:
        if name in candidate_domain.models:
            return candidate_domain.name
    try:
        resolved_domain, _decl = resolve_semantic_type_ref(mdl, current_domain, name)
    except AmbiguousSemanticTypeError:
        return None
    except LookupError:
        return None
    return resolved_domain


def _add_dep_from_model_ref(
    model_ref: str,
    package_for_domain: dict[str, str],
    current_pkg: str,
    into: set[str],
) -> None:
    if "." not in model_ref:
        return
    ref_domain = model_ref.split(".", 1)[0]
    _add_dep(ref_domain, package_for_domain, current_pkg, into)


def _add_dep(ref_domain: str, package_for_domain: dict[str, str], current_pkg: str, into: set[str]) -> None:
    ref_pkg = package_for_domain.get(ref_domain)
    if ref_pkg is not None and ref_pkg != current_pkg:
        into.add(ref_pkg)


_WHITE, _GRAY, _BLACK = 0, 1, 2


def _detect_cycles(edges: dict[str, set[str]]) -> None:
    color = dict.fromkeys(edges, _WHITE)

    def dfs(node: str) -> None:
        color[node] = _GRAY
        for neighbor in edges.get(node, set()):
            if color.get(neighbor) == _GRAY:
                raise ValueError(f"package dependency cycle detected: {node} -> {neighbor}")
            if color.get(neighbor) == _WHITE:
                dfs(neighbor)
        color[node] = _BLACK

    for node in edges:
        if color[node] == _WHITE:
            dfs(node)
