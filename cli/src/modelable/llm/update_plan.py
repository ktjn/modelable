from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from modelable.llm.providers import LLMRequest


class UpdateChange(BaseModel):
    kind: Literal[
        "make_optional",
        "make_required",
        "rename_field",
        "remove_field",
        "change_type",
        "add_field",
        "change_source",
    ]
    field: str
    new_name: str | None = None
    type: str | None = None
    source: str | None = None


class UpdatePlan(BaseModel):
    target: str
    target_kind: Literal["model", "projection"]
    rationale: str | None = None
    warnings: list[str] = Field(default_factory=list)
    changes: list[UpdateChange] = Field(default_factory=list)


SYSTEM_PROMPT = """You edit Modelable .mdl definitions.
Return JSON only matching the supplied schema.
Do not include markdown fences, prose, or commentary.
Prefer the smallest set of changes that satisfies the instruction.
"""


def build_update_request(*, ref: str, current_summary: str, current_text: str, instruction: str) -> LLMRequest:
    user = (
        f"Target reference: {ref}\n\n"
        f"Current summary:\n{current_summary}\n\n"
        f"Current .mdl:\n{current_text}\n\n"
        f"Instruction:\n{instruction}\n"
    )
    return LLMRequest(
        system=SYSTEM_PROMPT,
        user=user,
        temperature=0.1,
        response_format="json",
        schema=UpdatePlan.model_json_schema(),
    )


def parse_update_plan(text: str) -> UpdatePlan:
    payload = _extract_json(text)
    return UpdatePlan.model_validate(payload)


def _extract_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)
