"""Canonical semantic declaration and path identities."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH_SEGMENT = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*(?:\[\]|\{\}|\{key\})?|\[\]|\{\}|\{key\})$")


def declaration_id(domain: str, name: str, version: int) -> str:
    """Render an exact, source-location-independent declaration identity."""
    for label, value in (("domain", domain), ("name", name)):
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError(f"{label} must be a language identifier: {value!r}")
    if version < 0:
        raise ValueError("declaration version must be non-negative")
    return f"{domain}.{name}@{version}"


@dataclass(frozen=True)
class SemanticPath:
    """A declaration identity plus typed field/container path segments."""

    declaration: str
    segments: tuple[str, ...]

    def render(self) -> str:
        if not self.segments:
            raise ValueError("semantic paths must address at least one segment")
        if any(not _PATH_SEGMENT.fullmatch(segment) for segment in self.segments):
            raise ValueError("semantic path contains an invalid segment")
        return f"{self.declaration}#{'.'.join(self.segments)}"


def parse_semantic_path(value: str) -> SemanticPath:
    """Parse a canonical semantic path and reject ambiguous spellings."""
    declaration, separator, path = value.partition("#")
    if not separator or not declaration or not path:
        raise ValueError(f"invalid semantic path: {value!r}")
    domain_name, at, version_text = declaration.rpartition("@")
    domain, dot, name = domain_name.partition(".")
    if not at or not dot or not version_text.isdigit():
        raise ValueError(f"invalid declaration identity in semantic path: {value!r}")
    canonical_declaration = declaration_id(domain, name, int(version_text))
    segments = tuple(path.split("."))
    result = SemanticPath(canonical_declaration, segments)
    if result.render() != value:
        raise ValueError(f"non-canonical semantic path: {value!r}")
    return result


def semantic_path(declaration: str, *segments: str) -> str:
    """Render a canonical semantic path rooted in an exact declaration ID."""
    return SemanticPath(declaration, tuple(segments)).render()
