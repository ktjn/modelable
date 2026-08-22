from __future__ import annotations

from dataclasses import dataclass

from modelable.parser.ir import (
    DomainDef,
    MdlFile,
    ModelVersion,
    ProjectionVersion,
    RefType,
    SemanticTypeDecl,
    VersionExact,
    VersionMin,
    VersionPinned,
    VersionRange,
    VersionSpec,
    latest_semantic_types,
)
from modelable.registry.signature import compute_version_signature


@dataclass(frozen=True)
class ResolvedModelRef:
    domain_name: str
    model_name: str
    version: ModelVersion | ProjectionVersion


def resolve_model_ref(
    mdl: MdlFile,
    model_ref: str,
    version_spec: VersionSpec | int,
) -> ResolvedModelRef:
    """Resolve a model reference to a concrete published model version."""
    domain_name, model_name = _split_model_ref(model_ref)
    versions = _find_model_versions(mdl, domain_name, model_name)
    if not versions:
        raise LookupError(f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}")

    matching = [version for version in versions if _matches(version, version_spec, domain_name, model_name)]
    if not matching:
        raise LookupError(f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}")

    selected = max(matching, key=lambda version: version.version)

    # If using a range or min spec, ensure no breaking change exists between
    # the requested start and the selected version.
    if isinstance(version_spec, (VersionRange, VersionMin)):
        min_v = version_spec.min_inclusive
        # Check all versions from min_v + 1 up to selected.version
        for v in versions:
            if min_v < v.version <= selected.version:
                from modelable.parser.ir import ChangeKind

                if v.change_kind == ChangeKind.breaking:
                    raise LookupError(
                        f"unresolved model reference {model_ref}@{_format_version_spec(version_spec)}: "
                        f"breaking change at version {v.version} blocks automatic resolution"
                    )

    return ResolvedModelRef(
        domain_name=domain_name,
        model_name=model_name,
        version=selected,
    )


def resolve_ref_type(field_type: RefType, mdl: MdlFile) -> ResolvedModelRef:
    """Resolve a ref<> field's target to a concrete model version.

    Unversioned ref<Domain.Model> resolves via VersionMin(1) ("latest
    matching") — the documented interpretation for existing files, and the
    same rule already implicit in emitters/typescript.py's codegen and the
    LSP's definition/hover "unversioned ref" handling.
    """
    version_spec = field_type.version if field_type.version is not None else VersionMin(min_inclusive=1)
    return resolve_model_ref(mdl, field_type.target, version_spec)


def resolved_version_spec(
    mdl: MdlFile,
    model_ref: str,
    version_spec: VersionSpec | int,
) -> VersionExact:
    """Return the concrete version selected by a model reference."""
    resolved = resolve_model_ref(mdl, model_ref, version_spec)
    return VersionExact(version=resolved.version.version)


def find_dependents(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
    version: int,
) -> list[tuple[str, str, int]]:
    """Return list of (domain, projection, version) depending on the source model version."""
    dependents: list[tuple[str, str, int]] = []
    source_ref = f"{domain_name}.{model_name}"

    for domain in mdl.domains:
        for proj_name, proj_versions in domain.projections.items():
            for pv in proj_versions:
                # Check primary source
                is_dependent = False
                if pv.source.model == source_ref:
                    try:
                        resolved = resolve_model_ref(mdl, pv.source.model, pv.source.version)
                        if resolved.version.version == version:
                            is_dependent = True
                    except LookupError:
                        pass

                # Check joins if not already found
                if not is_dependent:
                    for join in pv.joins:
                        if join.model == source_ref:
                            try:
                                resolved = resolve_model_ref(mdl, join.model, join.version)
                                if resolved.version.version == version:
                                    is_dependent = True
                                    break
                            except LookupError:
                                pass

                if is_dependent:
                    dependents.append((domain.name, proj_name, pv.version))

    return dependents


class AmbiguousSemanticTypeError(LookupError):
    """Raised when a bare semantic-type name matches more than one domain's declaration.

    A subclass of ``LookupError`` so existing ``except LookupError`` callers that
    treat "couldn't resolve" uniformly (e.g. skip and move on) keep working
    unchanged; callers that need to react differently to a genuine ambiguity
    (as opposed to a name that simply doesn't exist) can catch this specifically.
    """


