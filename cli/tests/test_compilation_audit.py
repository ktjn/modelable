from __future__ import annotations

import json
from pathlib import Path

from modelable.operations.compilation_audit import (
    CompilationAuditDestination,
    CompilationAuditRecord,
)


def test_audit_schema_v1_is_deterministic_and_private(tmp_path: Path) -> None:
    record = CompilationAuditRecord(
        action_id="action-1",
        session_id="session-1",
        preview_timestamp="2026-07-20T10:00:00Z",
        confirmation_timestamp="2026-07-20T10:01:00Z",
        confirmation_surface="cli-chat",
        provider="ollama",
        model="qwen",
        plan={
            "target": "rust",
            "domains": ["platform"],
            "output": "generated/rust",
            "descriptorSet": False,
        },
        affected_definitions=("platform.Order@1",),
        destinations=(
            CompilationAuditDestination(
                status="created",
                path="generated/rust/platform/order.rs",
                size=24,
                content_hash="a" * 64,
            ),
        ),
        registry_id_allocations=(("platform.SchemaId", 1),),
        warnings=("safe warning",),
        manifest_fingerprint="b" * 64,
        outcome="applied",
    )

    payload = record.to_bytes()
    decoded = json.loads(payload)

    assert payload.endswith(b"\n")
    assert payload == record.to_bytes()
    assert decoded == {
        "actionId": "action-1",
        "affectedDefinitions": ["platform.Order@1"],
        "confirmation": {
            "model": "qwen",
            "provider": "ollama",
            "surface": "cli-chat",
            "timestamp": "2026-07-20T10:01:00Z",
        },
        "destinations": [
            {
                "contentHash": "a" * 64,
                "path": "generated/rust/platform/order.rs",
                "size": 24,
                "status": "created",
            }
        ],
        "manifestFingerprint": "b" * 64,
        "outcome": "applied",
        "plan": {
            "descriptorSet": False,
            "domains": ["platform"],
            "output": "generated/rust",
            "target": "rust",
        },
        "previewTimestamp": "2026-07-20T10:00:00Z",
        "registryIdAllocations": [{"ref": "platform.SchemaId", "registryId": 1}],
        "schemaVersion": 1,
        "sessionId": "session-1",
        "warnings": ["safe warning"],
    }
    serialized = payload.decode("utf-8").lower()
    for private_term in (
        "prompt",
        "response",
        "sourcecontent",
        "artifactcontent",
        "token",
        "credential",
        "environment",
    ):
        assert private_term not in serialized
    assert str(tmp_path).lower() not in serialized
