from __future__ import annotations
import json
from pathlib import Path
import click
from modelable.commands.common import console
from modelable.runtime.adapter import get_adapter

def register_runtime_commands(cli_group: click.Group) -> None:
    cli_group.add_command(runtime)

@click.group()
def runtime() -> None:
    """Manage runtime adapter operations."""
    pass

@runtime.command()
@click.option("--adapter", required=True, help="Adapter type (e.g., postgres)")
@click.option("--config", required=True, type=click.Path(exists=True), help="Path to adapter configuration JSON")
def bootstrap(adapter: str, config: str) -> None:
    """Initialize a runtime adapter environment."""
    try:
        adapter_instance = get_adapter(adapter)
        config_path = Path(config)
        with open(config_path, "r") as f:
            config_data = json.load(f)
        
        adapter_instance.bootstrap(config_data)
        console.print(f"[green]OK[/green] Bootstrapped {adapter}.")
    except Exception as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.ClickException(str(exc))
