from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import modelable.browser.dispatch as browser_dispatch
from modelable.browser import dispatch_browser_request

FIXTURE_ROOT = Path(__file__).parent / "conformance" / "browser"
LANGUAGE_FIXTURE_ROOT = Path(__file__).parent / "conformance" / "language"
SNAPSHOT_ROOT = FIXTURE_ROOT / "snapshots"
GENERATOR = Path(__file__).parents[1] / "scripts" / "write_browser_conformance.py"
SNAPSHOT_NAMES = (
    "invalid-parse.json",
    "invalid-reference.json",
    "invalid-semantic.json",
    "multi-domain.json",
    "single-valid.json",
)


def _generate(output: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--fixtures",
            str(FIXTURE_ROOT),
            "--output",
            str(output),
        ],
        check=True,
    )


def _collect_strings(
    value: object,
    strings: list[str],
    uris: list[str],
    portable_strings: list[str],
    key: str | None = None,
) -> None:
    if isinstance(value, str):
        strings.append(value)
        if key != "content":
            portable_strings.append(value)
        if key == "uri":
            uris.append(value)
    elif isinstance(value, list):
        for item in value:
            _collect_strings(item, strings, uris, portable_strings, key)
    elif isinstance(value, dict):
        for item_key, item in value.items():
            assert "duration" not in item_key.lower()
            assert "timing" not in item_key.lower()
            _collect_strings(item, strings, uris, portable_strings, item_key)


def test_native_browser_snapshots_are_deterministic(tmp_path: Path) -> None:
    generated = tmp_path / "snapshots"

    _generate(generated)

    assert tuple(path.name for path in sorted(generated.glob("*.json"))) == SNAPSHOT_NAMES
    for name in SNAPSHOT_NAMES:
        assert (generated / name).read_bytes() == (SNAPSHOT_ROOT / name).read_bytes()


def test_native_browser_snapshots_are_portable_and_sanitized() -> None:
    checkout = str(Path(__file__).parents[2].resolve())
    forbidden = (checkout, checkout.replace("\\", "/"), "Traceback")

    paths = sorted(SNAPSHOT_ROOT.glob("*.json"))
    assert tuple(path.name for path in paths) == SNAPSHOT_NAMES
    for path in paths:
        text = path.read_text(encoding="utf-8")
        snapshot = json.loads(text)
        strings: list[str] = []
        uris: list[str] = []
        portable_strings: list[str] = []

        _collect_strings(snapshot, strings, uris, portable_strings)
        assert text.endswith("\n")
        assert not any(value in item for item in strings for value in forbidden)
        assert not any(marker in item.lower() for item in strings for marker in ("duration", "timing"))
        assert not any("\\" in uri for uri in uris)
        assert not any("\\" in item for item in portable_strings)


def test_reference_scenario_records_a_reference_diagnostic() -> None:
    snapshot = json.loads((SNAPSHOT_ROOT / "invalid-reference.json").read_text(encoding="utf-8"))

    assert snapshot["open"]["diagnostics"]
    assert any("reference" in diagnostic["message"] for diagnostic in snapshot["open"]["diagnostics"])


def _dispatch(method: str, payload: object) -> dict:
    return json.loads(dispatch_browser_request(method, json.dumps(payload)))


def _language_fixture(name: str) -> dict:
    return json.loads((LANGUAGE_FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_language_valid_fixture_conforms_for_completion_and_hover() -> None:
    browser_dispatch._reset_compiler_for_tests()
    fixture = _language_fixture("workspace-valid.json")

    opened = _dispatch("workspace.open", fixture["workspace"])
    completion = _dispatch("language.completion", fixture["completion"]["request"])
    hover = _dispatch("language.hover", fixture["hover"]["request"])

    assert opened["result"]["diagnostics"] == []
    assert [item["label"] for item in completion["result"]["items"]] == fixture["completion"]["labels"]
    assert fixture["hover"]["markdownContains"] in hover["result"]["hover"]["markdown"]


def test_language_valid_fixture_conforms_for_definition() -> None:
    browser_dispatch._reset_compiler_for_tests()
    fixture = _language_fixture("workspace-valid.json")
    _dispatch("workspace.open", fixture["workspace"])

    result = _dispatch("language.definition", fixture["definition"]["request"])

    assert result["ok"] is True
    location = result["result"]["location"]
    assert location is not None
    assert location["uri"] == fixture["definition"]["expectLocation"]["uri"]
    assert location["range"]["start"]["line"] == fixture["definition"]["expectLocation"]["line"]


def test_language_valid_fixture_conforms_for_references() -> None:
    browser_dispatch._reset_compiler_for_tests()
    fixture = _language_fixture("workspace-valid.json")
    _dispatch("workspace.open", fixture["workspace"])

    result = _dispatch("language.references", fixture["references"]["request"])

    assert result["ok"] is True
    assert len(result["result"]["locations"]) >= fixture["references"]["minCount"]


def test_language_valid_fixture_conforms_for_prepare_rename() -> None:
    browser_dispatch._reset_compiler_for_tests()
    fixture = _language_fixture("workspace-valid.json")
    _dispatch("workspace.open", fixture["workspace"])

    result = _dispatch("language.prepareRename", fixture["prepareRename"]["request"])

    assert result["ok"] is True
    assert result["result"]["prepared"] is not None
    assert result["result"]["prepared"]["placeholder"] == fixture["prepareRename"]["expectPlaceholder"]


def test_language_valid_fixture_conforms_for_rename() -> None:
    browser_dispatch._reset_compiler_for_tests()
    fixture = _language_fixture("workspace-valid.json")
    _dispatch("workspace.open", fixture["workspace"])

    result = _dispatch("language.rename", fixture["rename"]["request"])

    assert result["ok"] is True
    edits = result["result"]["edit"]["edits"]
    assert len(edits) >= fixture["rename"]["minEdits"]
    assert all(edit["new_text"] == fixture["rename"]["expectNewText"] for edit in edits)


def test_language_invalid_current_fixture_keeps_last_parseable_results() -> None:
    browser_dispatch._reset_compiler_for_tests()
    valid = _language_fixture("workspace-valid.json")
    invalid = _language_fixture("workspace-invalid-current.json")
    _dispatch("workspace.open", valid["workspace"])

    opened = _dispatch("workspace.open", invalid["workspace"])
    completion = _dispatch("language.completion", invalid["completion"]["request"])
    hover = _dispatch("language.hover", invalid["hover"]["request"])

    assert opened["result"]["diagnostics"][0]["code"] == "PARSE"
    assert [item["label"] for item in completion["result"]["items"]] == invalid["completion"]["labels"]
    assert invalid["hover"]["markdownContains"] in hover["result"]["hover"]["markdown"]
