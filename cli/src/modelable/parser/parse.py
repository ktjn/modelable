from functools import cache
from importlib.resources import files
from pathlib import Path

from lark import Lark, Tree, UnexpectedInput


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
