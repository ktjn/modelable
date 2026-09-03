"""Canonical semantic declaration and path identities."""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOMAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_PATH_SEGMENT = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*(?:\[\]|\{\}|\{key\})?|\[\]|\{\}|\{key\})$")


@dataclass(frozen=True)
class DeclarationId:
    """Typed identity for a named declaration before version selection."""

    domain: str
    name: str

    def __post_init__(self) -> None:
        if not _DOMAIN.fullmatch(self.domain):
            raise ValueError(f"domain must be a valid domain name: {self.domain!r}")
        if not _IDENTIFIER.fullmatch(self.name):
            raise ValueError(f"name must be a language identifier: {self.name!r}")

    def render(self) -> str:
        return f"{self.domain}.{self.name}"


@dataclass(frozen=True)
class DeclarationVersion:
    """Typed exact declaration identity including its published version."""

    declaration: DeclarationId
    version: int

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("declaration version must be non-negative")

    @property
    def identity(self) -> str:
        return f"{self.declaration.render()}@{self.version}"

    @classmethod
    def parse(cls, value: str) -> DeclarationVersion:
        domain, name, version = parse_declaration_id(value)
        return cls(DeclarationId(domain, name), version)


@dataclass(frozen=True)
class DeclarationReference:
    """Typed exact declaration or semantic-path reference."""

    declaration: DeclarationVersion
    segments: tuple[str, ...] = ()

    def render(self) -> str:
        if not self.segments:
            return self.declaration.identity
        return SemanticPath(self.declaration.identity, self.segments).render()

    @classmethod
    def parse(cls, value: str) -> DeclarationReference:
        if "#" in value:
            path = parse_semantic_path(value)
            return cls(DeclarationVersion.parse(path.declaration), path.segments)
        return cls(DeclarationVersion.parse(value))


def declaration_id(domain: str, name: str, version: int) -> str:
    """Render an exact, source-location-independent declaration identity."""
    return DeclarationVersion(DeclarationId(domain, name), version).identity


def parse_declaration_id(value: str) -> tuple[str, str, int]:
    """Parse and validate an exact canonical declaration identity."""
    domain_name, at, version_text = value.rpartition("@")
    domain, dot, name = domain_name.partition(".")
    if not at or not dot or not version_text.isdigit():
        raise ValueError(f"invalid declaration identity: {value!r}")
    canonical = declaration_id(domain, name, int(version_text))
    if canonical != value:
        raise ValueError(f"non-canonical declaration identity: {value!r}")
    return domain, name, int(version_text)


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
    parse_declaration_id(declaration)
    return SemanticPath(declaration, tuple(segments)).render()
