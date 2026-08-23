from __future__ import annotations

from collections.abc import Callable

from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import EnumType, MdlFile, latest_semantic_types
from modelable.registry.resolver import AmbiguousSemanticTypeError, resolve_semantic_type_ref


def resolve_named_types(
    mdl: MdlFile,
    *,
    current_domain: str,
    model_name: Callable[[str, str, int], str],
    emit_nominal_enums: bool = False,
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
                names.setdefault(name, model_name(domain.name, name, versions[-1].version))

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
        if ref in names:
            return (_declaring_domain(mdl, ref) or current_domain, names[ref], None)
        if ref in shapes:
            return (current_domain, None, shapes[ref])
    else:
        if bare in names and declaring_domain != current_domain:
            return (declaring_domain, names[bare], None)
        if bare in shapes and declaring_domain != current_domain:
            return (declaring_domain, None, shapes[bare])
    # Qualified semantic reference not visible in the per-domain dicts (or a
    # cross-domain semantic name that resolve_named_types only keyed locally).
    try:
        resolved_domain, decl = resolve_semantic_type_ref(mdl, current_domain, ref)
    except LookupError, AmbiguousSemanticTypeError:
        return (None, None, None)
    if resolved_domain != current_domain:
        if emit_nominal_enums and isinstance(decl.underlying, EnumType):
            return (resolved_domain, decl.name, None)
        return (resolved_domain, None, TypeShape.from_field_type(decl.underlying))
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
