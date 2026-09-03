from __future__ import annotations

import re

from modelable.compiler.workspace import Workspace
from modelable.parser.ir import JoinRef, SourceRef, VersionExact, VersionMin, VersionPinned, VersionRange, VersionSpec
from modelable.registry.resolver import resolve_declaration

REF_TYPE_PATTERN = re.compile(
    r"ref\s*<\s*(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*@\s*(?P<version>"
    r">=\s*\d+\s*<\s*\d+"
    r"|>=\s*\d+"
    r"|\d+\s*#\s*[A-Za-z0-9_]+"
    r"|\d+"
    r"))?"
    r"\s*>"
)


def _parse_version_text(version_text: str | None) -> VersionSpec | None:
    """Parse a ref<>'s captured '@ ...' text into a VersionSpec, or None if absent."""
    if version_text is None:
        return None
    text = version_text.replace(" ", "")
    range_match = re.fullmatch(r">=(\d+)<(\d+)", text)
    if range_match:
        return VersionRange(min_inclusive=int(range_match.group(1)), max_exclusive=int(range_match.group(2)))
    min_match = re.fullmatch(r">=(\d+)", text)
    if min_match:
        return VersionMin(min_inclusive=int(min_match.group(1)))
    pinned_match = re.fullmatch(r"(\d+)#([A-Za-z0-9_]+)", text)
    if pinned_match:
        return VersionPinned(version=int(pinned_match.group(1)), content_hash=pinned_match.group(2))
    exact_match = re.fullmatch(r"(\d+)", text)
    if exact_match:
        return VersionExact(version=int(exact_match.group(1)))
    return None


def resolve_ref_match_version(
    workspace: Workspace,
    domain_name: str,
    name: str,
    version_text: str | None,
) -> int | None:
    """Resolve a ref<> match's (domain, name, optional version text) to a concrete version number.

    version_text=None resolves to the latest matching version (VersionMin(1))
    — the same "unversioned ref" rule resolve_ref_type uses for parsed IR
    fields. Returns None if the reference doesn't resolve at all (unknown
    domain/model/version) — callers should fall back to their existing
    "not found" handling rather than raise.
    """
    version_spec = _parse_version_text(version_text)
    if version_spec is None:
        version_spec = VersionMin(min_inclusive=1)
    try:
        resolved = resolve_declaration(
            workspace.mdl,
            f"{domain_name}.{name}",
            version_spec,
            allowed_kinds=frozenset({"model", "projection"}),
        )
    except LookupError:
        return None
    return resolved.version_number


def projection_aliases(
    workspace: Workspace,
    domain_name: str,
    projection_name: str,
    version: int,
) -> dict[str, tuple[str, str, int]]:
    """Map each source/join alias of a projection version to its resolved model.

    Values are ``(domain, model, version)`` triples; aliases whose model
    reference does not resolve are omitted, as are unknown projections.
    """
    domain = next((item for item in workspace.mdl.domains if item.name == domain_name), None)
    if domain is None:
        return {}
    versions = domain.projections.get(projection_name, [])
    projection_version = next((item for item in versions if item.version == version), None)
    if projection_version is None:
        return {}

    aliases: dict[str, tuple[str, str, int]] = {}
    all_sources: list[SourceRef | JoinRef] = [projection_version.source, *projection_version.joins]
    for source_ref in all_sources:
        try:
            resolved = resolve_declaration(
                workspace.mdl,
                source_ref.model,
                source_ref.version,
                allowed_kinds=frozenset({"model", "projection"}),
            )
        except LookupError:
            continue
        aliases[source_ref.alias] = (
            resolved.domain_name,
            resolved.name,
            resolved.version_number,
        )
    return aliases
