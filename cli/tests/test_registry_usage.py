from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.registry.usage import build_usage_graph, build_usage_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "customer.mdl"


def test_usage_graph_contains_exact_model_signatures() -> None:
    graph = build_usage_graph(load_workspace(FIXTURE))

    models = [node for node in graph["nodes"] if node["kind"] == "model_version"]

    assert graph["kind"] == "usage_graph"
    assert graph["application"] == "workspace"
    assert [node["target_ref"] for node in models] == ["customer.Customer@1", "customer.Customer@2"]
    assert all(len(node["signature"]) == 64 for node in models)


def test_usage_manifest_is_compact() -> None:
    manifest = build_usage_manifest(load_workspace(FIXTURE))

    assert manifest["kind"] == "usage_manifest"
    assert all(set(reference) == {"ref", "signature"} for reference in manifest["references"])


def test_usage_cli_emits_json() -> None:
    result = CliRunner().invoke(cli, ["registry", "usage", str(FIXTURE), "--format", "manifest"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "usage_manifest"
