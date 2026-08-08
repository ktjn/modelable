"""Render the canonical Modelable grammar into docs/grammar.md.

The Lark EBNF in ``cli/src/modelable/grammar/modelable.lark`` is the single
source of truth for the language. This script regenerates the published
grammar page from it so the parser and the documentation cannot drift apart.
Run it from anywhere; it locates files relative to the repo root.

    uv run python cli/scripts/render_language_grammar.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
GRAMMAR = CLI_ROOT / "src" / "modelable" / "grammar" / "modelable.lark"
OUTPUT = REPO_ROOT / "docs" / "grammar.md"

_RULE_HEADER = re.compile(r"^([a-z][a-z0-9_]*):\s*(.*)$")
_TERMINAL_HEADER = re.compile(r"^([A-Z][A-Z0-9_]*):\s*(.*)$")
_DIRECTIVE = re.compile(r"^(%[a-z]+.*)$")
_COMMENT = re.compile(r"^\s*//")
_BLANK = re.compile(r"^\s*$")
_ALTERNATION = re.compile(r"^\s*\|")
_QUOTED = re.compile(r'"[^"]*"')
_REGEX_TOKEN = re.compile(r"/.*/")


def _is_lexical(parts: list[str]) -> bool:
    """A definition is lexical-only when every token is a regex or an alternation bar."""
    tokens: list[str] = []
    for part in parts:
        tokens.extend(part.split())
    return all(token == "|" or _REGEX_TOKEN.match(token) for token in tokens)


def _parse_grammar(text: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Split the grammar into (rules, terminals, directives) with normalized bodies."""
    rules: list[tuple[str, str]] = []
    terminals: list[tuple[str, str]] = []
    directives: list[str] = []

    current: tuple[str, str] | None = None
    parts: list[str] = []

    def flush() -> None:
        nonlocal current, parts
        if current is None:
            return
        body = " | ".join(parts)
        if _is_lexical(parts):
            terminals.append((current[0], body))
        else:
            rules.append((current[0], body))
        current = None
        parts = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or _COMMENT.match(raw):
            continue
        if _DIRECTIVE.match(line):
            flush()
            directives.append(line)
            continue
        header = _RULE_HEADER.match(line) or _TERMINAL_HEADER.match(line)
        if header and not _ALTERNATION.match(raw):
            flush()
            current = (header.group(1),)
            parts = [header.group(2)]
            continue
        if current is not None and (line.startswith("|") or raw.startswith((" ", "\t"))):
            parts.append(line.lstrip("|").strip())
            continue
    flush()

    return rules, terminals, directives


def _md_cell(value: str) -> str:
    return "`" + value.replace("|", r"\|") + "`"


def _render(rules: list[tuple[str, str]], terminals: list[tuple[str, str]], directives: list[str]) -> str:
    lines: list[str] = [
        "# Modelable Grammar",
        "",
        "> Generated from `cli/src/modelable/grammar/modelable.lark` by",
        "> `cli/scripts/render_language_grammar.py` — do not edit by hand. Whenever the",
        "> grammar changes, regenerate this page and commit it alongside the parser.",
        "",
        "This page is the published form of the canonical grammar. The Lark EBNF",
        "in `cli/src/modelable/grammar/modelable.lark` is loaded by",
        '`cli/src/modelable/parser/parse.py` via `Lark(parser="earley",',
        'ambiguity="resolve")` and remains the single source of truth. If any',
        "example in [language-reference.md](language-reference.md) conflicts with",
        "this grammar, the documentation identifies a defect; it does not redefine",
        "the language.",
        "",
        "## Grammar",
        "",
        "```lark",
    ]
    lines.extend(GRAMMAR.read_text(encoding="utf-8").rstrip().splitlines())
    lines.extend(["```", ""])

    lines.extend(["## Rule index", "", "Alphabetical listing of every named rule and its production.", ""])
    lines.append("| Rule | Production |")
    lines.append("|---|---|")
    for name, body in sorted(rules):
        lines.append(f"| {_md_cell(name)} | {_md_cell(body)} |")
    lines.append("")

    lines.extend(["## Lexical rules", "", "Regular-expression terminals used by the lexer.", ""])
    lines.append("| Token | Pattern |")
    lines.append("|---|---|")
    for name, body in sorted(terminals):
        lines.append(f"| {_md_cell(name)} | {_md_cell(body)} |")
    lines.append("")

    lines.extend(["## Directives", "", "Lark import and ignore directives.", ""])
    lines.extend(f"- `{d}`" for d in directives)
    lines.append("")

    return "\n".join(lines)


def render_text(grammar: Path) -> str:
    text = grammar.read_text(encoding="utf-8")
    rules, terminals, directives = _parse_grammar(text)
    return _render(rules, terminals, directives)


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate docs/grammar.md from modelable.lark")
    parser.add_argument("--grammar", type=Path, default=GRAMMAR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    text = render_text(args.grammar)
    if str(args.output) == "-":
        print(text, end="")
    else:
        args.output.write_text(text, encoding="utf-8")
        print(f"Grammar page written to {args.output}")


if __name__ == "__main__":
    main()
