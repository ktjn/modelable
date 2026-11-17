from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

DEFAULT_TEMPORAL = "chrono"

TEMPORAL_MAPPINGS: dict[str, dict[str, str]] = {
    "chrono": {
        "timestamp": "chrono::DateTime<chrono::Utc>",
        "date": "chrono::NaiveDate",
        "time": "chrono::NaiveTime",
        "duration": "chrono::Duration",
    },
    "jiff": {
        "timestamp": "jiff::Timestamp",
        "date": "jiff::civil::Date",
        "time": "jiff::civil::Time",
        "duration": "jiff::SignedDuration",
    },
}

TEMPORAL_DEPENDENCIES: dict[str, str] = {
    "chrono": 'chrono = { version = "0.4", features = ["serde"] }',
    "jiff": 'jiff = { version = "0.2", features = ["serde"] }',
}

_current: ContextVar[str] = ContextVar("modelable_rust_temporal", default=DEFAULT_TEMPORAL)


def validate_temporal(value: object) -> str:
    if not isinstance(value, str) or value not in TEMPORAL_MAPPINGS:
        supported = ", ".join(sorted(TEMPORAL_MAPPINGS))
        raise ValueError(f"[targets.rust].temporal must be one of: {supported} (got {value!r})")
    return value


@contextmanager
def temporal_scope(value: str) -> Iterator[None]:
    token = _current.set(validate_temporal(value))
    try:
        yield
    finally:
        _current.reset(token)


def current_temporal() -> str:
    return _current.get()


def temporal_type(kind: str) -> str | None:
    return TEMPORAL_MAPPINGS[_current.get()].get(kind)
