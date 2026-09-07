"""Rust emission tests for ``union<discriminator> { tag: T, ... }`` fields (issue #856)."""

from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.rust import emit_rust


def _write(tmp_path, name: str, text: str) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")


def test_union_field_emits_internally_tagged_enum_with_object_variants(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      card: object { number: string },
      bank: object { iban: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert "pub method: PaymentsPaymentV1Method," in entity_artifact.content
    assert '#[serde(tag = "kind")]' in entity_artifact.content
    assert "pub enum PaymentsPaymentV1Method {" in entity_artifact.content
    assert "Card {" in entity_artifact.content
    assert "number: String," in entity_artifact.content
    assert "Bank {" in entity_artifact.content
    assert "iban: String," in entity_artifact.content


def test_union_variant_tag_needing_rename_gets_serde_rename(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      bank_transfer: object { iban: string },
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert '#[serde(rename = "bank_transfer")]' in entity_artifact.content
    assert "BankTransfer {" in entity_artifact.content


def test_union_variant_referencing_named_type_emits_newtype_variant(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  semantic CardDetails @ 1 (additive): object { number: string }
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      card: CardDetails,
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert "Card(CardDetails)," in entity_artifact.content
    assert "use super::card_details::CardDetails;" in entity_artifact.content


def test_union_variant_colliding_tag_identifiers_raise(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      foo_bar: object { a: string },
      foo_bar_: object { b: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    with pytest.raises(ValueError, match="variant collision"):
        emit_rust(workspace, tmp_path / "out")


def test_union_ref_variant_warns_about_internally_tagged_wire_mismatch(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  entity Card @ 1 (additive) { @key cardId: uuid }
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      card: ref<payments.Card>,
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert "Card(String)," in entity_artifact.content
    assert any("ref<T> union variant" in warning for warning in entity_artifact.warnings)


def test_union_named_variant_backed_by_scalar_type_warns(tmp_path):
    """A `named` variant whose semantic declaration is scalar-backed (not
    object-shaped) hits the same serde internally-tagged limitation as a
    ref<T> variant: it cannot serialize as a map alongside the discriminator."""
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  semantic AccountId @ 1 (additive): string
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      account: AccountId,
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert "Account(AccountId)," in entity_artifact.content
    assert any("named union variant" in warning for warning in entity_artifact.warnings)


def test_union_named_variant_backed_by_object_semantic_type_does_not_warn(tmp_path):
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  semantic CardDetails @ 1 (additive): object { number: string }
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      card: CardDetails,
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert entity_artifact.warnings == []


def test_union_named_variant_referencing_model_does_not_warn(tmp_path):
    """A model reference is always object-shaped, so no warning is expected
    even though the resolution path differs from a semantic declaration."""
    _write(
        tmp_path,
        "model.mdl",
        """
domain payments {
  owner: "payments-team"
  entity CardOnFile @ 1 (additive) { @key cardId: uuid number: string }
  entity Payment @ 1 (additive) {
    @key paymentId: uuid
    method: union<kind> {
      card: CardOnFile,
      cash: object { currency: string }
    }
  }
}
""",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_rust(workspace, tmp_path / "out")
    entity_artifact = next(a for a in artifacts if a.ref == "payments.Payment@1")

    assert entity_artifact.warnings == []
    assert "Card(PaymentsCardOnFileV1)," in entity_artifact.content
