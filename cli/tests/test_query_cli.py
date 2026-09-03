import json
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli


def test_query_cli_answers_query_v1_request(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "$schema": "modelable.query/v1",
                "kind": "query",
                "query": "declaration",
                "id": "customer.Customer@1",
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["query", str(source), "--request", str(request)])

    assert result.exit_code == 0, result.output
    response = json.loads(result.output)
    assert response["$schema"] == "modelable.query/v1"
    assert response["data"]["nodes"][0]["target_ref"] == "customer.Customer@1"


def test_query_cli_accepts_json_request_over_stdio(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    request = {
        "$schema": "modelable.query/v1",
        "kind": "query",
        "query": "declaration",
        "id": "customer.Customer@1",
    }

    result = CliRunner().invoke(cli, ["query", str(source), "--request", "-"], input=json.dumps(request))

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["query"] == "declaration"


def test_query_cli_exposes_explicit_lifecycle_metadata(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "$schema": "modelable.query/v1",
                "kind": "query",
                "query": "lifecycle",
                "id": "customer.Customer@1",
            }
        ),
        encoding="utf-8",
    )
    lifecycle = tmp_path / "lifecycle.json"
    lifecycle.write_text(
        json.dumps(
            {
                "$schema": "modelable.lifecycle/v1",
                "entries": [{"identity": "customer.Customer@1", "state": "published"}],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["query", str(source), "--request", str(request), "--lifecycle", str(lifecycle)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"] == {"identity": "customer.Customer@1", "state": "published"}


def test_query_cli_exposes_explicit_migration_lineage(tmp_path: Path) -> None:
    source = tmp_path / "workspace.mdl"
    source.write_text(
        'domain customer { owner: "team" entity Customer @ 1 (additive) { @key customerId: uuid } }',
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "$schema": "modelable.query/v1",
                "kind": "query",
                "query": "lineage",
                "id": "customer.Customer@1",
            }
        ),
        encoding="utf-8",
    )
    migration = tmp_path / "migration.json"
    migration.write_text(
        json.dumps(
            {
                "$schema": "modelable.migration/v1",
                "mappings": [{"kind": "rename", "sources": ["legacy.Customer@1"], "targets": ["customer.Customer@1"]}],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["query", str(source), "--request", str(request), "--migration", str(migration)],
    )

    assert result.exit_code == 0, result.output
    assert result.output.count('"kind": "migrates_to"') == 1
