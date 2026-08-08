"""docs/grammar.md must stay in sync with the canonical modelable.lark grammar."""

import subprocess
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
GRAMMAR = CLI_ROOT / "src" / "modelable" / "grammar" / "modelable.lark"
DOCS_GRAMMAR = REPO_ROOT / "docs" / "grammar.md"


def test_grammar_page_is_up_to_date() -> None:
    script = CLI_ROOT / "scripts" / "render_language_grammar.py"
    result = subprocess.run(
        [sys.executable, str(script), "--grammar", str(GRAMMAR), "--output", "-"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert DOCS_GRAMMAR.read_text(encoding="utf-8") == result.stdout


def test_grammar_page_is_referenced_from_nav() -> None:
    nav = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "grammar.md" in nav
