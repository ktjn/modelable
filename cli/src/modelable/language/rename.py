from __future__ import annotations

import re
from dataclasses import dataclass

from modelable.compiler.workspace import Workspace
from modelable.language.dto import (
    LanguagePosition,
    LanguagePreparedRename,
    LanguageRange,
    LanguageTextEdit,
    LanguageWorkspaceEdit,
)
from modelable.language.positions import codepoint_to_utf16, document_lines, utf16_to_codepoint
from modelable.language.workspace import LanguageWorkspace
from modelable.parser.ir import JoinRef, SourceRef
from modelable.registry.resolver import resolve_model_ref

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_QUALIFIED_REF_PATTERN = re.compile(
    r"(?P<domain>[A-Za-z_][A-Za-z0-9_]*)\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_FIELD_REF_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<field>[A-Za-z_][A-Za-z0-9_]*)")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
)
_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_MODEL_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:"
)
_PROJECTION_FIELD_PATTERN = re.compile(
    r"^\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:<-|=)"
)
_WORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MODEL_DECL_KINDS = {"entity", "aggregate", "event", "value"}


class InvalidRenameError(Exception):
    pass


@dataclass(frozen=True)
class _Target:
    kind: str
    domain: str
    name: str
    version: int
    field_name: str | None
    range: LanguageRange


def prepare_rename(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
) -> LanguagePreparedRename | None:
    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        return None
    if not workspace.is_semantically_current():
        return None

    lines = document_lines(document.text)
    if position.line < 0 or position.line >= len(lines) or position.character < 0:
        return None
    try:
        character = utf16_to_codepoint(lines[position.line], position.character)
    except ValueError:
        return None

    target = _target_at(semantic, document.text, lines, position.line, character)
    if target is None:
        return None

    text_line = lines[position.line]
    start_cp = target.range.start.character
    end_cp = target.range.end.character
    placeholder = text_line[start_cp:end_cp]

    return LanguagePreparedRename(
        range=LanguageRange.at(
            position.line,
            codepoint_to_utf16(text_line, start_cp),
            position.line,
            codepoint_to_utf16(text_line, end_cp),
        ),
        placeholder=placeholder,
    )


def rename(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
    new_name: str,
) -> LanguageWorkspaceEdit:
    if not _IDENTIFIER_PATTERN.match(new_name):
        raise InvalidRenameError(f"Invalid identifier: {new_name}")

    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        raise InvalidRenameError("Document or workspace not available")
    if not workspace.is_semantically_current():
        raise InvalidRenameError("Workspace has unparsed changes")

    lines = document_lines(document.text)
    if position.line < 0 or position.line >= len(lines) or position.character < 0:
        raise InvalidRenameError("Position out of range")
    try:
        character = utf16_to_codepoint(lines[position.line], position.character)
    except ValueError as err:
        raise InvalidRenameError("Invalid character position") from err

    target = _target_at(semantic, document.text, lines, position.line, character)
    if target is None:
        raise InvalidRenameError("No renamable symbol at position")

    edits: list[LanguageTextEdit] = []
    hashes = workspace.current_hashes()

    if target.kind in {"model_decl", "projection_decl"}:
        _add_decl_renames(edits, semantic, workspace, hashes, target, new_name)
    elif target.kind == "model_field":
        _add_model_field_renames(edits, semantic, workspace, hashes, target, new_name)
    elif target.kind == "projection_field":
        _add_projection_field_renames(edits, semantic, workspace, hashes, target, new_name)
    else:
        raise InvalidRenameError("Unsupported rename target")

    if not edits:
        raise InvalidRenameError("No edits produced")

    return LanguageWorkspaceEdit.from_edits(edits)


