from __future__ import annotations

from collections.abc import Callable

from modelable.emitters.naming import pascalize_plain as _pascalize
from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import EnumProjectionDecl, EnumType, MdlFile, SemanticTypeDecl, latest_semantic_types
from modelable.registry.resolver import AmbiguousSemanticTypeError, resolve_enum_type_ref, resolve_semantic_type_ref


def resolve_named_types(
    mdl: MdlFile,
    *,
    current_domain: str,
    model_name: Callable[[str, str, int], str],
    emit_nominal_enums: bool = False,
    emit_nominal_enum_projections: bool = False,
) -> tuple[dict[str, str], dict[str, TypeShape]]:
    """Resolve source-level named references for a generated target.

    Model references point at the versioned declaration name emitted by the
    target. When ``emit_nominal_enums`` is set, enum-backed semantic
    declarations get their own declared name too (evolution plan E8) --
    the caller must emit one reusable enum type per declaration and import
    it by name, the same way it already imports a model. Every other
    semantic underlying type -- and, for callers not yet migrated to
    ``emit_nominal_enums``, enum-backed ones too -- is expanded inline,
    because those lightweight emitters do not produce a separate wrapper
    artifact for scalar semantics. ``emit_nominal_enums`` defaults to False
    so this shared resolver stays correct for every target as E8 rolls out
    to each one individually; flipping it for a target's emitter is only
    safe once that emitter actually emits the enum type declarations this
    produces references to.
    """
    names: dict[str, str] = {}
    shapes: dict[str, TypeShape] = {}
    for domain in mdl.domains:
        for name, versions in domain.models.items():
            if versions:
                emitted_name = model_name(domain.name, name, versions[-1].version)
                names.setdefault(name, emitted_name)
                names.setdefault(f"{domain.name}.{name}", emitted_name)
                for version in versions:
                    names[f"{domain.name}.{name}@{version.version}"] = model_name(domain.name, name, version.version)

    for domain in mdl.domains:
        for declaration in latest_semantic_types(domain):
            if declaration.name in names:
                continue
            try:
                resolved_domain, resolved = resolve_semantic_type_ref(mdl, current_domain, declaration.name)
            except LookupError, AmbiguousSemanticTypeError:
                continue
            if resolved_domain == domain.name and resolved.name == declaration.name:
                if emit_nominal_enums and isinstance(declaration.underlying, EnumType):
                    names[declaration.name] = declaration.name
                else:
                    shapes[declaration.name] = TypeShape.from_field_type(declaration.underlying)
    return names, shapes


def split_domain_qualifier(name: str) -> tuple[str | None, str]:
    """Split a possibly domain-qualified reference into (domain, bare name).

    ``"patient.PatientId"`` -> ``("patient", "PatientId")``; a bare name
    ``"PatientId"`` -> ``(None, "PatientId")``.
    """
    if "." in name:
        domain_name, _, bare = name.partition(".")
        return (domain_name, bare)
    return (None, name)


