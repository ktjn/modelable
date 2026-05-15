from functools import cache
from importlib.resources import files
from pathlib import Path

from lark import Lark, Tree, UnexpectedInput

from modelable.parser.ir import MdlFile
from modelable.parser.transformer import MdlTransformer


class ParseError(Exception):
    """Raised when .mdl input cannot be parsed."""


@cache
def _parser() -> Lark:
    grammar_path = files("modelable.grammar").joinpath("modelable.lark")
    return Lark(
        grammar_path.read_text(encoding="utf-8"),
        parser="earley",
        ambiguity="resolve",
    )


def parse_text(text: str) -> Tree:
    try:
        return _parser().parse(text)
    except UnexpectedInput as exc:
        raise ParseError(str(exc)) from exc


def parse_file(path: str | Path) -> Tree:
    return parse_text(Path(path).read_text(encoding="utf-8"))


def parse_text_to_ir(text: str) -> MdlFile:
    return MdlTransformer().transform(parse_text(text))


def parse_file_to_ir(path: str | Path) -> MdlFile:
    return parse_text_to_ir(Path(path).read_text(encoding="utf-8"))