def _target_at(
    semantic: Workspace,
    text: str,
    lines: tuple[str, ...],
    line: int,
    character: int,
) -> _Target | None:
    text_line = lines[line]

    for match in _QUALIFIED_REF_PATTERN.finditer(text_line):
        if not _contains(match.start(), match.end(), character):
            continue
        domain = match.group("domain")
        name = match.group("name")
        version = int(match.group("version"))
        domain_def = next((d for d in semantic.mdl.domains if d.name == domain), None)
        if domain_def is None:
            return None
        if name in domain_def.models:
            return _Target(
                kind="model_decl",
                domain=domain,
                name=name,
                version=version,
                field_name=None,
                range=LanguageRange.at(line, match.start("name"), line, match.end("name")),
            )
        if name in domain_def.projections:
            return _Target(
                kind="projection_decl",
                domain=domain,
                name=name,
                version=version,
                field_name=None,
                range=LanguageRange.at(line, match.start("name"), line, match.end("name")),
            )
        return None

    for match in _FIELD_REF_PATTERN.finditer(text_line):
        if not _contains(match.start(), match.end(), character):
            continue
        scope = _current_scope(text, line)
        if scope is None:
            return None
        domain_name, kind, name, version = scope
        if kind == "model":
            return _Target(
                kind="model_field",
                domain=domain_name,
                name=name,
                version=version,
                field_name=match.group("field"),
                range=LanguageRange.at(line, match.start("field"), line, match.end("field")),
            )
        alias_map = _projection_aliases(semantic, domain_name, name, version)
        target_model = alias_map.get(match.group("alias"))
        if target_model is not None and match.group("field"):
            return _Target(
                kind="model_field",
                domain=target_model[0],
                name=target_model[1],
                version=target_model[2],
                field_name=match.group("field"),
                range=LanguageRange.at(line, match.start("field"), line, match.end("field")),
            )
        return _Target(
            kind="projection_field",
            domain=domain_name,
            name=name,
            version=version,
            field_name=match.group("field"),
            range=LanguageRange.at(line, match.start("field"), line, match.end("field")),
        )

    word = _word_at(text_line, character)
    if word is None:
        return None

    scope = _current_scope(text, line)
    if scope is None:
        return None
    domain_name, kind, name, version = scope

    if word == name:
        return _Target(
            kind="model_decl" if kind == "model" else "projection_decl",
            domain=domain_name,
            name=name,
            version=version,
            field_name=None,
            range=LanguageRange.at(line, _word_start(text_line, word), line, _word_end(text_line, word)),
        )

    if kind == "model":
        if _is_field_name(semantic, domain_name, name, version, word):
            return _Target(
                kind="model_field",
                domain=domain_name,
                name=name,
                version=version,
                field_name=word,
                range=LanguageRange.at(line, _word_start(text_line, word), line, _word_end(text_line, word)),
            )
    else:
        if _is_projection_field_name(semantic, domain_name, name, version, word):
            return _Target(
                kind="projection_field",
                domain=domain_name,
                name=name,
                version=version,
                field_name=word,
                range=LanguageRange.at(line, _word_start(text_line, word), line, _word_end(text_line, word)),
            )
    return None


def _add_decl_renames(
    edits: list[LanguageTextEdit],
    semantic: Workspace,
    workspace: LanguageWorkspace,
    hashes: dict[str, str],
    target: _Target,
    new_name: str,
) -> None:
    decl_kind = "model" if target.kind == "model_decl" else "projection"
    declaration = _find_decl_location(semantic, target.domain, decl_kind, target.name, target.version)
    if declaration is not None:
        doc = workspace.current_document(declaration[0])
        if doc is not None:
            edits.append(_make_edit(declaration[0], declaration[1], new_name, doc.version, hashes))

    old_ref = f"{target.domain}.{target.name}@{target.version}"
    for source in semantic.sources:
        doc = workspace.current_document(source.uri)
        if doc is None:
            continue
        source_lines = document_lines(source.text)
        for line_no, line_text in enumerate(source_lines):
            for match in _QUALIFIED_REF_PATTERN.finditer(line_text):
                ref = f"{match.group('domain')}.{match.group('name')}@{match.group('version')}"
                if ref != old_ref:
                    continue
                edits.append(
                    _make_edit(
                        source.uri,
                        LanguageRange.at(line_no, match.start("name"), line_no, match.end("name")),
                        new_name,
                        doc.version,
                        hashes,
                    )
                )


