from __future__ import annotations

import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from modelable.cli import cli
from modelable.emitters.fhir_validator import validate_fhir_profile


def test_validate_fhir_profile_invokes_hl7_validator_cli_with_r4_version(tmp_path):
    profile = tmp_path / "clinical.PatientProfile.v1.fhir.json"
    profile.write_text('{"resourceType":"StructureDefinition"}\n', encoding="utf-8")
    validator = tmp_path / "validator_cli.jar"
    validator.write_bytes(b"jar")
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    result = validate_fhir_profile(profile, validator, run=fake_run)

    assert result.returncode == 0
    assert calls == [
        [
            "java",
            "-jar",
            str(validator),
            str(profile),
            "-version",
            "4.0.1",
        ]
    ]


def test_compile_fhir_profile_passes_hl7_validator_when_available(tmp_path):
    validator = os.getenv("MODELABLE_FHIR_VALIDATOR_JAR")
    if not validator:
        if os.getenv("MODELABLE_FHIR_VALIDATOR") == "1":
            raise AssertionError("MODELABLE_FHIR_VALIDATOR=1 requires MODELABLE_FHIR_VALIDATOR_JAR")
        return

    source = tmp_path / "clinical.mdl"
    source.write_text(
        """
domain clinical {
  owner: "clinical-platform"

  value ContactDetails @ 1 (additive) {
    email?: string
    phone?: string
  }

  entity Patient @ 1 (additive) {
    @key id: uuid
    active: bool
    birthDate?: date
    contact: ContactDetails
    @pii patientId: uuid
  }

  projection PatientProfile @ 1
    from clinical.Patient @ 1 as p
  {
    active <- p.active
    birthDate <- p.birthDate
    contact <- p.contact
    patientId <- p.patientId
  }
}
""",
        encoding="utf-8",
    )

    out = tmp_path / "dist" / "fhir"
    compile_result = CliRunner().invoke(cli, ["compile", str(source), "--target", "fhir-profile", "--out", str(out)])

    assert compile_result.exit_code == 0, compile_result.output

    # Validate every emitted artifact together (the profile, its companion
    # per-field extension StructureDefinitions, and the shared `pii`
    # annotation extension) so cross-references between them resolve -
    # validating the profile alone previously hid real errors on the
    # composite direct field (`contact`, mapped to the base resource's own
    # `Patient.contact`) and the extension slicing/value elements.
    fhir_artifacts = sorted(out.glob("*.fhir.json"))
    assert fhir_artifacts
    result = validate_fhir_profile(fhir_artifacts, Path(validator))

    assert result.returncode == 0, result.stdout + result.stderr
