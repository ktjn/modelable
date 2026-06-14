import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema
from modelable.emitters.rust import emit_rust
from modelable.emitters.typescript import emit_typescript
from modelable.llm.render import render_mdl
from modelable.parser.ir import AnnWire
from modelable.parser.parse import parse_text_to_ir


def test_transform_wire_annotation():
    mdl = parse_text_to_ir(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string", rust.type: "u64")
            startTimeUnixNano: int
          }
        }
        """
    )

    field = mdl.domains[0].models["Span"][0].fields[1]
    wire = next(annotation for annotation in field.annotations if isinstance(annotation, AnnWire))

    assert wire.targets["json"].encoding == "string"
    assert wire.targets["rust"].type == "u64"


def test_render_wire_annotation_round_trip():
    mdl = parse_text_to_ir(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string", rust.type: "u64")
            startTimeUnixNano: int
          }
        }
        """
    )

    rendered = render_mdl(mdl)

    assert '@wire(json: "string", rust.type: "u64")' in rendered


def test_multiple_wire_annotations_are_merged_for_emitters():
    mdl = parse_text_to_ir(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string")
            @wire(rust.type: "u64")
            startTimeUnixNano: int
          }
        }
        """
    )

    field = mdl.domains[0].models["Span"][0].fields[1]

    assert field.wire_targets()["json"].encoding == "string"
    assert field.wire_targets()["rust"].type == "u64"


def test_conflicting_wire_annotations_raise():
    mdl = parse_text_to_ir(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string")
            @wire(json: "binary")
            startTimeUnixNano: int
          }
        }
        """
    )

    field = mdl.domains[0].models["Span"][0].fields[1]

    with pytest.raises(ValueError):
        field.wire_targets()


def test_emit_json_schema_honors_json_wire_string(tmp_path):
    mdl = tmp_path / "wire.mdl"
    mdl.write_text(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string")
            startTimeUnixNano: int
          }
        }
        """,
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    schema = next(
        artifact.content
        for artifact in emit_json_schema(workspace, tmp_path / "out")
        if artifact.ref == "metrics.Span@1"
    )

    assert schema["properties"]["startTimeUnixNano"]["type"] == "string"
    assert schema["properties"]["startTimeUnixNano"]["x-modelable-wire"]["json"]["encoding"] == "string"


def test_emit_typescript_honors_json_wire_string(tmp_path):
    mdl = tmp_path / "wire.mdl"
    mdl.write_text(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string")
            startTimeUnixNano: int
          }
        }
        """,
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifact = next(
        artifact for artifact in emit_typescript(workspace, tmp_path / "out") if artifact.ref == "metrics.Span@1"
    )

    assert "startTimeUnixNano: string;" in artifact.content


def test_emit_typescript_does_not_apply_json_wire_to_array_items(tmp_path):
    mdl = tmp_path / "wire.mdl"
    mdl.write_text(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            @wire(json: "string")
            samples: array<int>
          }
        }
        """,
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifact = next(
        artifact for artifact in emit_typescript(workspace, tmp_path / "out") if artifact.ref == "metrics.Span@1"
    )

    assert "samples: number[];" in artifact.content


def test_emit_rust_honors_inline_object_wire_hints(tmp_path):
    mdl = tmp_path / "wire.mdl"
    mdl.write_text(
        """
        domain metrics {
          owner: "test-team"
          entity Span @ 1 (additive) {
            @key spanId: string
            payload: object {
              @wire(rust.type: "u64")
              count: int
            }
          }
        }
        """,
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifact = next(artifact for artifact in emit_rust(workspace, tmp_path / "out") if artifact.ref == "metrics.Span@1")

    assert "pub count: u64," in artifact.content


def test_render_wire_annotation_rejects_empty_targets():
    from modelable.parser.ir import AnnWire

    with pytest.raises(ValueError):
        AnnWire(targets={})
