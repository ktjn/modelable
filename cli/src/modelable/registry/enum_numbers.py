"""Deterministic, persisted Protobuf enum number allocation (evolution plan E6).

Allocates stable Protobuf enum discriminant numbers for enum-backed semantic
declarations and their projections:

- ``0`` is reserved for the synthetic ``<PREFIX>_UNSPECIFIED`` value.
- positive numbers are allocated deterministically, in the order a member is
  first seen walking a declaration's version history from lowest to highest.
- numbers are never reassigned: additions, reordering, and version bumps that
  keep an existing member never change its number.
- a member removed from every currently-declared version keeps its number
  reserved forever; a later version cannot reintroduce a member under the same
  canonical name (evolution plan E5 documents that remove-then-re-add is
  indistinguishable from a rename, so silently reusing the slot would hide an
  unrelated identity change).
- an enum projection carries its source declaration's numbers for every
  member it includes (Protobuf permits reusing a plain integer value across
  independent enum types), so it has no independent allocation of its own.

Source spelling never enters the allocator; only normalized canonical member
identities are used. Allocation is a pure function of the declared member
history plus whatever was already persisted in the ledger.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from modelable.parser.ir import EnumProjectionDecl, EnumType, MdlFile, SemanticTypeDecl


class EnumNumberConflictError(ValueError):
    """A previously-removed enum member name reappeared in a later version."""


@dataclass(frozen=True)
class EnumNumberAllocation:
    """Complete number allocation for one enum-backed declaration.

    Attributes
        name: Qualified declaration name (``"domain.Name"``).
        unspecified: Always 0, the synthetic UNSPECIFIED value.
        members: Currently-live members with their allocated numbers, ordered
            by number.
        reservations: Members removed from every currently-declared version;
            their numbers (and names) can never be reused.
    """

    name: str
    unspecified: int = 0
    members: tuple[tuple[str, int], ...] = ()
    reservations: tuple[tuple[str, int], ...] = ()

    @property
    def member_numbers(self) -> dict[str, int]:
        return dict(self.members)

    @property
    def reserved_numbers(self) -> dict[str, int]:
        return dict(self.reservations)


def _enum_declarations_by_name(mdl: MdlFile) -> dict[str, list[SemanticTypeDecl]]:
    """Group every enum-backed semantic declaration version by qualified name."""
    grouped: dict[str, list[SemanticTypeDecl]] = {}
    for domain in mdl.domains:
        for decl in domain.semantic_types:
            if not isinstance(decl.underlying, EnumType):
                continue
            grouped.setdefault(f"{domain.name}.{decl.name}", []).append(decl)
    for versions in grouped.values():
        versions.sort(key=lambda declaration: declaration.version)
    return grouped


def _allocate_one(
    qualified: str,
    versions: list[SemanticTypeDecl],
    prior: EnumNumberAllocation | None,
) -> EnumNumberAllocation:
    # Old versions of a declaration remain valid permanently alongside newer
    # ones (evolution plan D0's additive-syntax policy), so *versions* only
    # grows over time; "live" membership is defined by the highest version,
    # while the full history still drives first-seen allocation order.
    member_numbers: dict[str, int] = dict(prior.members) if prior else {}
    reserved: dict[str, int] = dict(prior.reservations) if prior else {}
    next_number = max([*member_numbers.values(), *reserved.values(), 0]) + 1

    latest = versions[-1]
    assert isinstance(latest.underlying, EnumType)
    latest_members = latest.underlying.values

    reused = sorted(set(latest_members) & set(reserved))
    if reused:
        canonical = reused[0]
        raise EnumNumberConflictError(
            f"{qualified}: member '{canonical}' was previously removed (reserved as protobuf "
            f"number {reserved[canonical]}) and cannot be reintroduced under the same name. "
            "Removing and re-adding a member is indistinguishable from an unrelated rename; "
            "use a distinct member name for the new value."
        )

    for version in versions:
        assert isinstance(version.underlying, EnumType)
        for canonical in version.underlying.values:
            if canonical not in member_numbers:
                member_numbers[canonical] = next_number
                next_number += 1

    for canonical in list(member_numbers):
        if canonical not in latest_members:
            reserved[canonical] = member_numbers.pop(canonical)

    return EnumNumberAllocation(
        name=qualified,
        members=tuple(sorted(member_numbers.items(), key=lambda item: item[1])),
        reservations=tuple(sorted(reserved.items(), key=lambda item: item[1])),
    )


def allocate_enum_numbers(
    mdl: MdlFile,
    existing: dict[str, EnumNumberAllocation],
) -> dict[str, EnumNumberAllocation]:
    """Compute the deterministic, persisted number allocation for every
    enum-backed semantic declaration in *mdl*.

    Walks each declaration's full version history (lowest to highest) so a
    member's number is fixed the first time it is ever seen, never solely by
    its position in the latest version. Numbers already present in *existing*
    are preserved exactly. Members no longer present in any currently
    declared version become reservations. Reintroducing a previously-removed
    member name raises ``EnumNumberConflictError``.
    """
    return {
        qualified: _allocate_one(qualified, versions, existing.get(qualified))
        for qualified, versions in _enum_declarations_by_name(mdl).items()
    }


def resolve_projection_numbers(
    projection: EnumProjectionDecl,
    source_allocation: EnumNumberAllocation,
) -> dict[str, int]:
    """Return the Protobuf numbers an enum projection's included members
    carry from their source declaration.

    A projection member is always a member of its source at the projected
    version, so it always has an allocated source number; this raises
    ``KeyError`` only if the projection and its source have drifted out of
    sync with each other, which normalization should already prevent.
    """
    numbers = source_allocation.member_numbers
    return {member: numbers[member] for member in projection.members}


def read_lock_file(path: Path) -> dict[str, EnumNumberAllocation]:
    if not path.exists():
        return {}
    payload = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    result: dict[str, EnumNumberAllocation] = {}
    for name, raw_entry in payload.items():
        entry = cast(dict[str, object], raw_entry)
        members = tuple(
            (cast(str, member["name"]), cast(int, member["number"]))
            for member in cast(list[dict[str, object]], entry.get("members", []))
        )
        reservations = tuple(
            (cast(str, member["name"]), cast(int, member["number"]))
            for member in cast(list[dict[str, object]], entry.get("reservations", []))
        )
        result[name] = EnumNumberAllocation(name=name, members=members, reservations=reservations)
    return result


def write_lock_file(path: Path, allocations: dict[str, EnumNumberAllocation]) -> None:
    payload = {
        name: {
            "members": [{"name": member, "number": number} for member, number in allocation.members],
            "reservations": [{"name": member, "number": number} for member, number in allocation.reservations],
        }
        for name, allocation in sorted(allocations.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def orphaned_declarations(mdl: MdlFile, existing: dict[str, EnumNumberAllocation]) -> list[str]:
    """Ledger entries with no matching enum-backed semantic declaration."""
    declared = set(_enum_declarations_by_name(mdl))
    return sorted(name for name in existing if name not in declared)
