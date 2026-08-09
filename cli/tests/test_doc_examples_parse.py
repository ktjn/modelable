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

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
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


def _synthesize_validatable_doc(body: str) -> str | None:
    """Build a self-contained workspace document from a projection selection block.

    Only blocks that declare a `pick(...)`/`omit(...)` clause and reference a
    `domain.Model` primary source are handled. The referenced source is
    materialized as a local entity carrying every field the block names via the
    source alias (plus a key), so the block can be validated for real by the
    compiler rather than merely parsed. Returns ``None`` when the block is not a
    validatable projection selection example.
    """
    if "pick(" not in body and "omit(" not in body:
        return None
    match = re.search(r"\bfrom\s+(\w+)\.(\w+)\s*@\s*(\d+)\s+as\s+(\w+)", body)
    if match is None:
        return None
    domain, model, version, alias = match.groups()

    source_fields = set(re.findall(rf"\b{alias}\.(\w+)", body))
    source_fields.add("__id")
    field_lines = "\n".join(f"    {name}: string" for name in sorted(source_fields))

    indented = "\n".join(f"  {line}" if line.strip() else line for line in body.splitlines())
    return (
        f"domain {domain} {{\n"
        f'  owner: "test-team"\n'
        f"  entity {model} @ {version} (additive) {{\n"
        f"    @key __id: string\n"
        f"{field_lines}\n"
        f"  }}\n"
        f"{indented}\n"
        f"}}\n"
    )


@pytest.mark.parametrize("_line,body", _extract_blocks(LANGUAGE_REFERENCE.read_text(encoding="utf-8")))
def test_doc_projection_selection_examples_validate(_line: int, body: str) -> None:
    """Projection `pick`/`omit` examples must be semantically valid, not just parse.

    Guards against a documented example drifting back into the contradiction
    where a selection clause result collides with a declared body field (e.g. an
    `omit(...)` body that redeclares retained source fields).
    """
    if "..." in body:
        pytest.skip("illustrative template or placeholder block")
    doc = _synthesize_validatable_doc(body)
    if doc is None:
        pytest.skip("block is not a projection selection example (not semantically validated)")
    assert isinstance(doc, str)
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri=f"inmemory://docs-example-{_line}.mdl",
                text=doc,
            )
        ]
    )
    assert workspace.errors == [], (
        f"docs/language-reference.md projection example (starting line {_line}) does not validate: "
        f"{[d.message for d in workspace.errors]}"
    )
