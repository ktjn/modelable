"""Selectable Rust crate for Modelable's temporal primitives.

The Rust emitter historically hard-wired ``timestamp``/``date``/``time``/
``duration`` to ``chrono`` (now flagged unmaintained, RUSTSEC-2026-0543).
This module owns the per-backend type table so a workspace can pick
``chrono`` (default), ``jiff`` or ``time`` once, via ``[targets.rust]
temporal = "..."`` in ``modelable.toml``, instead of annotating every field.

The selection is held in a :class:`~contextvars.ContextVar` for the duration of
one ``emit_rust`` call so the many rendering helpers don't each need an extra
parameter.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

TEMPORAL_KINDS = ("timestamp", "date", "time", "duration")
DEFAULT_BACKEND = "chrono"


@dataclass(frozen=True)
class TemporalBackend:
    name: str
    types: dict[str, str]
    #: ``Cargo.toml`` dependency line for this crate.
    cargo_dependency: str
    #: ``Duration`` constructor from an ``i64`` nanosecond count (serde adapter).
    duration_from_nanos: str
    #: Body of ``fn to_iso(value: &Duration) -> String`` in the serde adapter, for
    #: crates whose ``Display`` is not ISO 8601. ``None`` means ``to_string()`` is
    #: already ISO 8601 (chrono, jiff).
    duration_to_iso_body: tuple[str, ...] | None = None
    #: ``#[serde(with = ...)]`` module per temporal kind (``timestamp``/``date``/
    #: ``time``), for kinds whose crate-default serde form is not the ISO-8601 /
    #: RFC 3339 text the other backends and languages use.
    serde_modules: dict[str, str] = field(default_factory=dict)
    #: Source for generated helper modules named in ``serde_modules`` (keyed by
    #: module name) that live in the emitted file rather than in the crate.
    serde_helper_items: dict[str, tuple[str, ...]] = field(default_factory=dict)


TEMPORAL_BACKENDS: dict[str, TemporalBackend] = {
    "chrono": TemporalBackend(
        name="chrono",
        types={
            "timestamp": "chrono::DateTime<chrono::Utc>",
            "date": "chrono::NaiveDate",
            "time": "chrono::NaiveTime",
            "duration": "chrono::Duration",
        },
        cargo_dependency='chrono = { version = "0.4", features = ["serde"] }',
        duration_from_nanos="chrono::Duration::nanoseconds(total_nanos)",
    ),
    "jiff": TemporalBackend(
        name="jiff",
        types={
            "timestamp": "jiff::Timestamp",
            "date": "jiff::civil::Date",
            "time": "jiff::civil::Time",
            "duration": "jiff::SignedDuration",
        },
        cargo_dependency='jiff = { version = "0.2", features = ["serde"] }',
        duration_from_nanos="jiff::SignedDuration::from_nanos(total_nanos)",
    ),
    "time": TemporalBackend(
        name="time",
        types={
            "timestamp": "time::OffsetDateTime",
            "date": "time::Date",
            "time": "time::Time",
            "duration": "time::Duration",
        },
        cargo_dependency='time = { version = "0.3", features = ["serde-human-readable", "macros"] }',
        duration_from_nanos="time::Duration::nanoseconds(total_nanos)",
        duration_to_iso_body=(
            "        let nanos = value.whole_nanoseconds();",
            '        let sign = if nanos < 0 { "-" } else { "" };',
            "        let nanos = nanos.unsigned_abs();",
            "        let (secs, frac) = (nanos / 1_000_000_000, nanos % 1_000_000_000);",
            "        if frac == 0 {",
            '            format!("{sign}PT{secs}S")',
            "        } else {",
            '            let frac = format!("{frac:09}");',
            "            format!(\"{sign}PT{secs}.{}S\", frac.trim_end_matches('0'))",
            "        }",
        ),
        serde_modules={"timestamp": "time::serde::rfc3339", "time": "modelable_time"},
        serde_helper_items={
            # time::Time's default text form requires a subsecond part ("12:30:00.0");
            # accept the plain ISO-8601 "12:30:00" other producers emit.
            "modelable_time": (
                "time::serde::format_description!(",
                "    modelable_time,",
                "    Time,",
                '    "[hour]:[minute]:[second][optional [.[subsecond]]]"',
                ");",
            ),
        },
    ),
}

_current: ContextVar[str] = ContextVar("modelable_rust_temporal", default=DEFAULT_BACKEND)

#: Matches the crate prefix of a Rust path such as ``jiff::Timestamp`` or
#: ``chrono::NaiveDate``, but not ``std::time::Duration`` or ``my_time::X``.
_CRATE_PATH = re.compile(r"(?<![\w:])(chrono|jiff|time)::")


def validate_backend(name: object) -> str:
    if not isinstance(name, str) or name not in TEMPORAL_BACKENDS:
        raise ValueError(
            f"unsupported Rust temporal backend {name!r}; valid values are: {', '.join(sorted(TEMPORAL_BACKENDS))}"
        )
    return name


def current_backend() -> TemporalBackend:
    return TEMPORAL_BACKENDS[_current.get()]


@contextmanager
def use_backend(name: str | None) -> Iterator[TemporalBackend]:
    """Select the temporal backend for the enclosed emission."""
    backend = validate_backend(name if name is not None else DEFAULT_BACKEND)
    token = _current.set(backend)
    try:
        yield TEMPORAL_BACKENDS[backend]
    finally:
        _current.reset(token)


def temporal_rust_type(kind: str) -> str | None:
    """Rust type for a temporal primitive under the active backend, else ``None``."""
    return current_backend().types.get(kind)


def crates_in(text: str) -> set[str]:
    """Temporal crates referenced by a Rust type annotation or serde attribute."""
    return set(_CRATE_PATH.findall(text))


def requires_header(crate: str) -> str:
    return f"// requires: {crate} (https://docs.rs/{crate})"
