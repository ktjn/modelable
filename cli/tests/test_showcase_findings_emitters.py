from __future__ import annotations

import pytest

from modelable.compiler.workspace import load_workspace
from modelable.emitters.csharp import emit_csharp
from modelable.emitters.go import emit_go
from modelable.emitters.java import emit_java
from modelable.emitters.python import emit_python
from modelable.emitters.sql import _ch_col_type
from modelable.parser.ir import ArrayType, PrimitiveType


@pytest.mark.parametrize(
    ("emitter", "expected_model", "expected_semantic"),
    [
        (emit_csharp, "PlatformAddressV1", "Guid"),
        (emit_java, "AddressV1", "UUID"),
        (emit_python, "PlatformAddressV1", "UUID"),
        (emit_go, "PlatformAddressV1", "string"),
    ],
)
def test_language_emitters_resolve_named_and_semantic_fields(tmp_path, emitter, expected_model, expected_semantic):
    (tmp_path / "model.mdl").write_text(
        """
domain platform {
  semantic AddressId : uuid
  value Address @ 1 (additive) {
    street: string
  }
  entity Customer @ 1 (additive) {
    address: Address
    id: AddressId
  }
}
""",
        encoding="utf-8",
    )
    artifacts = emitter(load_workspace(tmp_path), tmp_path / "out")
    customer = next(artifact for artifact in artifacts if artifact.ref == "platform.Customer@1")
    assert expected_model in customer.content
    assert expected_semantic in customer.content
    assert "Address;" not in customer.content
    assert "AddressId" not in customer.content


def test_clickhouse_optional_array_is_not_wrapped_in_nullable():
    field_type = ArrayType(item=PrimitiveType(kind="string"))
    assert _ch_col_type(field_type, {}, optional=True) == "Array(String)"
