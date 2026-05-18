from __future__ import annotations

from dataclasses import dataclass
import re

from lsprotocol import types

from modelable.lsp.federation import (
    mirror_domain_names,
    mirror_field_names,
    mirror_model_versions,
    mirror_reference_names,
)
from modelable.lsp.workspace import LspWorkspaceIndex

_KEYWORDS = [
    "domain",
    "entity",
    "aggregate",
    "event",
    "value",
    "projection",
    "from",
    "join",
    "as",
    "group by",
]
_ANNOTATIONS = [
    "@key",
    "@pii",
    "@classification",
    "@deprecated",
    "@owner",
    "@server",
]
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_DOMAIN_PATTERN = re.compile(r"^\s*domain\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_WORD_PREFIX_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*$")
_ANNOTATION_PATTERN = re.compile(r"(?:^|\s)@[A-Za-z_][A-Za-z0-9_-]*$")
_REFERENCE_PATTERN = re.compile(r"\b(from|join)\s+[A-Za-z_][A-Za-z0-9_.-]*$")
_REFERENCE_VERSION_PATTERN = re.compile(
    r"\b(from|join)\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*$"
)
_IMPORT_VERSION_PATTERN = re.compile(
    r"\bimport\s+domain\s+[A-Za-z_][A-Za-z0-9_.-]*\s+from\s+registry\s+\"[^\"]+\""
    r"\s+at\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*$"
)
_ALIAS_FIELD_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.$")
_SOURCE_ALIAS_PATTERN = re.compile(
    r"^\s*(from|join)\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*(?P<version>\d+)\s+as\s+"
    r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+on\s+.*)?$"
)
_IMPORT_DOMAIN_PATTERN = re.compile(r"\bimport\s+domain\s+[A-Za-z_][A-Za-z0-9_.-]*$")
_DOMAIN_DECL_PATTERN = re.compile(r"^\s*domain\s+[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class _Scope:
    domain: str
    kind: str
    name: str
    version: int
    line: int


@dataclass(frozen=True)
class _Candidate:
    label: str
    kind: types.CompletionItemKind | None
    sort_rank: int


def build_completion(
    index: LspWorkspaceIndex,
    uri: str,
    line: int,
    character: int,
) -> types.CompletionList:
    source = index.documents.get(uri)
    workspace = index.workspace
    if source is None or workspace is None:
        return _empty_completion()

    lines = source.text.splitlines()
    if line < 0 or line >= len(lines):
        return _empty_completion()

    text_line = lines[line]
    cursor = max(character, 0)
    before_cursor = text_line[:cursor]
    prefix = _completion_prefix(before_cursor)
    scope = _current_scope(source.text, line)

    if _version_context(before_cursor):
        candidates = _version_candidates(index, before_cursor, prefix)
    elif _annotation_context(before_cursor):
        candidates = _annotation_candidates(prefix)
    elif _domain_context(before_cursor):
        candidates = _domain_candidates(workspace, prefix)
        candidates.extend(_mirror_domain_candidates(index, prefix))
    elif _reference_context(before_cursor):
        candidates = _workspace_reference_candidates(workspace, prefix)
        candidates.extend(_mirror_reference_candidates(index, prefix))
    elif _alias_context(before_cursor):
        candidates = _alias_field_candidates(index, source.text, scope, line, prefix)
    elif scope is not None and line > scope.line:
        candidates = _field_candidates(workspace, scope, prefix)
    else:
        candidates = _keyword_candidates(prefix)
        candidates.extend(_mirror_domain_candidates(index, prefix))

    return types.CompletionList(
        is_incomplete=False,
        items=[_to_completion_item(candidate, index) for index, candidate in enumerate(_dedupe(candidates))],
    )


def _empty_completion() -> types.CompletionList:
    return types.CompletionList(is_incomplete=False, items=[])


def _annotation_context(before_cursor: str) -> bool:
    stripped = before_cursor.rstrip()
    return stripped.endswith("@") or bool(_ANNOTATION_PATTERN.search(stripped))


def _domain_context(before_cursor: str) -> bool:
    stripped = before_cursor.rstrip()
    return (
        before_cursor.endswith("domain ")
        or before_cursor.endswith("import domain ")
        or bool(_IMPORT_DOMAIN_PATTERN.search(stripped))
        or bool(_DOMAIN_DECL_PATTERN.match(stripped))
    )


def _reference_context(before_cursor: str) -> bool:
    stripped = before_cursor.rstrip()
    return before_cursor.endswith("from ") or before_cursor.endswith("join ") or bool(
        _REFERENCE_PATTERN.search(stripped)
    )


def _keyword_candidates(prefix: str) -> list[_Candidate]:
    return _filtered_candidates(
        [
            _Candidate(label=keyword, kind=types.CompletionItemKind.Keyword, sort_rank=index + 10)
            for index, keyword in enumerate(_KEYWORDS)
        ],
        prefix,
    )


def _annotation_candidates(prefix: str) -> list[_Candidate]:
    return _filtered_candidates(
        [
            _Candidate(label=annotation, kind=types.CompletionItemKind.Keyword, sort_rank=index + 10)
            for index, annotation in enumerate(_ANNOTATIONS)
        ],
        prefix,
    )


def _domain_candidates(workspace, prefix: str) -> list[_Candidate]:
    names = sorted({domain.name for domain in workspace.mdl.domains})
    return _filtered_candidates(
        [
            _Candidate(label=name, kind=types.CompletionItemKind.Module, sort_rank=index + 20)
            for index, name in enumerate(names)
        ],
        prefix,
    )


def _workspace_reference_candidates(workspace, prefix: str) -> list[_Candidate]:
    names: list[_Candidate] = []
    for domain in workspace.mdl.domains:
        for model_name in sorted(domain.models):
            names.append(
                _Candidate(
                    label=f"{domain.name}.{model_name}",
                    kind=types.CompletionItemKind.Class,
                    sort_rank=100,
                )
            )
        for projection_name in sorted(domain.projections):
            names.append(
                _Candidate(
                    label=f"{domain.name}.{projection_name}",
                    kind=types.CompletionItemKind.Class,
                    sort_rank=120,
                )
            )
    names.sort(key=lambda candidate: (candidate.sort_rank, candidate.label.lower(), candidate.label))
    return _filtered_candidates(names, prefix)


def _mirror_domain_candidates(index: LspWorkspaceIndex, prefix: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for domain_name in mirror_domain_names(index):
        candidates.append(
            _Candidate(label=domain_name, kind=types.CompletionItemKind.Module, sort_rank=40)
        )
    return _filtered_candidates(candidates, prefix)


def _mirror_reference_candidates(index: LspWorkspaceIndex, prefix: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for domain_name, model_name in mirror_reference_names(index):
        candidates.append(
            _Candidate(
                label=f"{domain_name}.{model_name}",
                kind=types.CompletionItemKind.Class,
                sort_rank=150,
            )
        )
    return _filtered_candidates(candidates, prefix)


def _alias_field_candidates(
    index: LspWorkspaceIndex,
    text: str,
    scope: _Scope | None,
    line: int,
    prefix: str,
) -> list[_Candidate]:
    if scope is None:
        return []

    alias = _alias_name(text, line)
    if alias is None:
        return []

    reference = _projection_reference_for_alias(text, scope, line, alias)
    if reference is None:
        return []

    domain_name, model_name, version = reference
    fields = _mirror_or_workspace_fields(index, domain_name, model_name, version)
    candidates = [
        _Candidate(label=field_name, kind=types.CompletionItemKind.Field, sort_rank=index + 30)
        for index, field_name in enumerate(fields)
    ]
    return _filtered_candidates(candidates, prefix)


def _version_candidates(index: LspWorkspaceIndex, before_cursor: str, prefix: str) -> list[_Candidate]:
    context = _version_context(before_cursor)
    if context is None:
        return []

    domain_name, model_name = context
    candidates: list[_Candidate] = []
    for mirror_domain, mirror_model, version in mirror_model_versions(index):
        if mirror_domain == domain_name and mirror_model == model_name:
            candidates.append(
                _Candidate(
                    label=str(version),
                    kind=types.CompletionItemKind.Value,
                    sort_rank=160,
                )
            )
    return _filtered_candidates(candidates, prefix)


def _field_candidates(workspace, scope: _Scope, prefix: str) -> list[_Candidate]:
    domain = next((item for item in workspace.mdl.domains if item.name == scope.domain), None)
    if domain is None:
        return []

    if scope.kind == "projection":
        versions = domain.projections.get(scope.name, [])
    else:
        versions = domain.models.get(scope.name, [])

    version = next((item for item in versions if item.version == scope.version), None)
    if version is None:
        return []

    fields = getattr(version, "fields", [])
    candidates = [
        _Candidate(label=field.name, kind=types.CompletionItemKind.Field, sort_rank=index + 30)
        for index, field in enumerate(sorted(fields, key=lambda item: item.name))
    ]
    return _filtered_candidates(candidates, prefix)


def _filtered_candidates(candidates: list[_Candidate], prefix: str) -> list[_Candidate]:
    if not prefix:
        return candidates
    lowered = prefix.lower()
    return [candidate for candidate in candidates if candidate.label.lower().startswith(lowered)]


def _dedupe(candidates: list[_Candidate]) -> list[_Candidate]:
    seen: set[str] = set()
    deduped: list[_Candidate] = []
    for candidate in candidates:
        if candidate.label in seen:
            continue
        seen.add(candidate.label)
        deduped.append(candidate)
    return deduped


def _to_completion_item(candidate: _Candidate, index: int) -> types.CompletionItem:
    return types.CompletionItem(
        label=candidate.label,
        kind=candidate.kind,
        sort_text=f"{candidate.sort_rank:04d}-{index:04d}",
        insert_text=candidate.label,
        filter_text=candidate.label,
    )


def _completion_prefix(before_cursor: str) -> str:
    if not before_cursor:
        return ""

    version_match = re.search(r"@\s*([0-9]*)$", before_cursor)
    if version_match is not None:
        return version_match.group(1)

    if before_cursor.endswith("@"):
        return "@"

    annotation_match = re.search(r"@[A-Za-z_][A-Za-z0-9_-]*$", before_cursor)
    if annotation_match is not None:
        return annotation_match.group(0)

    stripped = before_cursor.rstrip()
    if stripped.endswith("group"):
        return "group"

    match = _WORD_PREFIX_PATTERN.search(before_cursor)
    if match is None:
        return ""
    return match.group(0)


def _alias_context(before_cursor: str) -> bool:
    stripped = before_cursor.rstrip()
    return bool(_ALIAS_FIELD_PATTERN.search(stripped))


def _version_context(before_cursor: str) -> tuple[str, str] | None:
    stripped = before_cursor.rstrip()
    import_match = _IMPORT_VERSION_PATTERN.search(stripped)
    if import_match is not None:
        return import_match.group("domain"), import_match.group("model")
    reference_match = _REFERENCE_VERSION_PATTERN.search(stripped)
    if reference_match is not None:
        return reference_match.group("domain"), reference_match.group("model")
    return None


def _alias_name(text: str, line: int) -> str | None:
    lines = text.splitlines()
    if line < 0 or line >= len(lines):
        return None
    match = _ALIAS_FIELD_PATTERN.search(lines[line][: len(lines[line])])
    if match is None:
        return None
    return match.group("alias")


def _projection_reference_for_alias(
    text: str,
    scope: _Scope,
    line: int,
    alias: str,
) -> tuple[str, str, int] | None:
    lines = text.splitlines()
    end_line = min(line, len(lines) - 1)
    for item in lines[scope.line + 1 : end_line + 1]:
        match = _SOURCE_ALIAS_PATTERN.match(item)
        if match is None:
            continue
        if match.group("alias") != alias:
            continue
        return match.group("domain"), match.group("model"), int(match.group("version"))
    return None


def _mirror_or_workspace_fields(
    index: LspWorkspaceIndex,
    domain_name: str,
    model_name: str,
    version: int,
) -> list[str]:
    workspace = index.workspace
    if workspace is not None:
        domain = next((item for item in workspace.mdl.domains if item.name == domain_name), None)
        if domain is not None:
            versions = domain.models.get(model_name, [])
            current = next((item for item in versions if item.version == version), None)
            if current is not None:
                return sorted(field.name for field in current.fields)
    return mirror_field_names(index, domain_name, model_name, version)


def _current_scope(text: str, line: int) -> _Scope | None:
    lines = text.splitlines()
    current_domain: str | None = None
    current_scope: _Scope | None = None
    for index, item in enumerate(lines[: line + 1]):
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("name")
            current_scope = None
            continue

        decl_match = _DECL_PATTERN.match(item)
        if decl_match and current_domain is not None:
            current_scope = _Scope(
                domain=current_domain,
                kind="projection" if decl_match.group("kind") == "projection" else "model",
                name=decl_match.group("name"),
                version=int(decl_match.group("version")),
                line=index,
            )

    return current_scope
