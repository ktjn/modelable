from functools import cache
from importlib.resources import files
from pathlib import Path

from lark import Lark, Tree, UnexpectedInput
from lark.exceptions import VisitError

from modelable.parser.ir import MdlFile, ParseError
from modelable.parser.transformer import MdlTransformer


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
        raise ParseError(
            str(exc),
            line=getattr(exc, "line", None),
            column=getattr(exc, "column", None),
            end_line=getattr(exc, "end_line", None),
            end_column=getattr(exc, "end_column", None),
        ) from exc


def parse_file(path: str | Path) -> Tree:
    return parse_text(Path(path).read_text(encoding="utf-8"))


def parse_text_to_ir_with_tree(text: str, path: str | Path | None = None) -> tuple[MdlFile, Tree]:
    """Parse one source document into its per-file IR plus syntax tree.

    Parsing-level API: the returned ``MdlFile`` is an *unresolved, per-source*
    declaration set — cross-file references are not resolved, auto projections
    are not expanded, and config defaults are not applied. It is intended for
    syntax tooling (formatter, deferred-syntax scan). Canonical normalized
    contracts come only from
    :func:`modelable.compiler.workspace.load_workspace_from_sources`.
    """
    tree = parse_text(text)
    try:
        return MdlTransformer().transform(tree), tree
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
    except VisitError as exc:
        if isinstance(exc.orig_exc, ValueError):
            raise ParseError(str(exc.orig_exc)) from exc.orig_exc
        raise


def parse_text_to_ir(text: str, path: str | Path | None = None) -> MdlFile:
    """Parsing-level API — see :func:`parse_text_to_ir_with_tree`.

    Returns unresolved per-source declarations; do not treat them as canonical
    contracts for signatures, registry state, compatibility, or emission.
    """
    mdl, _tree = parse_text_to_ir_with_tree(text, path=path)
    return mdl


def parse_file_to_ir(path: str | Path) -> MdlFile:
    """Parsing-level API — see :func:`parse_text_to_ir_with_tree`."""
    path = Path(path)
    return parse_text_to_ir(path.read_text(encoding="utf-8"), path=path)
