from pathlib import Path

from modelable.parser.ir import AnnWire
from modelable.parser.parse import parse_text_to_ir
from modelable.compiler.workspace import load_workspace
from modelable.emitters.json_schema import emit_json_schema
from modelable.llm.render import render_mdl
from modelable.emitters.typescript import emit_typescript


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
        artifact
        for artifact in emit_typescript(workspace, tmp_path / "out")
        if artifact.ref == "metrics.Span@1"
    )

    assert "startTimeUnixNano: string;" in artifact.content
