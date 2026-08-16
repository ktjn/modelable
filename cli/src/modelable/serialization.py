from __future__ import annotations

from modelable.parser.ir import PrimitiveType, WireTargetHint

CANONICAL_TEMPORAL_FORMATS: dict[str, str] = {
    "date": "iso-8601-date",
    "time": "iso-8601-time",
    "timestamp": "rfc3339",
    "duration": "iso-8601-duration",
}


def canonical_temporal_format(kind: str, hint: WireTargetHint | None = None) -> str | None:
    """Return the default temporal wire format, honoring a target override."""
    if kind not in CANONICAL_TEMPORAL_FORMATS:
        return None
    return hint.encoding if hint is not None and hint.encoding is not None else CANONICAL_TEMPORAL_FORMATS[kind]


def temporal_kind(field_type: object) -> str | None:
    if isinstance(field_type, PrimitiveType):
        return field_type.kind if field_type.kind in CANONICAL_TEMPORAL_FORMATS else None
    return None
