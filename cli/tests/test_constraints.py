from pathlib import Path

from modelable.compiler.render import render_mdl
from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema


def test_constraints_round_trip_and_emit_json_schema(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """domain customer {
  owner: "customer-team"
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    age: int constraint { min: 0, max: 150 }
    code: string constraint { min_length: 2, max_length: 8, pattern: "^[A-Z]+$" }
    tags: array<string> constraint { min_items: 1, unique_items: true }
  }
}""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    assert not workspace.errors
    fields = workspace.mdl.domains[0].models["Customer"][0].fields
    assert [(item.kind, item.value) for item in fields[1].constraints] == [("min", 0), ("max", 150)]
    rendered = render_mdl(workspace.mdl)
    assert "constraint { min: 0, max: 150 }" in rendered
    artifacts = emit_json_schema(workspace, tmp_path / "out")
    customer = next(artifact for artifact in artifacts if artifact.ref == "customer.Customer@1")
    assert customer.content["properties"]["age"]["minimum"] == 0
    assert customer.content["properties"]["tags"]["uniqueItems"] is True


def test_named_enum_semantic_type_emits_as_reusable_enum(tmp_path: Path) -> None:
    source = tmp_path / "customer.mdl"
    source.write_text(
        """domain customer {
  owner: "customer-team"
  semantic CustomerStatus: enum(active, blocked)
  entity Customer @ 1 (additive) {
    @key
    customerId: uuid
    status: CustomerStatus
  }
}""",
        encoding="utf-8",
    )
    workspace = load_workspace(source)
    assert not workspace.errors
    artifact = next(item for item in emit_json_schema(workspace, tmp_path / "out") if item.ref == "customer.Customer@1")
    assert artifact.content["properties"]["status"] == {"type": "string", "enum": ["active", "blocked"]}
