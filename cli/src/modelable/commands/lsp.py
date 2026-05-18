from __future__ import annotations

import click

from modelable.lsp.server import main as run_lsp


def register_lsp_commands(cli_group: click.Group) -> None:
    cli_group.add_command(lsp)


@click.command()
def lsp() -> None:
    """Start the Modelable language server over stdio."""
    run_lsp()