def _add_model_field_renames(
    edits: list[LanguageTextEdit],
    semantic: Workspace,
    workspace: LanguageWorkspace,
    hashes: dict[str, str],
    target: _Target,
    new_name: str,
) -> None:
    declaration = _find_source_field_location(
        semantic,
        target.domain,
        target.name,
        target.version,
        target.field_name or "",
    )
    if declaration is not None:
        doc = workspace.current_document(declaration[0])
        if doc is not None:
            edits.append(_make_edit(declaration[0], declaration[1], new_name, doc.version, hashes))

    for source in semantic.sources:
        doc = workspace.current_document(source.uri)
        if doc is None:
            continue
        source_lines = document_lines(source.text)
        alias_map: dict[str, tuple[str, str, int]] = {}
        current_domain: str | None = None
        current_projection: tuple[str, int] | None = None
        for line_no, line_text in enumerate(source_lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                current_projection = None
                alias_map = {}
                continue

            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match and current_domain is not None:
                if decl_match.group("kind") == "projection":
                    current_projection = (decl_match.group("name"), int(decl_match.group("version")))
                    alias_map = _projection_aliases(semantic, current_domain, *current_projection)
                else:
                    current_projection = None
                    alias_map = {}
                continue

            if current_projection is None:
                continue

            for match in _FIELD_REF_PATTERN.finditer(line_text):
                target_model = alias_map.get(match.group("alias"))
                if target_model is None:
                    continue
                if target_model != (target.domain, target.name, target.version):
                    continue
                if match.group("field") != target.field_name:
                    continue
                edits.append(
                    _make_edit(
                        source.uri,
                        LanguageRange.at(line_no, match.start("field"), line_no, match.end("field")),
                        new_name,
                        doc.version,
                        hashes,
                    )
                )


def _add_projection_field_renames(
    edits: list[LanguageTextEdit],
    semantic: Workspace,
    workspace: LanguageWorkspace,
    hashes: dict[str, str],
    target: _Target,
    new_name: str,
) -> None:
    declaration = _find_source_field_location(
        semantic,
        target.domain,
        target.name,
        target.version,
        target.field_name or "",
    )
    if declaration is not None:
        doc = workspace.current_document(declaration[0])
        if doc is not None:
            edits.append(_make_edit(declaration[0], declaration[1], new_name, doc.version, hashes))

    for source in semantic.sources:
        doc = workspace.current_document(source.uri)
        if doc is None:
            continue
        source_lines = document_lines(source.text)
        alias_map: dict[str, tuple[str, str, int]] = {}
        current_domain: str | None = None
        current_projection: tuple[str, int] | None = None
        for line_no, line_text in enumerate(source_lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                current_projection = None
                alias_map = {}
                continue

            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match and current_domain is not None:
                if decl_match.group("kind") == "projection":
                    current_projection = (decl_match.group("name"), int(decl_match.group("version")))
                    alias_map = _projection_aliases(semantic, current_domain, *current_projection)
                else:
                    current_projection = None
                    alias_map = {}
                continue

            if current_projection is None:
                continue

            for match in _FIELD_REF_PATTERN.finditer(line_text):
                target_model = alias_map.get(match.group("alias"))
                if target_model is None:
                    continue
                if target_model != (target.domain, target.name, target.version):
                    continue
                if match.group("field") != target.field_name:
                    continue
                edits.append(
                    _make_edit(
                        source.uri,
                        LanguageRange.at(line_no, match.start("field"), line_no, match.end("field")),
                        new_name,
                        doc.version,
                        hashes,
                    )
                )


def _make_edit(
    uri: str,
    range: LanguageRange,
    new_text: str,
    version: int,
    hashes: dict[str, str],
) -> LanguageTextEdit:
    return LanguageTextEdit(
        uri=uri,
        range=range,
        new_text=new_text,
        expected_version=version,
        expected_hash=hashes.get(uri, ""),
    )


def _projection_aliases(
    workspace: Workspace,
    domain_name: str,
    projection_name: str,
    version: int,
) -> dict[str, tuple[str, str, int]]:
    domain = next((item for item in workspace.mdl.domains if item.name == domain_name), None)
    if domain is None:
        return {}
    versions = domain.projections.get(projection_name, [])
    projection_version = next((item for item in versions if item.version == version), None)
    if projection_version is None:
        return {}

    aliases: dict[str, tuple[str, str, int]] = {}
    all_sources: list[SourceRef | JoinRef] = [projection_version.source, *projection_version.joins]
    for source_ref in all_sources:
        try:
            resolved = resolve_model_ref(workspace.mdl, source_ref.model, source_ref.version)
        except LookupError:
            continue
        aliases[source_ref.alias] = (
            resolved.domain_name,
            resolved.model_name,
            resolved.version.version,
        )
    return aliases


def _find_source_field_location(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> tuple[str, LanguageRange] | None:
    for kind in ("model", "projection"):
        location = _find_field_location(workspace, domain_name, kind, model_name, version, field_name)
        if location is not None:
            return location
    return None


def _find_field_location(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
    field_name: str,
) -> tuple[str, LanguageRange] | None:
    for source in workspace.sources:
        current_domain: str | None = None
        active = False
        source_lines = document_lines(source.text)
        pattern = _MODEL_FIELD_PATTERN if kind == "model" else _PROJECTION_FIELD_PATTERN
        for line_no, line_text in enumerate(source_lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                active = False
                continue
            decl_match = _DECL_PATTERN.match(line_text)
            if decl_match and current_domain == domain_name:
                decl_kind = decl_match.group("kind")
                active = (
                    (decl_kind in _MODEL_DECL_KINDS if kind == "model" else decl_kind == kind)
                    and decl_match.group("name") == name
                    and int(decl_match.group("version")) == version
                )
                continue
            if not active:
                continue
            field_match = pattern.match(line_text)
            if field_match and field_match.group("name") == field_name:
                return (
                    source.uri,
                    LanguageRange.at(line_no, field_match.start("name"), line_no, field_match.end("name")),
                )
            if line_text.strip() == "}":
                active = False
    return None


def _find_decl_location(
    workspace: Workspace,
    domain_name: str,
    kind: str,
    name: str,
    version: int,
) -> tuple[str, LanguageRange] | None:
    for source in workspace.sources:
        current_domain: str | None = None
        source_lines = document_lines(source.text)
        for line_no, line_text in enumerate(source_lines):
            domain_match = _DOMAIN_PATTERN.match(line_text)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                continue
            decl_match = _DECL_PATTERN.match(line_text)
            if not decl_match or current_domain != domain_name:
                continue
            decl_kind = decl_match.group("kind")
            if kind == "model":
                if decl_kind not in _MODEL_DECL_KINDS:
                    continue
            elif decl_kind != kind:
                continue
            if decl_match.group("name") != name:
                continue
            if int(decl_match.group("version")) != version:
                continue
            return (
                source.uri,
                LanguageRange.at(line_no, decl_match.start("name"), line_no, decl_match.end("name")),
            )
    return None


def _current_scope(text: str, line: int) -> tuple[str, str, str, int] | None:
    lines = document_lines(text)
    current_domain: str | None = None
    current_kind: str | None = None
    current_name: str | None = None
    current_version: int | None = None
    for item in lines[: line + 1]:
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            current_kind = None
            current_name = None
            current_version = None
            continue
        decl_match = _DECL_PATTERN.match(item)
        if decl_match and current_domain is not None:
            current_kind = "model" if decl_match.group("kind") != "projection" else "projection"
            current_name = decl_match.group("name")
            current_version = int(decl_match.group("version"))
    if current_domain and current_kind and current_name and current_version is not None:
        return current_domain, current_kind, current_name, current_version
    return None


def _word_at(text_line: str, character: int) -> str | None:
    for match in _WORD_PATTERN.finditer(text_line):
        if _contains(match.start(), match.end(), character):
            return match.group(0)
    return None


def _word_start(text_line: str, word: str) -> int:
    match = re.search(rf"\b{re.escape(word)}\b", text_line)
    return match.start() if match is not None else 0


def _word_end(text_line: str, word: str) -> int:
    match = re.search(rf"\b{re.escape(word)}\b", text_line)
    return match.end() if match is not None else len(text_line)


def _is_field_name(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
    field_name: str,
) -> bool:
    return _find_field_location(workspace, domain_name, "model", model_name, version, field_name) is not None


def _is_projection_field_name(
    workspace: Workspace,
    domain_name: str,
    projection_name: str,
    version: int,
    field_name: str,
) -> bool:
    return _find_field_location(workspace, domain_name, "projection", projection_name, version, field_name) is not None


def _contains(start: int, end: int, character: int) -> bool:
    return start <= character <= max(end - 1, start)
