import json

from click.testing import CliRunner

from modelable.cli import cli


def test_capabilities_text_output_lists_every_category():
    result = CliRunner().invoke(cli, ["capabilities"])

    assert result.exit_code == 0
    assert "target" in result.output
    assert "sql_dialect" in result.output
    assert "model_kind" in result.output
    assert "annotation" in result.output
    assert "deferred_feature" in result.output
    assert "typescript" in result.output
    assert "composite-keys" in result.output


def test_capabilities_json_output_is_valid_and_complete():
    result = CliRunner().invoke(cli, ["capabilities", "--format", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    assert "typescript" in names
    assert "postgres" in names
    assert "entity" in names
    assert "key" in names
    assert "composite-keys" in names
    for entry in payload:
        assert set(entry) == {"name", "category", "status", "description", "notes"}


def test_capabilities_json_output_marks_deferred_features():
    result = CliRunner().invoke(cli, ["capabilities", "--format", "json"])

    payload = json.loads(result.output)
    composite_keys = next(entry for entry in payload if entry["name"] == "composite-keys")
    assert composite_keys["status"] == "deferred"
    assert composite_keys["notes"]
