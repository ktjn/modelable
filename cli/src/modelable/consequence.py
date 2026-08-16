from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACTION_NO_ACTION = "no_action"
ACTION_RECOMPILE = "recompile"
ACTION_REGENERATE = "regenerate"
ACTION_CONSUMER_UPDATE = "consumer_update"
ACTION_BREAKING = "breaking"


@dataclass(frozen=True)
class Consequence:
    action: str
    subject: str
    status: str
    reason: str | None = None
    causal_path: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "subject": self.subject,
            "status": self.status,
            "reason": self.reason,
            "causal_path": list(self.causal_path),
        }


def action_for_projection_status(status: str) -> str:
    if status == "broken":
        return ACTION_BREAKING
    if status == "affected":
        return ACTION_REGENERATE
    return ACTION_NO_ACTION
