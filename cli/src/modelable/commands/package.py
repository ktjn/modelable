from __future__ import annotations

from pathlib import Path

import click

from modelable.commands.common import console
from modelable.package_artifact import pack_package_artifact, unpack_package_artifact, verify_package_artifact
from modelable.package_manifest import PackageManifestError, load_package_manifest, serialize_package_manifest


def register_package_commands(cli_group: click.Group) -> None:
    cli_group.add_command(package)


@click.group()
def package() -> None:
    """Validate and inspect semantic package manifests."""


@package.command("validate")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def validate(path: Path) -> None:
    """Validate a semantic package manifest PATH offline."""
    try:
        manifest = load_package_manifest(path)
    except PackageManifestError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
    console.print(f"[green]OK[/green] package manifest is valid: {manifest.identity.name}@{manifest.identity.version}")


@package.command("inspect")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--format", "output_format", type=click.Choice(["json"]), default="json", show_default=True)
def inspect_manifest(path: Path, output_format: str) -> None:
    """Print a deterministic normalized representation of PATH."""
    del output_format
    try:
        manifest = load_package_manifest(path)
    except PackageManifestError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
    click.echo(serialize_package_manifest(manifest), nl=False)


@package.command("pack")
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--snapshot",
    "snapshot_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path(".modelable"),
    show_default=True,
)
@click.option("--out", "output_path", type=click.Path(path_type=Path), required=True)
def pack(manifest: Path, snapshot_dir: Path, output_path: Path) -> None:
    """Pack MANIFEST from a verified local registry snapshot."""
    try:
        digest = pack_package_artifact(manifest, snapshot_dir, output_path)
    except (OSError, PackageManifestError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
    console.print(f"[green]OK[/green] wrote package artifact {output_path} ({digest})")


@package.command("verify")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def verify(path: Path) -> None:
    """Verify a local modelable package artifact offline."""
    try:
        document = verify_package_artifact(path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
    package_info = document["package"]["package"]
    console.print(f"[green]OK[/green] package artifact is valid: {package_info['name']}@{package_info['version']}")


@package.command("unpack")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "output_dir", type=click.Path(path_type=Path), required=True)
def unpack(path: Path, output_dir: Path) -> None:
    """Verify and unpack a local modelable package artifact offline."""
    try:
        unpack_package_artifact(path, output_dir)
    except (OSError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise click.exceptions.Exit(1) from exc
    console.print(f"[green]OK[/green] unpacked package artifact to {output_dir}")
