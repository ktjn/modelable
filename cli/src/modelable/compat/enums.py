"""Declaration-level enum compatibility (evolution plan E5).

Compares semantic enum declarations and enum projections by member identity,
not shape: equal-shaped nominal enums never collapse into one compatibility
finding, additive growth and breaking evolution are distinct, and implicit
omit growth is reported instead of silently absorbed.
"""

from __future__ import annotations

from dataclasses import dataclass

from modelable.parser.ir import EnumProjectionDecl, EnumType, SemanticTypeDecl

EXHAUSTIVE_MATCH = "exhaustive_match"


@dataclass(frozen=True)
class EnumChange:
    """A single declaration-level enum evolution finding."""

    kind: str  # enum_member_added | enum_member_removed | enum_projection_source_changed |
    # enum_projection_member_added | enum_projection_member_removed | enum_projection_implicit_member_added
    owner: str  # qualified "domain.Name@version"
    member: str | None = None
    breaking: bool = False
    # Target-level consequences implied by the change, e.g. exhaustive-match
    # consumers (Rust matches) must extend their arms when a member is added.
    consequences: tuple[str, ...] = ()


def compare_semantic_enum_versions(old: SemanticTypeDecl, new: SemanticTypeDecl) -> list[EnumChange]:
    """Diff two versions of one semantic enum declaration by canonical member set.

    Member addition is schema-additive while existing member identities are
    stable, carrying an exhaustive-consumer consequence. Removal is breaking.
    A rename is indistinguishable from remove+add under the current model and
    therefore classifies as breaking via the removed half.
    """
    owner = f"{new.name}@{new.version}" if new.has_version_header else new.name
    old_values = set(old.underlying.values) if isinstance(old.underlying, EnumType) else set()
    new_values = set(new.underlying.values) if isinstance(new.underlying, EnumType) else set()
    changes: list[EnumChange] = []
    for member in sorted(old_values - new_values):
        changes.append(EnumChange(kind="enum_member_removed", owner=owner, member=member, breaking=True))
    for member in sorted(new_values - old_values):
        changes.append(
            EnumChange(
                kind="enum_member_added",
                owner=owner,
                member=member,
                breaking=False,
                consequences=(EXHAUSTIVE_MATCH,),
            )
        )
    return changes


def compare_enum_projections(
    source_name: str,
    old: EnumProjectionDecl,
    new: EnumProjectionDecl,
) -> list[EnumChange]:
    """Diff two versions of one enum projection.

    Source changes are always reported even when the resulting member set is
    identical. Member additions are explicit when authored by an updated pick
    list, and classified as ``enum_projection_implicit_member_added`` when they
    appear because an omit projection was rebased onto a source version that
    gained members — never silent either way.
    """
    owner = f"{source_name}.{new.name}@{new.version}"
    changes: list[EnumChange] = []
    if old.source_name != new.source_name or old.source_version != new.source_version:
        changes.append(
            EnumChange(
                kind="enum_projection_source_changed",
                owner=owner,
                breaking=True,
            )
        )

    old_members = set(old.members or old.selected)
    new_members = set(new.members or new.selected)
    for member in sorted(old_members - new_members):
        changes.append(EnumChange(kind="enum_projection_member_removed", owner=owner, member=member, breaking=True))
    for member in sorted(new_members - old_members):
        implicit = new.selection_kind == "omit" and member not in new.selected
        changes.append(
            EnumChange(
                kind="enum_projection_implicit_member_added" if implicit else "enum_projection_member_added",
                owner=owner,
                member=member,
                breaking=False,
                consequences=(EXHAUSTIVE_MATCH,) if not implicit else ("implicit_growth",),
            )
        )
    return changes


def describe_enum_change(change: EnumChange) -> str:
    label = {
        "enum_member_added": "adds member",
        "enum_member_removed": "removes member",
        "enum_projection_source_changed": "source changed",
        "enum_projection_member_added": "projection adds member",
        "enum_projection_member_removed": "projection removes member",
        "enum_projection_implicit_member_added": "implicitly includes member",
    }.get(change.kind, change.kind)
    text = f"{change.owner}: {label}"
    if change.member is not None:
        text += f" '{change.member}'"
    if EXHAUSTIVE_MATCH in change.consequences:
        text += " (exhaustive consumers must extend their handling)"
    if "implicit_growth" in change.consequences:
        text += " (implicit growth from omit rebase)"
    return text
