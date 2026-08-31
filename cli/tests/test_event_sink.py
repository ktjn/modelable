from __future__ import annotations

import json

from modelable.compiler.workspace import load_workspace
from modelable.emitters.event_sink import emit_event_sink
from modelable.planner.plans import build_plan_documents
from modelable.planner.protocol import PLAN_V1_SCHEMA

_MODEL = """
domain booking {
  entity Appointment @ 1 (additive) {
    @key
    appointmentId: uuid
    status: string
  }

  auto projections Appointment @ 1 {
    event on [created, deleted]
  }
}
"""


def test_event_sink_requests_v1_plan_documents(tmp_path, monkeypatch):
    (tmp_path / "booking.mdl").write_text(_MODEL, encoding="utf-8")
    workspace = load_workspace(tmp_path)
    observed: list[dict[str, object]] = []

    def observe_plan_request(workspace, **kwargs):
        observed.append(kwargs)
        return build_plan_documents(workspace, **kwargs)

    monkeypatch.setattr("modelable.emitters.event_sink.build_plan_documents", observe_plan_request)

    emit_event_sink(workspace, tmp_path / "out")

    assert observed == [{"schema": PLAN_V1_SCHEMA}]


def test_event_sink_emits_envelope_outbox_and_event_payload_schema(tmp_path):
    (tmp_path / "booking.mdl").write_text(_MODEL, encoding="utf-8")

    artifacts = emit_event_sink(load_workspace(tmp_path), tmp_path / "out")

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.path == tmp_path / "out" / "event-sink.json"
    document = json.loads(artifact.content)
    assert document["format"] == "modelable.event-sink.v1"
    assert document["envelope"]["required"] == [
        "domain",
        "model",
        "version",
        "operation",
        "key",
        "timestamp",
        "payload",
    ]
    event = document["events"][0]
    assert event["channel"] == "booking.Appointment.events.v1"
    assert event["operations"] == ["insert", "delete"]
    assert event["payload_schema"]["$ref"] in {
        f"#/components/schemas/{schema_id}" for schema_id in document["components"]["schemas"]
    }
    assert document["outbox"]["delivery"] == "transactional"
