from __future__ import annotations

import re

_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*=\s*([^\s,;]+)"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\s*:\s*([^\s,;]+)"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(-----BEGIN [^-]+PRIVATE KEY-----).*?(-----END [^-]+PRIVATE KEY-----)", re.DOTALL), "[REDACTED PRIVATE KEY]"),
)


def redact_sensitive_values(text: str) -> str:
    redacted = text
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted

