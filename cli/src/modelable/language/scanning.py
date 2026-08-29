from __future__ import annotations

import re

from modelable.language.positions import document_lines

DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def contains(start: int, end: int, character: int) -> bool:
    """True when the cursor at ``character`` sits on the span ``[start, end)``.

    The cursor is also treated as on-span when it rests on the span's closing
    boundary, so clicking just past the last character still resolves it.
    """
    return start <= character <= max(end - 1, start)


def word_at(text_line: str, character: int) -> str | None:
    """Return the identifier the cursor rests on, or None outside any identifier."""
    for match in WORD_PATTERN.finditer(text_line):
        if contains(match.start(), match.end(), character):
            return match.group(0)
    return None


def domain_at_or_before(text: str, line: int) -> str | None:
    """Return the name of the last ``domain`` header at or above ``line``."""
    current_domain: str | None = None
    for item in document_lines(text)[: line + 1]:
        domain_match = DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
    return current_domain
