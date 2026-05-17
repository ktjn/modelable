import sqlite3

from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema
from modelable.governance.por import DEFAULT_POR_ISSUER, build_por_reference, build_por_record
from modelable.registry.index import build_registry


def test_build_por_reference_is_unsigned_and_deterministic():
    por = build_por_reference("customer.Customer.v1")

    assert por == {
        "model": "customer.Customer.v1",
        "issuer": DEFAULT_POR_ISSUER,
        "issuedAt": "1970-01-01T00:00:00Z",
    }


def test_build_por_record_omits_signature_by_default():
    por = build_por_record("customer.Customer.v1").as_dict()

    assert por == {
        "model": "customer.Customer.v1",
        "issuer": DEFAULT_POR_ISSUER,
        "issuedAt": "1970-01-01T00:00:00Z",
    }


def test_registry_populates_por_log_and_json_schema_embeds_por_reference(tmp_path):
    source = tmp_path / "workspace.mdl"
    source.write_text(
        """
domain customer {
  owner: "customer-platform"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(source)
    registry_path = build_registry(workspace, tmp_path / ".modelable")

    with sqlite3.connect(registry_path) as conn:
        rows = conn.execute(
            "select model_ref, issuer, issued_at, signature from por_log order by model_ref"
        ).fetchall()

    assert rows == [
        ("customer.Customer.v1", DEFAULT_POR_ISSUER, "1970-01-01T00:00:00Z", None)
    ]

    artifacts = emit_json_schema(workspace, tmp_path / "out")
    schema = next(art.content for art in artifacts if art.ref == "customer.Customer@1")
    assert schema["x-modelable-por"] == {
        "model": "customer.Customer.v1",
        "issuer": DEFAULT_POR_ISSUER,
        "issuedAt": "1970-01-01T00:00:00Z",
    }
