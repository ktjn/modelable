from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console, load_workspace_or_exit
from modelable.graph.export import build_graph_export, write_graph_export


def register_graph_commands(cli_group: click.Group) -> None:
    cli_group.add_command(graph)


@click.group()
def graph() -> None:
    """Graph export commands for the normalized workspace graph."""


@graph.command(name="export")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--path",
    "path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Workspace path to load instead of SOURCE.",
)
@click.option(
    "--focus",
    "focus",
    default=None,
    help="Optional model or projection ref to center the graph.",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Output file for the canonical graph JSON.",
)
def export_graph(source: Path, path: Path | None, focus: str | None, out_path: Path) -> None:
    """Export the normalized workspace graph as deterministic JSON."""
    workspace = load_workspace_or_exit(path or source)
    graph_export = build_graph_export(workspace, focus=focus)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_graph_export(graph_export, out_path)
    console.print(f"[green]OK[/green] wrote {out_path}")