def resolve_semantic_type_ref(
    mdl: MdlFile,
    current_domain: str,
    name: str,
    exact_version: int | None = None,
) -> tuple[str, SemanticTypeDecl]:
    """Resolve a semantic-type reference to (declaring_domain_name, SemanticTypeDecl).

    ``name`` may be a bare name (resolved in ``current_domain`` first, falling back to
    a workspace-wide search only when exactly one declaration matches) or a
    domain-qualified reference (``"orders.Id"``).

    When ``exact_version`` is given, only a declaration of that name at exactly
    that version matches — a later version never re-resolves an earlier
    published consumer (evolution plan E2). Without it, the latest declared
    version wins, matching historical behavior.
    """
    if "." in name:
        domain_name, type_name = name.split(".", 1)
        domain = next((item for item in mdl.domains if item.name == domain_name), None)
        if domain is None:
            raise LookupError(f"unknown domain '{domain_name}' in semantic type reference '{name}'")
        decl = _find_semantic_decl(domain, type_name, exact_version)
        if decl is None:
            raise _unknown_semantic_type_error(name, domain, type_name, exact_version)
        return domain_name, decl

    current = next((item for item in mdl.domains if item.name == current_domain), None)
    if current is not None:
        local = _find_semantic_decl(current, name, exact_version)
        if local is not None:
            return current_domain, local

    # Workspace-wide fallback mirrors bare-name semantics: only a unique
    # workspace match is accepted, more than one is ambiguous.
    matches: list[tuple[str, SemanticTypeDecl]] = []
    for domain in mdl.domains:
        decl = _find_semantic_decl(domain, name, exact_version)
        if decl is not None:
            matches.append((domain.name, decl))
    if not matches:
        known_domains = [domain for domain in mdl.domains if any(item.name == name for item in domain.semantic_types)]
        if known_domains and exact_version is not None:
            known = sorted(
                {item.version for domain in known_domains for item in domain.semantic_types if item.name == name}
            )
            raise LookupError(f"semantic type '{name}' has no version {exact_version} (known versions: {known})")
        raise LookupError(f"unknown semantic type '{name}'")
    if len(matches) > 1:
        candidates = ", ".join(f"{domain_name}.{decl.name}" for domain_name, decl in matches)
        raise AmbiguousSemanticTypeError(f"ambiguous semantic type '{name}'; candidates: {candidates}")
    return matches[0]


def _find_semantic_decl(
    domain: DomainDef,
    name: str,
    exact_version: int | None,
) -> SemanticTypeDecl | None:
    if exact_version is None:
        return next((item for item in latest_semantic_types(domain) if item.name == name), None)
    return next(
        (item for item in domain.semantic_types if item.name == name and item.version == exact_version),
        None,
    )


def _unknown_semantic_type_error(
    name: str,
    domain: DomainDef,
    type_name: str,
    exact_version: int | None,
) -> LookupError:
    if exact_version is None:
        return LookupError(f"unknown semantic type '{name}'")
    known = sorted({item.version for item in domain.semantic_types if item.name == type_name})
    return LookupError(f"semantic type '{name}' has no version {exact_version} (known versions: {known})")


def validate_references(mdl: MdlFile) -> list[str]:
    """Return unresolved reference errors for projections, joins, and bindings."""
    errors: list[str] = []

    for domain in mdl.domains:
        for projection_name, projection_versions in domain.projections.items():
            for projection_version in projection_versions:
                context = f"{domain.name}.{projection_name}@{projection_version.version}"
                _append_lookup_error(
                    errors,
                    context,
                    projection_version.source.model,
                    projection_version.source.version,
                    mdl,
                )
                for join in projection_version.joins:
                    _append_lookup_error(errors, context, join.model, join.version, mdl)

    for binding in mdl.bindings:
        if not binding.model:
            continue
        _append_lookup_error(
            errors,
            f"binding {binding.name}",
            binding.model,
            binding.model_version,
            mdl,
        )

    return errors


def _append_lookup_error(
    errors: list[str],
    context: str,
    model_ref: str,
    version_spec: VersionSpec | int,
    mdl: MdlFile,
) -> None:
    try:
        resolve_model_ref(mdl, model_ref, version_spec)
    except LookupError as exc:
        errors.append(f"{context}: {exc}")


def _find_model_versions(
    mdl: MdlFile,
    domain_name: str,
    model_name: str,
) -> list[ModelVersion]:
    for domain in mdl.domains:
        if domain.name == domain_name:
            versions: list[ModelVersion] = []
            versions.extend(domain.models.get(model_name, []))
            versions.extend(domain.projections.get(model_name, []))
            return versions
    return []


def _split_model_ref(model_ref: str) -> tuple[str, str]:
    parts = model_ref.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise LookupError(f"invalid model reference {model_ref}")
    return parts[0], parts[1]


def _matches(
    version: ModelVersion | ProjectionVersion,
    version_spec: VersionSpec | int,
    domain_name: str,
    model_name: str,
) -> bool:
    if isinstance(version_spec, int):
        return version.version == version_spec
    if isinstance(version_spec, VersionExact):
        return version.version == version_spec.version
    if isinstance(version_spec, VersionRange):
        return version_spec.min_inclusive <= version.version < version_spec.max_exclusive
    if isinstance(version_spec, VersionMin):
        return version.version >= version_spec.min_inclusive
    if isinstance(version_spec, VersionPinned):
        if version.version != version_spec.version:
            return False
        return compute_version_signature(domain_name, model_name, version).lower() == version_spec.content_hash.lower()
    return False


def _format_version_spec(version_spec: VersionSpec | int) -> str:
    if isinstance(version_spec, int):
        return str(version_spec)
    if isinstance(version_spec, VersionExact):
        return str(version_spec.version)
    if isinstance(version_spec, VersionRange):
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if isinstance(version_spec, VersionMin):
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return str(version_spec)
