from __future__ import annotations

from pathlib import Path

from modelable.parser.ir import MdlFile
from modelable.parser.parse import parse_file_to_ir, parse_text_to_ir
from modelable.validation.semantic import validate


def compile_text(text: str) -> tuple[MdlFile, list[str]]:
    """Parse and validate .mdl text.

    Parsing-level convenience: returns unresolved per-source declarations plus
    single-file semantic errors. Canonical normalized contracts (merged
    domains, expanded projections, resolved references) come only from
    :func:`modelable.compiler.workspace.load_workspace_from_sources`.
    """
    mdl = parse_text_to_ir(text)
    return mdl, validate(mdl)


def compile_file(path: str | Path) -> tuple[MdlFile, list[str]]:
    """Parse and validate a .mdl file — parsing-level, see :func:`compile_text`."""
    mdl = parse_file_to_ir(path)
    return mdl, validate(mdl)
