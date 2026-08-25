"""Shared text-location helpers for A2's expand/compact tooling: locating a
model version's exact `{ ... }` block span (full-form or `evolves`-form) for
surgical, single-block text replacement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
    r"(?:.*?\bevolves\s*@\s*(?P<base>\d+))?"
)


class ModelBlockNotFoundError(ValueError):
    pass


@dataclass(frozen=True)
class ModelBlockSpan:
    path: Path
    start_index: int
    end_index: int
    is_evolves: bool
    leading_whitespace: str


def find_model_block(
    sources_by_path: dict[Path, list[str]],
    domain_name: str,
    model_name: str,
    version: int,
) -> ModelBlockSpan:
    for path, lines in sources_by_path.items():
        current_domain: str | None = None
        for index, line in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                continue
            if current_domain != domain_name:
                continue
            decl_match = _DECL_PATTERN.match(line)
            if decl_match is None:
                continue
            if decl_match.group("name") != model_name or int(decl_match.group("version")) != version:
                continue
            end_index = _matching_close_brace(lines, index)
            if end_index is None:
                raise ModelBlockNotFoundError(
                    f"{domain_name}.{model_name}@{version}: could not find a matching closing brace"
                )
            leading_whitespace = line[: len(line) - len(line.lstrip())]
            return ModelBlockSpan(
                path=path,
                start_index=index,
                end_index=end_index,
                is_evolves=decl_match.group("base") is not None,
                leading_whitespace=leading_whitespace,
            )
    raise ModelBlockNotFoundError(f"{domain_name}.{model_name}@{version}: declaration not found in any source file")


def _matching_close_brace(lines: list[str], start_index: int) -> int | None:
    depth = 0
    for index in range(start_index, len(lines)):
        depth += lines[index].count("{") - lines[index].count("}")
        if depth == 0:
            return index
    return None


def block_contains_comment(lines: list[str], span: ModelBlockSpan) -> bool:
    return any("//" in lines[index] for index in range(span.start_index, span.end_index + 1))
