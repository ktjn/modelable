from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from modelable.compiler.workspace import load_workspace
from modelable.diagnostics.model import render_diagnostic
from modelable.parser.ir import ParseError

console = Console()


def load_workspace_or_exit(path: Path):
    try:
        workspace = load_workspace(path)
    except FileNotFoundError:
        console.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)
    except ParseError as exc:
        console.print(f"[red]ERROR[/red] {render_diagnostic(exc.diagnostic(path=path))}")
        sys.exit(1)

    if workspace.errors:
        for diagnostic in workspace.errors:
            console.print(f"[red]ERROR[/red] {render_diagnostic(diagnostic)}", soft_wrap=True)
        sys.exit(1)

    return workspace


def render_version_spec(version_spec) -> str:
    kind = getattr(version_spec, "kind", None)
    if kind == "exact":
        return str(version_spec.version)
    if kind == "range":
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if kind == "min":
        return f">={version_spec.min_inclusive}"
    return "?"
