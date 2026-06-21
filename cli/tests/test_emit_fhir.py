from __future__ import annotations

import json

from modelable.compiler.workspace import load_workspace
from modelable.emitters.fhir import emit_fhir_profile


def test_emit_fhir_profile_maps_known_fields_direct_and_unknown_as_extensions(tmp_path):
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

    # Known Patient fields remain direct children
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
    assert elements["Patient.managingOrganization"]["type"] == [
        {
            "code": "Reference",
            "targetProfile": ["http://hl7.org/fhir/StructureDefinition/Organization"],
        }
    ]

    # Unknown fields (patientId, status) become extension slices
    assert "Patient.extension" in elements
    assert elements["Patient.extension"]["slicing"] == {
        "discriminator": [{"type": "value", "path": "url"}],
        "ordered": False,
        "rules": "open",
    }

    assert elements["Patient.extension:patientId"]["sliceName"] == "patientId"
    assert elements["Patient.extension:patientId"]["min"] == 1
    assert elements["Patient.extension:patientId"]["max"] == "1"
    assert elements["Patient.extension:patientId"]["type"] == [
        {
            "code": "Extension",
            "profile": ["http://modelable.io/fhir/StructureDefinition/clinical.PatientProfile.v1.ext.patientId"],
        }
    ]
    assert elements["Patient.extension:patientId"]["mapping"] == [
        {"identity": "modelable", "map": "clinical.Patient@1.patientId"}
    ]
    assert elements["Patient.extension:patientId.value[x]"]["type"] == [{"code": "string"}]

    assert elements["Patient.extension:status"]["sliceName"] == "status"
    assert elements["Patient.extension:status"]["type"] == [
        {
            "code": "Extension",
            "profile": ["http://modelable.io/fhir/StructureDefinition/clinical.PatientProfile.v1.ext.status"],
        }
    ]
    assert elements["Patient.extension:status.value[x]"]["type"] == [{"code": "code"}]
    assert elements["Patient.extension:status.value[x]"]["binding"] == {
        "strength": "required",
        "valueSet": "http://modelable.io/fhir/ValueSet/clinical.PatientProfile.status",
    }


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

    elements = {element["id"]: element for element in doc["snapshot"]["element"]}
    assert "Basic.extension" in elements
    assert elements["Basic.extension"]["slicing"]["rules"] == "open"
    assert elements["Basic.extension:invoiceId"]["sliceName"] == "invoiceId"
    assert elements["Basic.extension:invoiceId"]["type"] == [
        {
            "code": "Extension",
            "profile": ["http://modelable.io/fhir/StructureDefinition/billing.InvoiceProfile.v1.ext.invoiceId"],
        }
    ]


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

    docs = {artifact.ref: json.loads(artifact.content) for artifact in artifacts if artifact.target == "fhir-profile"}

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
    assert "Observation.extension" in observation_elements
    assert observation_elements["Observation.extension:observationId"]["sliceName"] == "observationId"

    encounter = docs["clinical.EncounterProfile@1"]
    assert encounter["type"] == "Encounter"
    assert encounter["baseDefinition"] == "http://hl7.org/fhir/StructureDefinition/Encounter"
    encounter_elements = {element["id"]: element for element in encounter["snapshot"]["element"]}
    assert encounter_elements["Encounter.diagnosis"]["min"] == 0
    assert encounter_elements["Encounter.diagnosis"]["max"] == "*"
    assert encounter_elements["Encounter.diagnosis"]["type"] == [{"code": "string"}]
    assert "Encounter.extension" in encounter_elements
    assert encounter_elements["Encounter.extension:encounterId"]["sliceName"] == "encounterId"


def test_emit_fhir_profile_generates_companion_extension_structure_definitions(tmp_path):
    (tmp_path / "clinical.mdl").write_text(
        """
domain clinical {
  entity Patient @ 1 (additive) {
    @key patientId: uuid
    active: bool
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    patientId <- p.patientId
    active <- p.active
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_fhir_profile(workspace, tmp_path / "out")

    ext_artifacts = [a for a in artifacts if a.target == "fhir-extension"]
    assert len(ext_artifacts) == 1
    ext = ext_artifacts[0]
    assert ext.ref == "clinical.PatientProfile@1.patientId"
    assert ext.artifact_id == "clinical.PatientProfile.v1.ext.patientId"
    assert ext.path == tmp_path / "out" / "clinical.PatientProfile.v1.ext.patientId.fhir.json"

    doc = json.loads(ext.content)
    assert doc["resourceType"] == "StructureDefinition"
    assert doc["type"] == "Extension"
    assert doc["derivation"] == "specialization"
    assert doc["kind"] == "complex-type"
    assert doc["name"] == "PatientProfilePatientId"
    assert doc["url"] == "http://modelable.io/fhir/StructureDefinition/clinical.PatientProfile.v1.ext.patientId"

    ext_elements = {el["id"]: el for el in doc["snapshot"]["element"]}
    assert "Extension" in ext_elements
    assert ext_elements["Extension.url"]["fixedUri"] == doc["url"]
    assert ext_elements["Extension.value[x]"]["type"] == [{"code": "string"}]

    # Active is a known Patient field, so no extension companion
    assert "PatientProfileActive" not in {a.artifact_id for a in artifacts}
