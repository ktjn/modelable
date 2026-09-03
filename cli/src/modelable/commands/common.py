from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from modelable.compiler.workspace import load_workspace
from modelable.diagnostics.model import render_diagnostic
from modelable.parser.ir import ParseError, VersionPinned
from modelable.registry.sources import SourceAdapter

console = Console()


def load_workspace_or_exit(
    path: Path, *, source_adapter: SourceAdapter | None = None, output_console: Console | None = None
) -> Any:
    output = output_console or console
    try:
        workspace = source_adapter.load(path) if source_adapter is not None else load_workspace(path)
    except FileNotFoundError:
        output.print("[yellow]No .mdl files found.[/yellow]")
        sys.exit(0)
    except ParseError as exc:
        output.print(f"[red]ERROR[/red] {render_diagnostic(exc.diagnostic(path=str(path)))}")
        sys.exit(1)

    if workspace.errors:
        for diagnostic in workspace.errors:
            output.print(f"[red]ERROR[/red] {render_diagnostic(diagnostic)}", soft_wrap=True)
        sys.exit(1)

    for diagnostic in workspace.warnings:
        output.print(f"[yellow]WARNING[/yellow] {render_diagnostic(diagnostic)}", soft_wrap=True)

    return workspace


def render_version_spec(version_spec: Any) -> str:
    kind = getattr(version_spec, "kind", None)
    if kind == "exact":
        return str(version_spec.version)
    if kind == "range":
        return f">={version_spec.min_inclusive}<{version_spec.max_exclusive}"
    if kind == "min":
        return f">={version_spec.min_inclusive}"
    if isinstance(version_spec, VersionPinned):
        return f"{version_spec.version}#{version_spec.content_hash}"
    return "?"
