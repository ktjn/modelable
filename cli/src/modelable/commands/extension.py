from __future__ import annotations

import json
from pathlib import Path

import click

from modelable.extension_host import ExtensionHostError, WasmExtensionHost, WasmExtensionLimits
from modelable.extensions import (
    ExtensionDescriptorError,
    ExtensionTrustPolicy,
    parse_extension_descriptor,
    parse_extension_pin,
)
from modelable.planner.protocol import PlanProtocolError, load_plan


def register_extension_commands(cli_group: click.Group) -> None:
    cli_group.add_command(extension)


@click.group()
def extension() -> None:
    """Execute explicitly trusted external extensions."""


@extension.command("run")
@click.argument("module", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--descriptor", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--pin", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--plan", "plan_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--configuration", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--virtual-file",
    "virtual_files",
    multiple=True,
    metavar="PATH=FILE",
    help="Expose a UTF-8 input file at virtual PATH; repeatable.",
)
@click.option(
    "--trust",
    is_flag=True,
    help="Explicitly trust the exact implementation identified by --pin for this invocation.",
)
@click.option("--fuel", type=click.IntRange(min=1), default=1_000_000, show_default=True)
@click.option("--max-memory-pages", type=click.IntRange(min=1), default=256, show_default=True)
@click.option("--max-output-bytes", type=click.IntRange(min=1), default=2 * 1024 * 1024, show_default=True)
def run(
    module: Path,
    descriptor: Path,
    pin: Path,
    plan_path: Path,
    configuration: Path | None,
    virtual_files: tuple[str, ...],
    trust: bool,
    fuel: int,
    max_memory_pages: int,
    max_output_bytes: int,
) -> None:
    """Run one WASM MODULE against a validated plan and print its result."""
    try:
        descriptor_payload = _load_json_object(descriptor, "extension descriptor")
        pin_payload = _load_json_object(pin, "extension pin")
        descriptor_value = parse_extension_descriptor(descriptor_payload)
        pin_value = parse_extension_pin(pin_payload)
        plan_value = load_plan(plan_path)
        configuration_value = (
            _load_json_object(configuration, "extension configuration") if configuration is not None else {}
        )
        virtual_file_values = _load_virtual_files(virtual_files)
        policy = ExtensionTrustPolicy(allowed_wasm_pins=(pin_value,)) if trust else ExtensionTrustPolicy()
        result = WasmExtensionHost(policy=policy).execute(
            module,
            descriptor=descriptor_value,
            pin=pin_value,
            plan=plan_value,
            configuration=configuration_value,
            virtual_files=virtual_file_values,
            limits=WasmExtensionLimits(
                fuel=fuel,
                max_memory_pages=max_memory_pages,
                max_output_bytes=max_output_bytes,
            ),
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ExtensionDescriptorError,
        PlanProtocolError,
        ExtensionHostError,
    ) as error:
        raise click.ClickException(str(error)) from error
    click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


def _load_json_object(path: Path, label: str) -> dict[str, object]:
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_virtual_files(specs: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for spec in specs:
        path, separator, source = spec.partition("=")
        if not separator or not path or not source:
            raise ValueError("--virtual-file must use PATH=FILE")
        if path in values:
            raise ValueError(f"duplicate virtual file path {path!r}")
        try:
            values[path] = Path(source).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ValueError(f"could not read virtual file {source!r}: {error}") from error
    return values


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_non_finite(value: str) -> object:
    raise ValueError(f"non-finite JSON number {value!r} is not allowed")
