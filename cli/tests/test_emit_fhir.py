from __future__ import annotations

import json

from modelable.compiler.workspace import load_workspace
from modelable.emitters.fhir import emit_fhir_profile


def test_emit_fhir_profile_builds_r4_structure_definition_elements(tmp_path):
    (tmp_path / "clinical.mdl").write_text(
        """
domain clinical {
  owner: "clinical-platform"
  contact: "clinical@example.com"
  description: "Clinical model contracts"

  entity Patient @ 1 (additive) {
    @key patientId: uuid
    @pii @classification("confidential") birthDate?: date
    active: bool
    status: enum(active, inactive)
    managingOrganization?: ref<Organization>
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    birthDate <- p.birthDate
    active <- p.active
    status <- p.status
    managingOrganization <- p.managingOrganization
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")

    artifact = next(a for a in artifacts if a.ref == "clinical.PatientProfile@1")
    assert artifact.target == "fhir-profile"
    assert artifact.artifact_id == "clinical.PatientProfile.v1"
    assert artifact.path == tmp_path / "out" / "clinical.PatientProfile.v1.fhir.json"
    assert not artifact.warnings

    doc = json.loads(artifact.content)
    assert doc["resourceType"] == "StructureDefinition"
    assert doc["fhirVersion"] == "4.0.1"
    assert doc["kind"] == "resource"
    assert doc["abstract"] is False
    assert doc["type"] == "Patient"
    assert doc["baseDefinition"] == "http://hl7.org/fhir/StructureDefinition/Patient"
    assert doc["derivation"] == "constraint"
    assert doc["publisher"] == "clinical-platform"
    assert doc["contact"] == [{"telecom": [{"system": "email", "value": "clinical@example.com"}]}]
    assert doc["description"] == "Clinical model contracts"

    elements = {element["id"]: element for element in doc["snapshot"]["element"]}
    assert elements["Patient"] == {
        "id": "Patient",
        "path": "Patient",
        "min": 0,
        "max": "*",
        "base": {"path": "Patient", "min": 0, "max": "*"},
        "definition": "Modelable projection clinical.PatientProfile@1 constrained from clinical.Patient@1.",
    }

    assert elements["Patient.patientId"]["min"] == 1
    assert elements["Patient.patientId"]["max"] == "1"
    assert elements["Patient.patientId"]["type"] == [{"code": "string"}]
    assert elements["Patient.patientId"]["mapping"] == [
        {"identity": "modelable", "map": "clinical.Patient@1.patientId"}
    ]

    assert elements["Patient.birthDate"]["min"] == 0
    assert elements["Patient.birthDate"]["type"] == [{"code": "date"}]
    assert elements["Patient.birthDate"]["extension"] == [
        {
            "url": "http://modelable.io/fhir/StructureDefinition/classification",
            "valueCode": "confidential",
        },
        {
            "url": "http://modelable.io/fhir/StructureDefinition/pii",
            "valueBoolean": True,
        },
    ]

    assert elements["Patient.active"]["type"] == [{"code": "boolean"}]
    assert elements["Patient.status"]["type"] == [{"code": "code"}]
    assert elements["Patient.status"]["binding"] == {
        "strength": "required",
        "valueSet": "http://modelable.io/fhir/ValueSet/clinical.PatientProfile.status",
    }
    assert elements["Patient.managingOrganization"]["type"] == [
        {
            "code": "Reference",
            "targetProfile": ["http://hl7.org/fhir/StructureDefinition/Organization"],
        }
    ]


def test_emit_fhir_profile_warns_for_unsupported_base_resources(tmp_path):
    (tmp_path / "billing.mdl").write_text(
        """
domain billing {
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
  }

  projection InvoiceProfile @ 1
    from billing.Invoice @ 1 as i
  {
    invoiceId <- i.invoiceId
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")

    artifact = next(a for a in artifacts if a.ref == "billing.InvoiceProfile@1")
    assert artifact.warnings == [
        "FHIR profile base resource 'Invoice' is not in the supported R4 set: Encounter, Observation, Patient"
    ]
    doc = json.loads(artifact.content)
    assert doc["type"] == "Basic"
    assert doc["baseDefinition"] == "http://hl7.org/fhir/StructureDefinition/Basic"


def test_emit_fhir_profile_uses_representative_r4_resource_cardinality(tmp_path):
    (tmp_path / "clinical.mdl").write_text(
        """
domain clinical {
  entity Observation @ 1 (additive) {
    @key observationId: uuid
    status: enum(final, amended)
    category?: array<string>
    subject?: ref<Patient>
  }

  entity Encounter @ 1 (additive) {
    @key encounterId: uuid
    status: enum(planned, finished)
    diagnosis?: array<string>
  }

  projection ObservationProfile @ 1
    from clinical.Observation @ 1 as o
  {
    observationId <- o.observationId
    status <- o.status
    category <- o.category
    subject <- o.subject
  }

  projection EncounterProfile @ 1
    from clinical.Encounter @ 1 as e
  {
    encounterId <- e.encounterId
    status <- e.status
    diagnosis <- e.diagnosis
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")

    docs = {artifact.ref: json.loads(artifact.content) for artifact in artifacts}

    observation = docs["clinical.ObservationProfile@1"]
    assert observation["type"] == "Observation"
    assert observation["baseDefinition"] == "http://hl7.org/fhir/StructureDefinition/Observation"
    observation_elements = {element["id"]: element for element in observation["snapshot"]["element"]}
    assert observation_elements["Observation.category"]["min"] == 0
    assert observation_elements["Observation.category"]["max"] == "*"
    assert observation_elements["Observation.category"]["base"] == {
        "path": "Observation.category",
        "min": 0,
        "max": "*",
    }
    assert observation_elements["Observation.category"]["type"] == [{"code": "string"}]
    assert observation_elements["Observation.subject"]["type"] == [
        {
            "code": "Reference",
            "targetProfile": ["http://hl7.org/fhir/StructureDefinition/Patient"],
        }
    ]

    encounter = docs["clinical.EncounterProfile@1"]
    assert encounter["type"] == "Encounter"
    assert encounter["baseDefinition"] == "http://hl7.org/fhir/StructureDefinition/Encounter"
    encounter_elements = {element["id"]: element for element in encounter["snapshot"]["element"]}
    assert encounter_elements["Encounter.diagnosis"]["min"] == 0
    assert encounter_elements["Encounter.diagnosis"]["max"] == "*"
    assert encounter_elements["Encounter.diagnosis"]["type"] == [{"code": "string"}]
