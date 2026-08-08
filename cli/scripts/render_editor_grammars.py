"""Regenerate editor keyword/type lists from the canonical modelable.lark grammar.

The Lark EBNF is the single source of truth for the language. This script
derives the keyword and type vocabularies from it and rewrites the two editor
grammar definitions that duplicate that vocabulary by hand:

- `vscode/syntaxes/modelable.tmLanguage.json` (TextMate `keywords` and
  `primitive-types` sections)
- `web/src/language/monaco-providers.ts` (Monarch `keywords` and `types`
  arrays)

Run it from anywhere; paths are located relative to the repo root.

    uv run python cli/scripts/render_editor_grammars.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
GRAMMAR = CLI_ROOT / "src" / "modelable" / "grammar" / "modelable.lark"
TM_LANGUAGE = REPO_ROOT / "vscode" / "syntaxes" / "modelable.tmLanguage.json"
MONACO = REPO_ROOT / "web" / "src" / "language" / "monaco-providers.ts"

_TYPE_RULES = (
    "primitive_type",
    "decimal_type",
    "fixed_binary_type",
    "enum_type",
    "array_type",
    "map_type",
    "ref_type",
    "object_type",
)

_QUOTED = re.compile(r'"([A-Za-z_][A-Za-z0-9_-]*)"')
_RULE_BODY = re.compile(r"^([a-z][a-z0-9_]*):(.*)$", re.M)


def _ordered_literals(text: str) -> list[str]:
    """Word-like quoted literals in first-appearance order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for word in _QUOTED.findall(text):
        if word not in seen:
            seen.add(word)
            ordered.append(word)
    return ordered


def _type_vocabulary(text: str) -> list[str]:
    """Type words in the order they appear in the type-producing rules."""
    seen: set[str] = set()
    ordered: list[str] = []
    for rule in _TYPE_RULES:
        for word in _QUOTED.findall(_rule_body(text, rule)):
            if word not in seen:
                seen.add(word)
                ordered.append(word)
    return ordered


def _rule_body(text: str, rule: str) -> str:
    lines = text.splitlines()
    body: list[str] = []
    for raw in lines:
        header = _RULE_BODY.match(raw)
        if header:
            if header.group(1) == rule:
                body = [header.group(2)]
            elif body:
                break
        elif body and (raw.strip().startswith("|") or raw.startswith((" ", "\t"))):
            body.append(raw)
    return "\n".join(body)


def _keyword_vocabulary(text: str) -> list[str]:
    """Bare quoted words that are not types or annotations, in order."""
    type_words = set(_type_vocabulary(text))
    ordered = _ordered_literals(text)
    return [word for word in ordered if word not in type_words and not word.startswith("@")]


def _tm_match(words: list[str]) -> str:
    return "\\\\b(" + "|".join(words) + ")\\\\b"


def _monarch_list(words: list[str]) -> str:
    items = "".join(f"      '{word}',\n" for word in words)
    return f"[\n{items}    ]"


def render_tm_language(text: str, keywords: list[str], types: list[str]) -> str:
    """Rewrite the keywords/primitive-types match lines in place."""
    keyword_pattern = re.compile(r"(\"name\": \"keyword.control.mdl\",\n(\s*)\"match\": )\"[^\"]*\"")

    def keyword_replacement(m: re.Match[str]) -> str:
        return m.group(1) + '"' + _tm_match(keywords) + '"'

    text = keyword_pattern.sub(keyword_replacement, text, count=1)
    type_pattern = re.compile(r"(\"name\": \"support.type.primitive.mdl\",\n(\s*)\"match\": )\"[^\"]*\"")

    def type_replacement(m: re.Match[str]) -> str:
        return m.group(1) + '"' + _tm_match(types) + '"'

    return type_pattern.sub(type_replacement, text, count=1)


def render_monaco(text: str, keywords: list[str], types: list[str]) -> str:
    keywords_block = _monarch_list(keywords)
    types_block = _monarch_list(types)
    keywords_re = re.compile(r"keywords: \[\n.*?\n    \],", re.S)
    types_re = re.compile(r"types: \[\n.*?\n    \],", re.S)
    text = keywords_re.sub(f"keywords: {keywords_block},", text, count=1)
    text = types_re.sub(f"types: {types_block},", text, count=1)
    return text


def render_text(grammar: Path) -> tuple[str, str]:
    grammar_text = grammar.read_text(encoding="utf-8")
    keywords = _keyword_vocabulary(grammar_text)
    types = _type_vocabulary(grammar_text)
    return (
        render_tm_language(TM_LANGUAGE.read_text(encoding="utf-8"), keywords, types),
        render_monaco(MONACO.read_text(encoding="utf-8"), keywords, types),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate editor grammars from modelable.lark")
    parser.add_argument("--grammar", type=Path, default=GRAMMAR)
    parser.add_argument("--tm-language", type=Path, default=TM_LANGUAGE)
    parser.add_argument("--monaco", type=Path, default=MONACO)
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="'tm', 'monaco', 'both' (default: write files in place)",
    )
    args = parser.parse_args()
    tm_text, monaco_text = render_text(args.grammar)
    if args.output == "tm":
        print(tm_text, end="")
    elif args.output == "monaco":
        print(monaco_text, end="")
    elif args.output == "both":
        print("--- tmLanguage ---")
        print(tm_text, end="")
        print("--- monaco ---")
        print(monaco_text, end="")
    else:
        args.tm_language.write_text(tm_text, encoding="utf-8")
        args.monaco.write_text(monaco_text, encoding="utf-8")
        print(f"Editor grammars written to {args.tm_language} and {args.monaco}")


if __name__ == "__main__":
    main()
