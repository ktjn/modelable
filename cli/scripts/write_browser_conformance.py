from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

from modelable.browser import BrowserCompiler, BrowserSource

SCENARIOS: dict[str, tuple[str, ...]] = {
    "invalid-parse": ("invalid-parse.mdl",),
    "invalid-reference": ("invalid-reference.mdl",),
    "invalid-semantic": ("invalid-semantic.mdl",),
    "multi-domain": ("multi-domain-customer.mdl", "multi-domain-order.mdl"),
    "single-valid": ("single-valid.mdl",),
}
VALID_SCENARIOS = {"multi-domain", "single-valid"}


def _json_value(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sources(fixture_root: Path, names: tuple[str, ...]) -> tuple[BrowserSource, ...]:
    return tuple(
        BrowserSource(
            uri=f"fixture:///{name}",
            text=(fixture_root / name).read_text(encoding="utf-8"),
            version=1,
        )
        for name in names
    )


def write_snapshots(fixture_root: Path, output: Path) -> None:
    compiler = BrowserCompiler()
    output.mkdir(parents=True, exist_ok=True)

    for scenario, names in SCENARIOS.items():
        sources = _sources(fixture_root, names)
        snapshot: dict[str, object] = {
            "open": _json_value(compiler.open_workspace(sources)),
        }
        if scenario == "single-valid":
            snapshot["format"] = _json_value(compiler.format_source(sources[0]))
        if scenario in VALID_SCENARIOS:
            snapshot["compile"] = _json_value(compiler.compile_json_schema(sources))
        (output / f"{scenario}.json").write_text(
            json.dumps(
                snapshot,
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Write native browser compiler conformance snapshots.")
    default_fixtures = Path(__file__).parents[1] / "tests" / "conformance" / "browser"
    parser.add_argument("--fixtures", type=Path, default=default_fixtures)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_snapshots(args.fixtures, args.output)


if __name__ == "__main__":
    main()
