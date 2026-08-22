from __future__ import annotations

import re
from collections.abc import Callable

_TOKEN_RE = re.compile(r"[^A-Za-z0-9]+")


def pascalize_titlecase(value: str) -> str:
    """PascalCase that titlecases all-uppercase tokens (used by C#/Rust emitters)."""
    parts = [part for part in _TOKEN_RE.split(value) if part]

    def _title(part: str) -> str:
        if part.isupper():
            return part[:1] + part[1:].lower()
        return part[:1].upper() + part[1:]

    return "".join(_title(part) for part in parts) or "Generated"


def pascalize_plain(value: str, fallback: str = "Generated") -> str:
    """PascalCase that capitalizes but preserves the case of the rest (Python/Go/Java/TS emitters)."""
    parts = [part for part in _TOKEN_RE.split(value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or fallback


def snake_case(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    text = text.strip("_").lower()
    return text or "generated"


def apply_case_style(value: str, case: str) -> str:
    """Convert an enum value string to the specified wire case convention.

    Shared by emitters that apply `@wire(json.case ...)` and by validation so
    both sides compute identical wire values.
    """
    words = re.sub(r"([a-z])([A-Z])", r"\1_\2", value)
    words_list = [w for w in re.split(r"[^A-Za-z0-9]+", words) if w]
    if not words_list:
        return value
    if case == "SCREAMING_SNAKE_CASE":
        return "_".join(w.upper() for w in words_list)
    if case == "snake_case":
        return "_".join(w.lower() for w in words_list)
    if case == "camelCase":
        return words_list[0].lower() + "".join(w.capitalize() for w in words_list[1:])
    if case == "PascalCase":
        return "".join(w.capitalize() for w in words_list)
    return value


def find_identifier_collisions(members: list[str], transform: Callable[[str], str]) -> dict[str, list[str]]:
    """Return target identifiers claimed by two or more distinct canonical members.

    Accepts canonical enum members plus a target's casing/escaping policy as a
    transform, and reports every generated identifier that two or more distinct
    canonical members normalize to (case folding, punctuation stripping,
    leading-digit escaping). Pure analysis — emits no code. Evolution plan F3.
    """
    claimed: dict[str, list[str]] = {}
    for member in members:
        identifier = transform(member)
        claimed.setdefault(identifier, []).append(member)
    return {identifier: group for identifier, group in claimed.items() if len(group) > 1}
