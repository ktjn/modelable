"""Validated, deterministic target overlay configuration."""

from __future__ import annotations

import operator
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from types import MappingProxyType
from typing import Any

from modelable.identity import declaration_id, parse_semantic_path

_DECLARATION_SELECTOR = re.compile(
    r"^(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)@(?P<version>[^#]+)$"
)
_RANGE_PART = re.compile(r"^(?P<operator>>=|<)(?P<version>[0-9]+)$")
_SECTIONS = {"defaults", "models", "fields"}
_COMPARATORS: dict[str, Callable[[int, int], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
}


class OverlayError(ValueError):
    """Raised when an overlay is malformed or cannot be resolved."""


class OverlayConflictError(OverlayError):
    """Raised when equal-specificity overlay entries disagree."""


@dataclass(frozen=True)
class _VersionSelector:
    text: str
    matches: Callable[[int], bool]
    exact: bool


@dataclass(frozen=True)
class _Selector:
    text: str
    declaration: str
    version: _VersionSelector
    path: str | None
    specificity: int

    def matches(self, declaration: str, version: int, path: str | None) -> bool:
        return (
            self.declaration == declaration
            and self.version.matches(version)
            and (self.path is None or _path_selector_matches(self.path, path))
        )


@dataclass(frozen=True)
class OverlayEntry:
    """One canonical selector and its target-owned representation values."""

    section: str
    selector: str
    values: Mapping[str, Any]
    _parsed: _Selector | None = None

    @property
    def specificity(self) -> int:
        return 0 if self._parsed is None else self._parsed.specificity


@dataclass(frozen=True)
class OverlayDocument:
    """A validated target overlay and its deterministic entries."""

    target: str
    version: int
    defaults: Mapping[str, Any]
    entries: tuple[OverlayEntry, ...]
    path: Path | None = None

    def resolve(self, identity: str, semantic_path: str | None = None) -> OverlayResolution:
        return resolve_overlay(self, identity, semantic_path)


@dataclass(frozen=True)
class OverlayResolution:
    """Merged values and the selector that supplied each value."""

    values: Mapping[str, Any]
    provenance: Mapping[str, str]


def load_overlay(path: str | Path) -> OverlayDocument:
    """Load and validate one non-executable TOML overlay file."""
    overlay_path = Path(path)
    try:
        data = tomllib.loads(overlay_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise OverlayError(f"cannot read overlay {overlay_path}: {exc}") from exc
    return parse_overlay(data, path=overlay_path)


def parse_overlay(data: Mapping[str, Any], *, path: Path | None = None) -> OverlayDocument:
    """Validate parsed TOML data using the common overlay envelope."""
    if not isinstance(data, Mapping):
        raise OverlayError("overlay must be a TOML table")
    target = data.get("target")
    version = data.get("version")
    if not isinstance(target, str) or not target:
        raise OverlayError("overlay requires a non-empty string 'target'")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise OverlayError("overlay requires a positive integer 'version'")

    unknown = sorted(set(data) - {"target", "version", *_SECTIONS})
    if unknown:
        raise OverlayError(f"overlay has unknown top-level key(s): {', '.join(unknown)}")
    defaults = _table(data.get("defaults", {}), "[defaults]")
    _validate_values(defaults, "[defaults]")
    entries: list[OverlayEntry] = []
    for section in ("models", "fields"):
        table = _table(data.get(section, {}), f"[{section}]")
        for selector, raw_values in table.items():
            if not isinstance(selector, str):
                raise OverlayError(f"[{section}] selector keys must be strings")
            values = _table(raw_values, f"[{section}.{selector}]")
            _validate_values(values, f"[{section}.{selector}]")
            parsed = _parse_selector(selector, section)
            entries.append(OverlayEntry(section, selector, MappingProxyType(dict(values)), parsed))
    return OverlayDocument(
        target=target,
        version=version,
        defaults=MappingProxyType(dict(defaults)),
        entries=tuple(sorted(entries, key=lambda entry: (entry.specificity, entry.section, entry.selector))),
        path=path,
    )


def resolve_overlay(
    document: OverlayDocument,
    identity: str,
    semantic_path: str | None = None,
) -> OverlayResolution:
    """Resolve target defaults and matching selectors without file-order effects."""
    declaration, version = _parse_identity(identity)
    requested_path: str | None = None
    if semantic_path is not None:
        parsed_path = parse_semantic_path(semantic_path)
        if parsed_path.declaration != identity:
            raise OverlayError(f"semantic path {semantic_path!r} does not belong to declaration {identity!r}")
        requested_path = semantic_path.partition("#")[2]

    values: dict[str, Any] = dict(document.defaults)
    provenance = dict.fromkeys(values, "defaults")
    matching = [
        entry
        for entry in document.entries
        if entry._parsed is not None and entry._parsed.matches(declaration, version, requested_path)
    ]
    for specificity in sorted({entry.specificity for entry in matching}):
        layer = [entry for entry in matching if entry.specificity == specificity]
        supplied: dict[str, tuple[Any, str]] = {}
        for entry in layer:
            for key, value in entry.values.items():
                previous = supplied.get(key)
                if previous is not None and previous[0] != value:
                    raise OverlayConflictError(
                        f"equal-specificity overlay conflict for {key!r}: {previous[1]!r} and {entry.selector!r}"
                    )
                supplied[key] = (value, entry.selector)
        for key, (value, selector) in supplied.items():
            values[key] = value
            provenance[key] = selector
    return OverlayResolution(MappingProxyType(values), MappingProxyType(provenance))


def _table(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OverlayError(f"{label} must be a TOML table")
    return value


def _validate_values(values: Mapping[str, Any], label: str) -> None:
    for key, value in values.items():
        if not isinstance(key, str):
            raise OverlayError(f"{label} keys must be strings")
        if isinstance(value, dict):
            _validate_values(value, f"{label}.{key}")
        elif isinstance(value, list):
            if any(isinstance(item, (dict, list)) for item in value):
                raise OverlayError(f"{label}.{key} must contain only TOML scalar values")
            if any(not isinstance(item, (str, int, float, bool, date, datetime, time)) for item in value):
                raise OverlayError(f"{label}.{key} contains an unsupported value")
        elif not isinstance(value, (str, int, float, bool, date, datetime, time)):
            raise OverlayError(f"{label}.{key} contains an unsupported value")


def _parse_identity(value: str) -> tuple[str, int]:
    match = _DECLARATION_SELECTOR.fullmatch(value)
    if match is None or not match.group("version").isdigit():
        raise OverlayError(f"invalid declaration identity: {value!r}")
    declaration = declaration_id(match.group("domain"), match.group("name"), int(match.group("version")))
    if declaration != value:
        raise OverlayError(f"non-canonical declaration identity: {value!r}")
    return f"{match.group('domain')}.{match.group('name')}", int(match.group("version"))


def _parse_selector(value: str, section: str) -> _Selector:
    declaration_text, separator, path = value.partition("#")
    if section == "models" and separator:
        raise OverlayError(f"model selector cannot contain a semantic path: {value!r}")
    if section == "fields" and not separator:
        raise OverlayError(f"field selector requires a semantic path: {value!r}")
    declaration_match = _DECLARATION_SELECTOR.fullmatch(declaration_text)
    if declaration_match is None:
        raise OverlayError(f"invalid overlay selector: {value!r}")
    domain = declaration_match.group("domain")
    name = declaration_match.group("name")
    version_text = declaration_match.group("version")
    if version_text == "*":
        version = _VersionSelector(version_text, lambda _value: True, False)
        version_specificity = 1
    else:
        version = _parse_version_selector(version_text, value)
        version_specificity = 3 if version.exact else 2
    declaration = f"{domain}.{name}"
    if path:
        try:
            _validate_path_selector(declaration, path)
        except ValueError as exc:
            raise OverlayError(f"invalid semantic path in selector: {value!r}") from exc
        specificity = 4 if "*" in path or not version.exact else 5
    else:
        specificity = version_specificity
    return _Selector(value, declaration, version, path or None, specificity)


def _validate_path_selector(declaration: str, path: str) -> None:
    """Validate a concrete path or a path with full-segment wildcards."""
    if not path or "#" in path:
        raise ValueError
    if "*" not in path:
        parse_semantic_path(f"{declaration}@0#{path}")
        return
    for segment in path.split("."):
        if segment == "*":
            continue
        parse_semantic_path(f"{declaration}@0#{segment}")


def _path_selector_matches(selector: str, path: str | None) -> bool:
    if path is None:
        return False
    selector_segments = selector.split(".")
    path_segments = path.split(".")
    return len(selector_segments) == len(path_segments) and all(
        selector_segment == "*" or selector_segment == path_segment
        for selector_segment, path_segment in zip(selector_segments, path_segments, strict=True)
    )


def _parse_version_selector(value: str, selector: str) -> _VersionSelector:
    if value.isdigit():
        if len(value) > 1 and value.startswith("0"):
            raise OverlayError(f"non-canonical version selector: {selector!r}")
        expected = int(value)
        return _VersionSelector(value, lambda actual: actual == expected, True)
    parts = value.split(",")
    if len(parts) not in (1, 2) or (len(parts) == 2 and not parts[1].startswith("<")):
        raise OverlayError(f"non-canonical version range in selector: {selector!r}")
    constraints: list[tuple[Callable[[int, int], bool], int]] = []
    for part in parts:
        if part != part.strip():
            raise OverlayError(f"non-canonical version range in selector: {selector!r}")
        match = _RANGE_PART.fullmatch(part)
        if match is None:
            raise OverlayError(f"invalid version range in selector: {selector!r}")
        if len(match.group("version")) > 1 and match.group("version").startswith("0"):
            raise OverlayError(f"non-canonical version range in selector: {selector!r}")
        constraints.append((_COMPARATORS[match.group("operator")], int(match.group("version"))))
    if not constraints:
        raise OverlayError(f"invalid version range in selector: {selector!r}")
    lower_bounds = [expected for compare, expected in constraints if compare in (operator.ge, operator.gt)]
    upper_bounds = [expected for compare, expected in constraints if compare in (operator.le, operator.lt)]
    if lower_bounds and upper_bounds and max(lower_bounds) >= min(upper_bounds):
        raise OverlayError(f"version range is empty or reversed in selector: {selector!r}")
    return _VersionSelector(
        value, lambda actual: all(compare(actual, expected) for compare, expected in constraints), False
    )
