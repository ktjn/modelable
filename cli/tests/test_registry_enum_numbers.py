"""Allocator tests for stable Protobuf enum numbering (evolution plan E6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from modelable.compiler.workspace import WorkspaceDocumentSource, load_workspace_from_sources
from modelable.registry.enum_numbers import (
    EnumNumberAllocation,
    EnumNumberConflictError,
    allocate_enum_numbers,
    orphaned_declarations,
    read_lock_file,
    write_lock_file,
)


def _workspace(source: str):
    workspace = load_workspace_from_sources(
        [WorkspaceDocumentSource(path=Path("orders.mdl"), uri="file:///orders.mdl", text=source)]
    )
    assert not workspace.errors, workspace.errors
    return workspace


def test_first_allocation_numbers_members_in_declaration_order():
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})["orders.OrderStatus"]
    assert allocation.members == (("pending", 1), ("active", 2), ("done", 3))
    assert allocation.reservations == ()


def test_append_and_reorder_preserve_existing_numbers():
    v1 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
        ).mdl,
        {},
    )
    v2 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (additive): enum(active, done, cancelled, pending)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
        ).mdl,
        v1,
    )
    allocation = v2["orders.OrderStatus"]
    assert dict(allocation.members) == {"pending": 1, "active": 2, "done": 3, "cancelled": 4}
    assert allocation.reservations == ()


def test_removed_member_becomes_a_reservation():
    v1 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
        ).mdl,
        {},
    )
    v2 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (breaking): enum(active, cancelled)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 2 }
}
"""
        ).mdl,
        v1,
    )
    allocation = v2["orders.OrderStatus"]
    assert dict(allocation.members) == {"active": 2, "cancelled": 4}
    assert dict(allocation.reservations) == {"pending": 1, "done": 3}


def test_reintroducing_a_removed_member_name_is_rejected():
    v1 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
        ).mdl,
        {},
    )
    v2 = allocate_enum_numbers(
        _workspace(
            """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (breaking): enum(active, cancelled)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 2 }
}
"""
        ).mdl,
        v1,
    )
    workspace_v3 = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic OrderStatus @ 2 (breaking): enum(active, cancelled)
  semantic OrderStatus @ 3 (breaking): enum(active, cancelled, pending)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 3 }
}
"""
    )
    with pytest.raises(EnumNumberConflictError, match="pending"):
        allocate_enum_numbers(workspace_v3.mdl, v2)


def test_unrelated_declaration_is_unaffected_by_another_declaration_change():
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  semantic PaymentStatus @ 1 (additive): enum(unpaid, paid)
  entity Order @ 1 (additive) {
    @key orderId: uuid
    status: OrderStatus @ 1
    paymentStatus: PaymentStatus @ 1
  }
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})
    assert dict(allocation["orders.OrderStatus"].members) == {"pending": 1, "active": 2, "done": 3}
    assert dict(allocation["orders.PaymentStatus"].members) == {"unpaid": 1, "paid": 2}


def test_lock_file_round_trips(tmp_path):
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})
    lock_path = tmp_path / "enum-numbers.lock"
    write_lock_file(lock_path, allocation)

    reloaded = read_lock_file(lock_path)
    assert reloaded == allocation

    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    assert payload["orders.OrderStatus"]["members"] == [
        {"name": "pending", "number": 1},
        {"name": "active", "number": 2},
        {"name": "done", "number": 3},
    ]


def test_missing_lock_file_reads_as_empty(tmp_path):
    assert read_lock_file(tmp_path / "missing.lock") == {}


def test_orphaned_declarations_reports_ledger_entries_with_no_matching_declaration():
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
}
"""
    )
    existing = {
        "orders.OrderStatus": EnumNumberAllocation(name="orders.OrderStatus", members=(("pending", 1),)),
        "orders.RemovedEnum": EnumNumberAllocation(name="orders.RemovedEnum", members=(("x", 1),)),
    }
    assert orphaned_declarations(workspace.mdl, existing) == ["orders.RemovedEnum"]


def test_enum_projection_reuses_source_numbers():
    workspace = _workspace(
        """
domain orders {
  owner: "orders-team"
  semantic OrderStatus @ 1 (additive): enum(pending, active, done)
  entity Order @ 1 (additive) { @key orderId: uuid status: OrderStatus @ 1 }
  enum projection PublicStatus @ 1 (additive)
    from OrderStatus @ 1
    pick(active, done)
}
"""
    )
    allocation = allocate_enum_numbers(workspace.mdl, {})
    source_allocation = allocation["orders.OrderStatus"]
    projection = workspace.mdl.domains[0].enum_projections[0]

    from modelable.registry.enum_numbers import resolve_projection_numbers

    numbers = resolve_projection_numbers(projection, source_allocation)
    assert numbers == {"active": 2, "done": 3}
