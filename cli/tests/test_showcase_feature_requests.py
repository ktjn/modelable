from __future__ import annotations

import json

from modelable.compiler.workspace import load_workspace
from modelable.emitters.registry_manifest import emit_registry_manifest
from modelable.emitters.sql import emit_sql
from modelable.planner.planner import expand_auto_projections


def test_postgres_emits_keys_value_objects_and_foreign_keys(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain scheduling {
  owner: "test-team"
  value Contact @ 1 (additive) {
    email: string
  }
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    contact: Contact
  }
  entity Appointment @ 1 (additive) {
    @key appointmentId: uuid
    patient: ref<scheduling.Patient@1>
  }
  projection PatientDb @ 1 from scheduling.Patient @ 1 as patient {
    patientId <- patient.patientId
    contact <- patient.contact
  }
  projection AppointmentDb @ 1 from scheduling.Appointment @ 1 as appointment {
    appointmentId <- appointment.appointmentId
    patient <- appointment.patient
  }
}

binding patient-table {
  model: scheduling.Patient @ 1
  adapter: postgres
  table: "patient_db"
}
binding appointment-table {
  model: scheduling.Appointment @ 1
  adapter: postgres
  table: "appointment_db"
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    patient = next(artifact for artifact in artifacts if artifact.ref == "scheduling.PatientDb@1")
    appointment = next(artifact for artifact in artifacts if artifact.ref == "scheduling.AppointmentDb@1")

    assert "patient_id UUID NOT NULL PRIMARY KEY" in patient.content
    assert "contact JSONB NOT NULL" in patient.content
    assert "appointment_id UUID NOT NULL PRIMARY KEY" in appointment.content
    assert "FOREIGN KEY (patient) REFERENCES patient_db (patient_id)" in appointment.content


def test_request_auto_projection_drops_server_owned_key():
    from modelable.parser.parse import parse_text_to_ir

    mdl = parse_text_to_ir(
        """
domain catalog {
  owner: "test-team"
  entity Product @ 1 (additive) {
    @key @server productId: uuid
    name: string
  }
  auto projections Product @ 1 { request }
}
"""
    )
    assert expand_auto_projections(mdl) == []
    fields = {field.name for field in mdl.domains[0].projections["ProductRequest"][0].fields}
    assert fields == {"name"}


def test_registry_manifest_is_deterministic_and_complete(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  owner: "test-team"
  semantic TenantId : uuid { registry: true }
  entity Tenant @ 1 (additive) {
    @key id: TenantId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifact = emit_registry_manifest(workspace, tmp_path / "out", registry_ids={"platform.TenantId": 7})[0]
    payload = json.loads(artifact.content)
    assert payload["format"] == "modelable.registry.v1"
    assert [entry["ref"] for entry in payload["contracts"]] == ["platform.Tenant@1", "platform.TenantId"]
    assert payload["contracts"][1]["registry_id"] == 7
