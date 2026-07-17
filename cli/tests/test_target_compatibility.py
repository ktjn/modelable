from __future__ import annotations

from pathlib import Path

from modelable.compat.targets import compare_grpc_artifacts, compare_protobuf_manifests
from modelable.compiler.workspace import load_workspace
from modelable.emitters.grpc import emit_grpc
from modelable.emitters.protobuf import emit_protobuf


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _protobuf_artifacts(path: Path):
    return emit_protobuf(load_workspace(path), path.parent / "out")


def _grpc_artifacts(path: Path):
    return emit_grpc(load_workspace(path), path.parent / "grpc-out")


def test_protobuf_compat_allows_added_optional_field(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName?: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_rejects_removed_field_without_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "removed_field_not_reserved" for finding in report.findings)


def test_protobuf_compat_allows_removed_field_with_number_and_name_reservation(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legacyStatus: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [2]
      names: ["legacy_status"]
    }
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "wire_compatible"
    assert report.findings == []


def test_protobuf_compat_rejects_field_number_reuse_by_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    displayName: string
    @key customerId: uuid
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_number_reused" for finding in report.findings)


def test_protobuf_compat_rejects_target_type_change(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: int
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    score: string
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "field_type_changed" for finding in report.findings)


def test_protobuf_compat_rejects_inline_enum_reorder(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(active, blocked)
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: enum(blocked, active)
  }
}
""",
    )

    report = compare_protobuf_manifests(_protobuf_artifacts(old), _protobuf_artifacts(new))

    assert report.status == "breaking"
    assert any(finding.code == "enum_value_reused" for finding in report.findings)


def test_grpc_compat_reports_changed_secondary_index_as_read_rebuild(tmp_path):
    old = _write(
        tmp_path / "old.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
    }
  }
}
""",
    )
    new = _write(
        tmp_path / "new.mdl",
        """
domain billing {
  owner: "billing"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    customerId: uuid
    createdAt: timestamp
  }
  index Order @ 1 {
    primary orderId
    secondary by_customer {
      key: [customerId]
      sort: [createdAt desc]
    }
  }
}
""",
    )

    report = compare_grpc_artifacts(_grpc_artifacts(old), _grpc_artifacts(new))

    assert report.status == "requires_read_rebuild"
    assert any(finding.code == "read_index_changed" for finding in report.findings)
