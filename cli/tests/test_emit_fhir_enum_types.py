"""FHIR profile emission tests for nominal enum-backed semantic declarations
(evolution plan E10)."""

from __future__ import annotations

import json
from pathlib import Path

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.emitters.fhir import emit_fhir_profile


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("clinical.mdl"), uri="file:///clinical.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


_FIXTURE = """
domain clinical {
  owner: "clinical-platform"
  semantic PatientStatus @ 1 (additive): enum(active, inactive)
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    status: PatientStatus @ 1
  }
  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    status <- p.status
  }
}
"""


def _elements_by_id(content: str) -> dict[str, dict]:
    doc = json.loads(content)
    return {el["id"]: el for el in doc["differential"]["element"]}


def test_enum_ref_field_maps_to_code_type_not_string(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")
    profile = next(a for a in artifacts if a.artifact_id == "clinical.PatientProfile.v1")
    elements = _elements_by_id(profile.content)
    value_element = elements["Patient.extension:status.value[x]"]
    assert value_element["type"] == [{"code": "code"}]


def test_enum_ref_field_gets_declaration_scoped_value_set_not_field_scoped(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")
    profile = next(a for a in artifacts if a.artifact_id == "clinical.PatientProfile.v1")
    elements = _elements_by_id(profile.content)
    value_element = elements["Patient.extension:status.value[x]"]
    assert value_element["binding"] == {
        "strength": "required",
        "valueSet": "http://modelable.io/fhir/ValueSet/clinical.PatientStatus",
    }


def test_extension_structure_definition_gets_matching_type_and_binding(tmp_path):
    workspace = _workspace(_FIXTURE)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")
    extension = next(a for a in artifacts if a.artifact_id == "clinical.PatientProfile.v1.ext.status")
    elements = _elements_by_id(extension.content)
    value_element = elements["Extension.value[x]"]
    assert value_element["type"] == [{"code": "code"}]
    assert value_element["binding"] == {
        "strength": "required",
        "valueSet": "http://modelable.io/fhir/ValueSet/clinical.PatientStatus",
    }


def test_two_fields_sharing_one_enum_declaration_share_one_value_set(tmp_path):
    workspace = _workspace(
        """
domain clinical {
  owner: "clinical-platform"
  semantic PatientStatus @ 1 (additive): enum(active, inactive)
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    status: PatientStatus @ 1
    priorStatus: PatientStatus @ 1
  }
  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    status <- p.status
    priorStatus <- p.priorStatus
  }
}
"""
    )
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")
    profile = next(a for a in artifacts if a.artifact_id == "clinical.PatientProfile.v1")
    elements = _elements_by_id(profile.content)
    status_value_set = elements["Patient.extension:status.value[x]"]["binding"]["valueSet"]
    prior_value_set = elements["Patient.extension:priorStatus.value[x]"]["binding"]["valueSet"]
    assert status_value_set == prior_value_set == "http://modelable.io/fhir/ValueSet/clinical.PatientStatus"


def test_anonymous_enum_keeps_field_scoped_value_set(tmp_path):
    workspace = _workspace(
        """
domain clinical {
  owner: "clinical-platform"
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    status: enum(active, inactive)
  }
  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    status <- p.status
  }
}
"""
    )
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")
    profile = next(a for a in artifacts if a.artifact_id == "clinical.PatientProfile.v1")
    elements = _elements_by_id(profile.content)
    value_element = elements["Patient.extension:status.value[x]"]
    assert value_element["binding"]["valueSet"] == "http://modelable.io/fhir/ValueSet/clinical.PatientProfile.status"
