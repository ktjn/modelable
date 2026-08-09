from __future__ import annotations

import re

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
