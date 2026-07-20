from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class CompilationAuditDestination:
    status: Literal["created", "changed", "unchanged"]
    path: str
    size: int
    content_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "contentHash": self.content_hash,
            "path": self.path,
            "size": self.size,
            "status": self.status,
        }


@dataclass(frozen=True)
class CompilationAuditRecord:
    action_id: str
    session_id: str
    preview_timestamp: str
    confirmation_timestamp: str
    confirmation_surface: Literal["cli-chat", "vscode-chat"]
    provider: str | None
    model: str | None
    plan: dict[str, object]
    affected_definitions: tuple[str, ...]
    destinations: tuple[CompilationAuditDestination, ...]
    registry_id_allocations: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]
    manifest_fingerprint: str
    outcome: Literal["applied"]
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "actionId": self.action_id,
            "affectedDefinitions": list(self.affected_definitions),
            "confirmation": {
                "model": self.model,
                "provider": self.provider,
                "surface": self.confirmation_surface,
                "timestamp": self.confirmation_timestamp,
            },
            "destinations": [item.to_dict() for item in self.destinations],
            "manifestFingerprint": self.manifest_fingerprint,
            "outcome": self.outcome,
            "plan": self.plan,
            "previewTimestamp": self.preview_timestamp,
            "registryIdAllocations": [
                {"ref": ref, "registryId": registry_id} for ref, registry_id in self.registry_id_allocations
            ],
            "schemaVersion": self.schema_version,
            "sessionId": self.session_id,
            "warnings": list(self.warnings),
        }

    def to_bytes(self) -> bytes:
        return (
            json.dumps(
                self.to_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
