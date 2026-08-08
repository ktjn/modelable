"""Every ```mdl fenced block in the language reference must parse as Modelable.

This is the docs-as-tests gate. It catches documentation drift where an example
uses syntax the canonical grammar (`modelable.lark`) no longer accepts. Blocks
are parsed directly first; if that fails they are retried wrapped in a `domain`
block, then in a `domain { entity ... }` block, since many examples illustrate
domain-level or model-level fragments without the enclosing declaration.

Genuinely illustrative templates (e.g. `@annotation fieldName: Type`) and
placeholder blocks containing `...` are skipped via the allowlist below.
"""

import re
from pathlib import Path

import pytest

from modelable.parser.parse import parse_text

REPO_ROOT = Path(__file__).resolve().parents[2]
LANGUAGE_REFERENCE = REPO_ROOT / "docs" / "language-reference.md"

FENCE = re.compile(r"^```mdl\s*$\n(.*?)^```\s*$", re.M | re.S)

# Blocks that are deliberately not parseable: prose-level syntax templates.
# Keyed by the exact first non-empty line of the fence body.
ALLOWLIST_FIRST_LINES = {
    "@annotation  fieldName:  Type",  # §2.2 field declaration template
}


def _extract_blocks(text: str) -> list[tuple[int, str]]:
    blocks: list[tuple[int, str]] = []
    for match in FENCE.finditer(text):
        line = text[: match.start()].count("\n") + 1
        body = match.group(1)
        blocks.append((line, body))
    return blocks


def _first_line(body: str) -> str:
    return next((line for line in body.splitlines() if line.strip()), "").strip()


def _try_parse(body: str) -> Exception | None:
    for wrapped in (
        body,
        f"domain __docs {{\n{body}\n}}",
        f"domain __docs {{\n  entity __E @ 1 {{\n{body}\n  }}\n}}",
    ):
        try:
            parse_text(wrapped)
            return None
        except Exception as exc:
            last_error = exc
    return last_error


@pytest.mark.parametrize("_line,body", _extract_blocks(LANGUAGE_REFERENCE.read_text(encoding="utf-8")))
def test_doc_example_parses(_line: int, body: str) -> None:
    if "..." in body or _first_line(body) in ALLOWLIST_FIRST_LINES:
        pytest.skip("illustrative template or placeholder block")
    error = _try_parse(body)
    assert error is None, f"docs/language-reference.md example (starting line {_line}) does not parse: {error}"
