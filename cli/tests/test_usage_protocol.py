from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

import pytest


def _protocol():
    return import_module("modelable.registry.usage_protocol")


def _manifest() -> dict[str, object]:
    return {
        "$schema": "modelable.usage/v0",
        "kind": "usage_manifest",
        "application": "billing-service",
        "references": [
            {
                "ref": "customer.Customer@1",
                "signature": "a" * 64,
                "fields": ["customer.Customer@1#customerId"],
            }
        ],
    }


def test_usage_protocol_round_trips_canonical_json(tmp_path: Path) -> None:
    protocol = _protocol()
    path = tmp_path / "usage.json"
    path.write_text(protocol.serialize_usage_manifest(_manifest()), encoding="utf-8")

    assert protocol.load_usage_manifest(path) == _manifest()
    assert protocol.serialize_usage_manifest(json.loads(path.read_text(encoding="utf-8"))) == path.read_text(
        encoding="utf-8"
    )


def test_usage_protocol_rejects_duplicate_references() -> None:
    protocol = _protocol()
    manifest = _manifest()
    manifest["references"] = [manifest["references"][0], manifest["references"][0]]

    with pytest.raises(protocol.UsageProtocolError, match="duplicate reference"):
        protocol.validate_usage_manifest(manifest)


def test_usage_protocol_rejects_invalid_field_prefix() -> None:
    protocol = _protocol()
    manifest = _manifest()
    manifest["references"][0]["fields"] = ["orders.Order@1#orderId"]

    with pytest.raises(protocol.UsageProtocolError, match="must belong to reference"):
        protocol.validate_usage_manifest(manifest)
