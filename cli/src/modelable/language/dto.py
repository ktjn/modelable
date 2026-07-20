from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, Self

CompletionKind = Literal["keyword", "annotation", "module", "class", "property", "reference", "value"]


@dataclass(frozen=True, order=True)
class LanguagePosition:
    line: int
    character: int


@dataclass(frozen=True, order=True)
class LanguageRange:
    start: LanguagePosition
    end: LanguagePosition

    @classmethod
    def at(
        cls,
        start_line: int,
        start_character: int,
        end_line: int,
        end_character: int,
    ) -> Self:
        value = cls(
            LanguagePosition(start_line, start_character),
            LanguagePosition(end_line, end_character),
        )
        value.validate()
        return value

    def validate(self) -> None:
        if self.start.line < 0 or self.start.character < 0:
            raise ValueError("Range start must be non-negative")
        if self.end.line < 0 or self.end.character < 0:
            raise ValueError("Range end must be non-negative")
        if self.end < self.start:
            raise ValueError("Range end must not precede its start")


@dataclass(frozen=True, order=True)
class LanguageLocation:
    uri: str
    range: LanguageRange


@dataclass(frozen=True)
class LanguageCompletion:
    label: str
    kind: CompletionKind | None
    sort_text: str
    detail: str | None = None
    documentation: str | None = None
    replacement: LanguageRange | None = None


@dataclass(frozen=True)
class LanguageHover:
    markdown: str
    range: LanguageRange | None


@dataclass(frozen=True)
class LanguagePreparedRename:
    range: LanguageRange
    placeholder: str


@dataclass(frozen=True)
class LanguageTextEdit:
    uri: str
    range: LanguageRange
    new_text: str
    expected_version: int
    expected_hash: str


def _canonical_edits(edits: Iterable[LanguageTextEdit]) -> tuple[LanguageTextEdit, ...]:
    ascending = sorted(edits, key=lambda edit: (edit.uri, edit.range))
    previous: LanguageTextEdit | None = None
    for edit in ascending:
        edit.range.validate()
        if previous is not None and edit.uri == previous.uri and edit.range.start < previous.range.end:
            raise ValueError(f"Text edit ranges overlap for {edit.uri}")
        previous = edit

    canonical: list[LanguageTextEdit] = []
    group_start = 0
    while group_start < len(ascending):
        group_end = group_start + 1
        while group_end < len(ascending) and ascending[group_end].uri == ascending[group_start].uri:
            group_end += 1
        canonical.extend(reversed(ascending[group_start:group_end]))
        group_start = group_end
    return tuple(canonical)


@dataclass(frozen=True)
class LanguageWorkspaceEdit:
    edits: tuple[LanguageTextEdit, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "edits", _canonical_edits(self.edits))

    @classmethod
    def from_edits(cls, edits: Iterable[LanguageTextEdit]) -> Self:
        return cls(tuple(edits))


class CompletionCatalog(Protocol):
    def domain_names(self) -> tuple[str, ...]: ...

    def references(self) -> tuple[tuple[str, str], ...]: ...

    def model_versions(self) -> tuple[tuple[str, str, int], ...]: ...

    def field_names(self, domain: str, name: str, version: int) -> tuple[str, ...]: ...