def resolve_named_ref(
    mdl: MdlFile,
    *,
    current_domain: str,
    ref: str,
    names: dict[str, str],
    shapes: dict[str, TypeShape],
    emit_nominal_enums: bool = False,
    emit_nominal_enum_projections: bool = False,
    exact_version: int | None = None,
) -> tuple[str | None, str | None, TypeShape | None]:
    """Resolve a single named/semantic reference to the representation a target
    should emit.

    Returns ``(declaring_domain, named_type_name, inline_shape)`` where exactly
    one of ``named_type_name`` / ``inline_shape`` is set:

    - A model/value reference (in ``names``) -> ``(domain, emitted_name, None)``.
    - A semantic reference (in ``shapes``) -> ``(domain, None, underlying_shape)``,
      i.e. the lightweight emitters expand semantics to their underlying shape.
    - ``declaring_domain`` is ``None`` when the reference is local to the
      current domain (no cross-domain import is needed).

    ``ref`` may be bare or domain-qualified; a qualified reference is resolved
    to its declaring domain's semantic even when the current domain could not
    match it by bare name (the case that previously produced a bogus
    ``pascalized`` named type that never exists).
    """
    declaring_domain, bare = split_domain_qualifier(ref)
    if declaring_domain is None:
        local_model_name = f"{current_domain}.{bare}"
        if local_model_name in names:
            return (current_domain, names[local_model_name], None)
        if exact_version is not None:
            model_domain = _unique_model_domain(mdl, bare)
            if model_domain is not None:
                versioned_name = names.get(f"{model_domain}.{bare}@{exact_version}")
                if versioned_name is not None:
                    return (model_domain, versioned_name, None)
        if exact_version is None and ref in names:
            model_domain = _unique_model_domain(mdl, bare)
            return (model_domain or current_domain, names[ref], None)
        if exact_version is None and ref in shapes:
            return (current_domain, None, shapes[ref])
    else:
        if exact_version is not None:
            versioned_name = names.get(f"{declaring_domain}.{bare}@{exact_version}")
            if versioned_name is not None:
                return (declaring_domain, versioned_name, None)
        if exact_version is None and f"{declaring_domain}.{bare}" in names:
            return (declaring_domain, names[f"{declaring_domain}.{bare}"], None)
        if exact_version is None and bare in shapes and declaring_domain != current_domain:
            return (declaring_domain, None, shapes[bare])
    # Qualified semantic reference not visible in the per-domain dicts (or a
    # cross-domain semantic name that resolve_named_types only keyed locally).
    try:
        resolved_domain, decl = resolve_enum_type_ref(mdl, current_domain, ref, exact_version)
    except LookupError, AmbiguousSemanticTypeError:
        return (None, None, None)
    if resolved_domain != current_domain:
        if emit_nominal_enum_projections and isinstance(decl, EnumProjectionDecl):
            return (resolved_domain, _projection_type_name(resolved_domain, decl), None)
        if emit_nominal_enums and isinstance(decl, SemanticTypeDecl) and isinstance(decl.underlying, EnumType):
            return (resolved_domain, _semantic_enum_type_name(mdl, resolved_domain, decl), None)
        if not isinstance(decl, SemanticTypeDecl):
            return (None, None, None)
        return (resolved_domain, None, TypeShape.from_field_type(decl.underlying))
    if emit_nominal_enum_projections and isinstance(decl, EnumProjectionDecl):
        return (current_domain, _projection_type_name(current_domain, decl), None)
    if emit_nominal_enums and isinstance(decl, SemanticTypeDecl) and isinstance(decl.underlying, EnumType):
        return (current_domain, _semantic_enum_type_name(mdl, current_domain, decl), None)
    return (None, None, None)


def _declaring_domain(mdl: MdlFile, name: str) -> str | None:
    """Return the domain that declares the named model or enum-backed
    semantic declaration ``name`` (or None)."""
    for domain in mdl.domains:
        if name in domain.models:
            return domain.name
    for domain in mdl.domains:
        for declaration in latest_semantic_types(domain):
            if declaration.name == name and isinstance(declaration.underlying, EnumType):
                return domain.name
    return None


def _unique_model_domain(mdl: MdlFile, name: str) -> str | None:
    domains = [domain.name for domain in mdl.domains if name in domain.models]
    return domains[0] if len(domains) == 1 else None


def resolve_named_type_domains(mdl: MdlFile, *, current_domain: str) -> dict[str, str]:
    """Resolve the declaring domain for named model/semantic references."""
    result: dict[str, str] = {}
    for domain in mdl.domains:
        for name in domain.models:
            result.setdefault(name, domain.name)
        for declaration in latest_semantic_types(domain):
            try:
                resolved_domain, _ = resolve_semantic_type_ref(mdl, current_domain, declaration.name)
            except LookupError, AmbiguousSemanticTypeError:
                continue
            result.setdefault(declaration.name, resolved_domain)
    return result


def _projection_type_name(domain: str, projection: EnumProjectionDecl) -> str:
    return f"{_pascalize(domain)}{projection.name}V{projection.version}"


def _semantic_enum_type_name(mdl: MdlFile, domain: str, declaration: SemanticTypeDecl) -> str:
    latest = next(
        (
            item
            for item in latest_semantic_types(next(item for item in mdl.domains if item.name == domain))
            if item.name == declaration.name
        ),
        declaration,
    )
    if declaration.version == latest.version:
        return declaration.name
    return f"{_pascalize(domain)}{declaration.name}V{declaration.version}"
