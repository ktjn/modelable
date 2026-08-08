"""Editor grammar keyword/type lists must stay in sync with modelable.lark."""

import subprocess
import sys
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLI_ROOT.parent
GRAMMAR = CLI_ROOT / "src" / "modelable" / "grammar" / "modelable.lark"
TM_LANGUAGE = REPO_ROOT / "vscode" / "syntaxes" / "modelable.tmLanguage.json"
MONACO_PROVIDERS = REPO_ROOT / "web" / "src" / "language" / "monaco-providers.ts"
SCRIPT = CLI_ROOT / "scripts" / "render_editor_grammars.py"


def _render(mode: str) -> str:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--grammar", str(GRAMMAR), "--output", mode],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_tm_language_keywords_match_grammar() -> None:
    assert TM_LANGUAGE.read_text(encoding="utf-8") == _render("tm")


def test_monaco_providers_match_grammar() -> None:
    assert MONACO_PROVIDERS.read_text(encoding="utf-8") == _render("monaco")


def test_editor_lists_contain_pick_and_omit() -> None:
    keywords = _render("tm")
    assert "pick" in keywords
    assert "omit" in keywords
