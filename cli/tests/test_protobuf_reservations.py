from __future__ import annotations

import pytest

from modelable.parser import parse_text_to_ir
from modelable.parser.ir import ParseError


def test_parse_model_protobuf_reservations():
    mdl = parse_text_to_ir(
        """
domain billing {
  owner: "billing"

  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 7]
      names: ["legacy_status", "old_status"]
    }

    @key customerId: uuid
    displayName?: string
  }
}
"""
    )

    customer = mdl.domains[0].models["Customer"][0]
    assert customer.protobuf_reservations is not None
    assert customer.protobuf_reservations.numbers == [3, 7]
    assert customer.protobuf_reservations.names == ["legacy_status", "old_status"]


def test_parse_projection_protobuf_reservations():
    mdl = parse_text_to_ir(
        """
domain billing {
  owner: "billing"

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    status: string
  }

  projection CustomerView @ 2 from billing.Customer@1 as c {
    reserved protobuf {
      numbers: [2]
      names: ["status"]
    }

    customerId <- c.customerId
  }
}
"""
    )

    projection = mdl.domains[0].projections["CustomerView"][0]
    assert projection.protobuf_reservations is not None
    assert projection.protobuf_reservations.numbers == [2]
    assert projection.protobuf_reservations.names == ["status"]


def test_reject_duplicate_protobuf_reservation_numbers():
    with pytest.raises(ParseError, match="duplicate protobuf reservation number"):
        parse_text_to_ir(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
      numbers: [3, 3]
    }
    @key customerId: uuid
  }
}
"""
        )


def test_reject_empty_protobuf_reservation_block():
    with pytest.raises(ParseError, match="must reserve at least one number or name"):
        parse_text_to_ir(
            """
domain billing {
  owner: "billing"
  entity Customer @ 2 (additive) {
    reserved protobuf {
    }
    @key customerId: uuid
  }
}
"""
        )
