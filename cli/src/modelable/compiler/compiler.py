from __future__ import annotations

from pathlib import Path

from modelable.parser.ir import MdlFile
from modelable.parser.parse import parse_file_to_ir, parse_text_to_ir
from modelable.validation.semantic import validate


def compile_text(text: str) -> tuple[MdlFile, list[str]]:
    """Parse and validate .mdl text."""
    mdl = parse_text_to_ir(text)
    return mdl, validate(mdl)


def compile_file(path: str | Path) -> tuple[MdlFile, list[str]]:
    """Parse and validate a .mdl file."""
    mdl = parse_file_to_ir(path)
    return mdl, validate(mdl)
