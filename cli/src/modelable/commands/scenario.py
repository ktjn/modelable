from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import click
from rich.console import Console

console = Console()

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCENARIOS_DIR = _REPO_ROOT / "samples" / "scenarios"
_SAMPLES_README = _REPO_ROOT / "samples" / "README.md"
_ROW_PATTERN = re.compile(
    r"^\|\s*\d+\s*\|\s*`(?P<id>[^`]+)`\s*\|\s*(?P<title>[^|]+?)\s*\|",
    re.MULTILINE,
)


@dataclass(frozen=True)
class ScenarioInfo:
    scenario_id: str
    title: str
    path: Path


def register_scenario_commands(cli_group: click.Group) -> None:
    cli_group.add_command(scenario)


@click.group()
def scenario() -> None:
    """Browse and load bundled sample scenarios."""


@scenario.command(name="list")
def list_scenarios() -> None:
    """List bundled scenario IDs and titles."""
    for index, info in enumerate(_load_scenarios(), start=1):
        console.print(f"{index}. {info.scenario_id} - {info.title}")


@scenario.command(name="show")
@click.argument("scenario_id")
def show_scenario(scenario_id: str) -> None:
    """Show the contents of a bundled sample scenario."""
    info = _find_scenario(scenario_id)
    if info is None:
        raise click.ClickException(f"unknown scenario: {scenario_id}")

    console.print(f"{info.scenario_id} - {info.title}")
    for path in _scenario_files(info.path):
        console.print(f"[bold]{path.name}[/bold]")
        console.print(path.read_text(encoding="utf-8").rstrip())


@scenario.command(name="load")
@click.argument("scenario_id")
@click.option(
    "--output-dir",
    "output_dir",
    type=click.Path(path_type=Path),
    default=Path("."),
    show_default=True,
    help="Destination directory for the copied scenario.",
)
def load_scenario(scenario_id: str, output_dir: Path) -> None:
    """Copy a bundled sample scenario into a working directory."""
    info = _find_scenario(scenario_id)
    if info is None:
        raise click.ClickException(f"unknown scenario: {scenario_id}")

    target = output_dir / scenario_id
    shutil.copytree(info.path, target)
    console.print(f"[green]OK[/green] wrote {target}")


def _load_scenarios() -> list[ScenarioInfo]:
    titles = _parse_readme_titles()
    infos: list[ScenarioInfo] = []
    for scenario_dir in sorted(
        [path for path in _SCENARIOS_DIR.iterdir() if path.is_dir()],
        key=lambda path: path.name,
    ):
        title = titles.get(scenario_dir.name, scenario_dir.name)
        infos.append(ScenarioInfo(scenario_dir.name, title, scenario_dir))
    return infos


def _parse_readme_titles() -> dict[str, str]:
    if not _SAMPLES_README.exists():
        return {}
    text = _SAMPLES_README.read_text(encoding="utf-8")
    return {match.group("id"): match.group("title").strip() for match in _ROW_PATTERN.finditer(text)}


def _find_scenario(scenario_id: str) -> ScenarioInfo | None:
    return next((info for info in _load_scenarios() if info.scenario_id == scenario_id), None)


def _scenario_files(path: Path) -> list[Path]:
    return sorted(path.glob("*.mdl"), key=lambda item: item.name)
