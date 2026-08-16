from __future__ import annotations

from collections.abc import Callable

from modelable.emitters.shapes import TypeShape
from modelable.parser.ir import MdlFile, latest_semantic_types
from modelable.registry.resolver import AmbiguousSemanticTypeError, resolve_semantic_type_ref


def resolve_named_types(
    mdl: MdlFile,
    *,
    current_domain: str,
    model_name: Callable[[str, str, int], str],
) -> tuple[dict[str, str], dict[str, TypeShape]]:
    """Resolve source-level named references for a generated target.

    Model references point at the versioned declaration name emitted by the
    target. Semantic types are expanded to their underlying shape because the
    lightweight emitters do not produce a separate semantic wrapper artifact.
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
                shapes[declaration.name] = TypeShape.from_field_type(declaration.underlying)
    return names, shapes
