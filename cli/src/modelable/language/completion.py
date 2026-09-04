from __future__ import annotations

import re
from dataclasses import dataclass

from modelable.compiler.workspace import Workspace
from modelable.language.dto import (
    CompletionCatalog,
    CompletionKind,
    LanguageCompletion,
    LanguagePosition,
    LanguageRange,
)
from modelable.language.positions import codepoint_to_utf16, document_lines, utf16_to_codepoint
from modelable.language.scanning import DOMAIN_PATTERN as _DOMAIN_PATTERN
from modelable.language.workspace import LanguageDocument, LanguageWorkspace
from modelable.parser.ir import (
    AddFieldOp,
    DomainDef,
    EnumType,
    RemoveFieldOp,
    RenameFieldOp,
    ReplaceFieldOp,
    SemanticTypeDecl,
)
from modelable.registry.resolver import resolve_named_declaration

_KEYWORDS = (
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
)
_ANNOTATIONS = (
    "@key",
    "@pii",
    "@classification",
    "@deprecated",
    "@owner",
    "@server",
    "@wire",
)
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value|projection)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
    r"(?:.*?\bevolves\s*@\s*(?P<base>\d+))?"
)
_EVOLVES_OPERATION_LINE_PATTERN = re.compile(r"^\s*(?:add|remove|rename|replace)\b")
_EVOLVES_FIELD_OP_PATTERN = re.compile(r"^\s*(?:remove|rename|replace)\s+[A-Za-z_][A-Za-z0-9_]*$")
_WORD_PREFIX_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*$")
_ANNOTATION_PATTERN = re.compile(r"(?:^|\s)@[A-Za-z_][A-Za-z0-9_-]*$")
_REFERENCE_PATTERN = re.compile(r"\b(from|join)\s+[A-Za-z_][A-Za-z0-9_.-]*$")
_REFERENCE_VERSION_PATTERN = re.compile(
    r"\b(from|join)\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*(?P<prefix>\d*)$"
)
_IMPORT_VERSION_PATTERN = re.compile(
    r"\bimport\s+domain\s+[A-Za-z_][A-Za-z0-9_.-]*\s+from\s+registry\s+\"[^\"]+\""
    r"\s+at\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*(?P<prefix>\d*)$"
)
_IMPORT_PIN_MODEL_PATTERN = re.compile(
    r"\bimport\s+domain\s+[A-Za-z_][A-Za-z0-9_.-]*\s+from\s+registry\s+\"[^\"]+\""
    r"\s+at\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\.(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)?$"
)
_ALIAS_FIELD_PATTERN = re.compile(r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)\.(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)?$")
_SOURCE_ALIAS_PATTERN = re.compile(
    r"^\s*(from|join)\s+(?P<domain>[A-Za-z_][A-Za-z0-9_.-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_.-]*)\s*@\s*(?P<version>\d+)\s+as\s+"
    r"(?P<alias>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s+on\s+.*)?$"
)
_IMPORT_DOMAIN_PATTERN = re.compile(r"\bimport\s+domain\s+[A-Za-z_][A-Za-z0-9_.-]*$")
_DOMAIN_DECL_PATTERN = re.compile(r"^\s*domain\s+[A-Za-z_][A-Za-z0-9_-]*$")
_ENUM_PROJECTION_HEADER_PATTERN = re.compile(r"^\s*enum\s+projection\s+[A-Za-z_][A-Za-z0-9_]*")
_ENUM_PROJECTION_FROM_PATTERN = re.compile(r"^\s*from\s+(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*@\s*(?P<version>\d+)\s*$")
_PICK_OMIT_PATTERN = re.compile(
    r"\b(?:pick|omit)\s*\(\s*(?P<already>(?:[A-Za-z_][A-Za-z0-9_]*\s*,\s*)*)(?P<prefix>[A-Za-z_][A-Za-z0-9_]*)?$"
)


@dataclass(frozen=True)
class _Scope:
    domain: str
    kind: str
    name: str
    version: int
    line: int
    base_version: int | None = None


@dataclass(frozen=True)
class _Candidate:
    label: str
    kind: CompletionKind


def complete(
    workspace: LanguageWorkspace,
    uri: str,
    position: LanguagePosition,
    catalog: CompletionCatalog | None = None,
) -> tuple[LanguageCompletion, ...]:
    document = workspace.current_document(uri)
    semantic = workspace.semantic_workspace()
    if document is None or semantic is None:
        return ()

    lines = document_lines(document.text)
    if position.line < 0 or position.line >= len(lines) or position.character < 0:
        return ()
    try:
        cursor = utf16_to_codepoint(lines[position.line], position.character)
    except ValueError:
        return ()

    candidates, prefix = _candidates(
        document.text,
        semantic,
        position.line,
        cursor,
        catalog,
    )
    replacement = _replacement_range(document, position.line, cursor, prefix)
    return tuple(
        LanguageCompletion(
            label=candidate.label,
            kind=candidate.kind,
            sort_text=f"{index:04d}",
            replacement=replacement,
        )
        for index, candidate in enumerate(_dedupe(candidates))
    )


def _candidates(
    text: str,
    workspace: Workspace,
    line: int,
    cursor: int,
    catalog: CompletionCatalog | None,
) -> tuple[list[_Candidate], str]:
    text_line = document_lines(text)[line]
    before_cursor = text_line[:cursor]
    prefix = _completion_prefix(before_cursor)
    scope = _current_scope(text, line)

    if _version_context(before_cursor):
        prefix = _version_prefix(before_cursor)
        candidates = _version_candidates(catalog, before_cursor, prefix)
    elif _annotation_context(before_cursor):
        if before_cursor.endswith("@"):
            prefix = "@"
        candidates = _annotation_candidates(prefix)
    elif _import_pin_model_context(before_cursor):
        candidates = _import_pin_model_candidates(catalog, before_cursor, prefix)
    elif _pick_omit_context(before_cursor):
        candidates = _pick_omit_candidates(workspace, text, line, before_cursor)
    elif _domain_context(before_cursor):
        candidates = _domain_candidates(workspace, prefix)
        candidates.extend(_catalog_domain_candidates(catalog, prefix))
    elif _reference_context(before_cursor):
        candidates = _workspace_reference_candidates(workspace, prefix)
        candidates.extend(_catalog_reference_candidates(catalog, prefix))
    elif _alias_context(before_cursor):
        candidates = _alias_field_candidates(
            catalog,
            workspace,
            text,
            scope,
            line,
            before_cursor,
            prefix,
        )
    elif scope is not None and scope.base_version is not None and _evolves_operation_context(before_cursor):
        candidates = _evolves_operation_candidates(workspace, text, scope, line, prefix)
    elif scope is not None and line > scope.line:
        candidates = _field_candidates(workspace, scope, prefix)
    else:
        candidates = _keyword_candidates(prefix)
        candidates.extend(_catalog_domain_candidates(catalog, prefix))
    return candidates, prefix


def _replacement_range(
    document: LanguageDocument,
    line: int,
    cursor: int,
    prefix: str,
) -> LanguageRange:
    text_line = document_lines(document.text)[line]
    start = cursor - len(prefix)
    return LanguageRange.at(
        line,
        codepoint_to_utf16(text_line, start),
        line,
        codepoint_to_utf16(text_line, cursor),
    )


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
    return (
        before_cursor.endswith("from ") or before_cursor.endswith("join ") or bool(_REFERENCE_PATTERN.search(stripped))
    )


def _keyword_candidates(prefix: str) -> list[_Candidate]:
    return _filtered_candidates([_Candidate(keyword, "keyword") for keyword in _KEYWORDS], prefix)


def _annotation_candidates(prefix: str) -> list[_Candidate]:
    return _filtered_candidates([_Candidate(annotation, "annotation") for annotation in _ANNOTATIONS], prefix)


def _domain_candidates(workspace: Workspace, prefix: str) -> list[_Candidate]:
    names = sorted({domain.name for domain in workspace.mdl.domains})
    return _filtered_candidates([_Candidate(name, "module") for name in names], prefix)


def _workspace_reference_candidates(workspace: Workspace, prefix: str) -> list[_Candidate]:
    models: list[_Candidate] = []
    projections: list[_Candidate] = []
    for domain in workspace.mdl.domains:
        models.extend(_Candidate(f"{domain.name}.{name}", "class") for name in sorted(domain.models))
        projections.extend(_Candidate(f"{domain.name}.{name}", "class") for name in sorted(domain.projections))
    models.sort(key=lambda candidate: (candidate.label.lower(), candidate.label))
    projections.sort(key=lambda candidate: (candidate.label.lower(), candidate.label))
    return _filtered_candidates(models + projections, prefix)


def _catalog_domain_candidates(
    catalog: CompletionCatalog | None,
    prefix: str,
) -> list[_Candidate]:
    if catalog is None:
        return []
    return _filtered_candidates(
        [_Candidate(name, "module") for name in sorted(catalog.domain_names())],
        prefix,
    )


def _catalog_reference_candidates(
    catalog: CompletionCatalog | None,
    prefix: str,
) -> list[_Candidate]:
    if catalog is None:
        return []
    return _filtered_candidates(
        [_Candidate(f"{domain}.{name}", "class") for domain, name in sorted(catalog.references())],
        prefix,
    )


def _alias_field_candidates(
    catalog: CompletionCatalog | None,
    workspace: Workspace,
    text: str,
    scope: _Scope | None,
    line: int,
    before_cursor: str,
    prefix: str,
) -> list[_Candidate]:
    alias_match = _alias_name(before_cursor)
    if alias_match is None:
        return []
    alias, alias_prefix = alias_match

    if scope is not None:
        reference = _projection_reference_for_alias(text, scope, line, alias)
        if reference is not None:
            domain_name, model_name, version = reference
            fields = _workspace_fields(workspace, domain_name, model_name, version)
            if not fields and catalog is not None:
                fields = tuple(sorted(catalog.field_names(domain_name, model_name, version)))
            candidates = [_Candidate(field_name, "property") for field_name in fields]
            return _filtered_candidates(candidates, alias_prefix or prefix)

    # Not a projection-source alias -- if it names a domain directly (the
    # shape a field type reference takes, e.g. `status: orders.OrderStatus @
    # 1`), offer everything the domain declares: models, projections,
    # semantic types, and enum projections.
    domain = next((item for item in workspace.mdl.domains if item.name == alias), None)
    if domain is None:
        return []
    candidates = _domain_member_candidates(domain)
    return _filtered_candidates(candidates, alias_prefix or prefix)


def _domain_member_candidates(domain: DomainDef) -> list[_Candidate]:
    names: set[str] = set()
    names.update(domain.models)
    names.update(domain.projections)
    names.update(item.name for item in domain.semantic_types)
    names.update(item.name for item in domain.enum_projections)
    return [_Candidate(name, "class") for name in sorted(names)]


def _version_candidates(
    catalog: CompletionCatalog | None,
    before_cursor: str,
    prefix: str,
) -> list[_Candidate]:
    context = _version_context(before_cursor)
    if context is None or catalog is None:
        return []
    domain_name, model_name = context
    version_prefix = _version_prefix(before_cursor)
    candidates = [
        _Candidate(str(version), "value")
        for domain, model, version in sorted(catalog.model_versions())
        if domain == domain_name
        and model == model_name
        and (not version_prefix or str(version).startswith(version_prefix))
    ]
    return _filtered_candidates(candidates, prefix)


def _field_candidates(workspace: Workspace, scope: _Scope, prefix: str) -> list[_Candidate]:
    fields = _workspace_fields(workspace, scope.domain, scope.name, scope.version)
    return _filtered_candidates([_Candidate(field, "property") for field in fields], prefix)


def _workspace_fields(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
) -> tuple[str, ...]:
    domain = next((item for item in workspace.mdl.domains if item.name == domain_name), None)
    if domain is None:
        return ()
    model = next(
        (item for item in domain.models.get(model_name, []) if item.version == version),
        None,
    )
    if model is not None:
        return tuple(sorted(field.name for field in model.fields))
    projection = next(
        (item for item in domain.projections.get(model_name, []) if item.version == version),
        None,
    )
    if projection is not None:
        return tuple(sorted(field.name for field in projection.fields))
    return ()


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
    return "" if match is None else match.group(0)


def _alias_context(before_cursor: str) -> bool:
    return bool(_ALIAS_FIELD_PATTERN.search(before_cursor.rstrip()))


def _version_context(before_cursor: str) -> tuple[str, str] | None:
    stripped = before_cursor.rstrip()
    import_match = _IMPORT_VERSION_PATTERN.search(stripped)
    if import_match is not None:
        return import_match.group("domain"), import_match.group("model")
    reference_match = _REFERENCE_VERSION_PATTERN.search(stripped)
    if reference_match is not None:
        return reference_match.group("domain"), reference_match.group("model")
    return None


def _version_prefix(before_cursor: str) -> str:
    stripped = before_cursor.rstrip()
    import_match = _IMPORT_VERSION_PATTERN.search(stripped)
    if import_match is not None:
        return import_match.group("prefix") or ""
    reference_match = _REFERENCE_VERSION_PATTERN.search(stripped)
    if reference_match is not None:
        return reference_match.group("prefix") or ""
    return ""


def _import_pin_model_context(before_cursor: str) -> bool:
    return bool(_IMPORT_PIN_MODEL_PATTERN.search(before_cursor.rstrip()))


def _import_pin_model_candidates(
    catalog: CompletionCatalog | None,
    before_cursor: str,
    prefix: str,
) -> list[_Candidate]:
    match = _IMPORT_PIN_MODEL_PATTERN.search(before_cursor.rstrip())
    if match is None or catalog is None:
        return []
    domain_name = match.group("domain")
    model_prefix = match.group("prefix") or ""
    candidates = [
        _Candidate(model_name, "class")
        for domain, model_name in sorted(catalog.references())
        if domain == domain_name and (not model_prefix or model_name.lower().startswith(model_prefix.lower()))
    ]
    return _filtered_candidates(candidates, prefix)


def _pick_omit_context(before_cursor: str) -> bool:
    return bool(_PICK_OMIT_PATTERN.search(before_cursor))


def _pick_omit_candidates(
    workspace: Workspace,
    text: str,
    line: int,
    before_cursor: str,
) -> list[_Candidate]:
    match = _PICK_OMIT_PATTERN.search(before_cursor)
    if match is None:
        return []
    already = {item.strip() for item in match.group("already").split(",") if item.strip()}
    member_prefix = match.group("prefix") or ""
    source = _enum_projection_source_for_line(text, workspace, line)
    if source is None:
        return []
    _declaring_domain, decl = source
    if not isinstance(decl.underlying, EnumType):
        return []
    candidates = [_Candidate(value, "value") for value in decl.underlying.values if value not in already]
    return _filtered_candidates(candidates, member_prefix)


def _enum_projection_source_for_line(
    text: str,
    workspace: Workspace,
    line: int,
) -> tuple[str, SemanticTypeDecl] | None:
    """Find the `from Source @ version` this line's `pick`/`omit` clause belongs
    to by scanning backward for the nearest preceding `enum projection` header
    and its `from` clause -- `pick`/`omit` only ever appears immediately after
    one in the grammar, so the most recently seen pair is always correct."""
    current_domain: str | None = None
    pending_from: tuple[str, int] | None = None
    for item in document_lines(text)[: line + 1]:
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            pending_from = None
            continue
        if _ENUM_PROJECTION_HEADER_PATTERN.match(item):
            pending_from = None
            continue
        from_match = _ENUM_PROJECTION_FROM_PATTERN.match(item)
        if from_match is not None:
            pending_from = (from_match.group("name"), int(from_match.group("version")))
    if current_domain is None or pending_from is None:
        return None
    source_name, source_version = pending_from
    try:
        resolved = resolve_named_declaration(
            workspace.mdl,
            current_domain,
            source_name,
            exact_version=source_version,
            include_enum_projections=False,
        )
        if not isinstance(resolved.declaration, SemanticTypeDecl):
            return None
        return resolved.domain_name, resolved.declaration
    except LookupError:
        return None


def _alias_name(before_cursor: str) -> tuple[str, str] | None:
    match = _ALIAS_FIELD_PATTERN.search(before_cursor)
    if match is None:
        return None
    return match.group("alias"), match.group("prefix") or ""


def _projection_reference_for_alias(
    text: str,
    scope: _Scope,
    line: int,
    alias: str,
) -> tuple[str, str, int] | None:
    lines = document_lines(text)
    end_line = min(line, len(lines) - 1)
    for item in lines[scope.line + 1 : end_line + 1]:
        match = _SOURCE_ALIAS_PATTERN.match(item)
        if match is not None and match.group("alias") == alias:
            return match.group("domain"), match.group("model"), int(match.group("version"))
    return None


def _evolves_operation_context(before_cursor: str) -> bool:
    return (
        before_cursor.endswith("remove ")
        or before_cursor.endswith("rename ")
        or before_cursor.endswith("replace ")
        or bool(_EVOLVES_FIELD_OP_PATTERN.match(before_cursor.rstrip()))
    )


def _evolves_operation_candidates(
    workspace: Workspace,
    text: str,
    scope: _Scope,
    line: int,
    prefix: str,
) -> list[_Candidate]:
    fields = _evolves_intermediate_fields(workspace, text, scope, line)
    return _filtered_candidates([_Candidate(field, "property") for field in fields], prefix)


def _evolves_intermediate_fields(
    workspace: Workspace,
    text: str,
    scope: _Scope,
    line: int,
) -> tuple[str, ...]:
    """Replay this evolves block's operations from its base version up to (but
    not including) the operation on `line`, so `remove`/`rename`/`replace`
    offer the field names valid at that point in the sequence -- not only the
    base version's original fields or the fully expanded final version."""
    if scope.base_version is None:
        return ()
    domain = next((item for item in workspace.mdl.domains if item.name == scope.domain), None)
    if domain is None:
        return ()
    evolution = next(
        (item for item in domain.model_evolutions if item.name == scope.name and item.version == scope.version),
        None,
    )
    if evolution is None:
        return ()

    field_names = list(_workspace_fields(workspace, scope.domain, scope.name, scope.base_version))
    preceding = sum(
        1 for item in document_lines(text)[scope.line + 1 : line] if _EVOLVES_OPERATION_LINE_PATTERN.match(item)
    )
    for operation in evolution.operations[:preceding]:
        if isinstance(operation, AddFieldOp):
            if operation.field.name not in field_names:
                field_names.append(operation.field.name)
        elif isinstance(operation, RemoveFieldOp):
            if operation.field_name in field_names:
                field_names.remove(operation.field_name)
        elif isinstance(operation, RenameFieldOp):
            if operation.old_name in field_names:
                field_names[field_names.index(operation.old_name)] = operation.new_name
        elif isinstance(operation, ReplaceFieldOp) and operation.field.name not in field_names:
            field_names.append(operation.field.name)
    return tuple(sorted(field_names))


def _current_scope(text: str, line: int) -> _Scope | None:
    current_domain: str | None = None
    current_scope: _Scope | None = None
    for index, item in enumerate(document_lines(text)[: line + 1]):
        domain_match = _DOMAIN_PATTERN.match(item)
        if domain_match:
            current_domain = domain_match.group("quoted") or domain_match.group("name")
            current_scope = None
            continue
        declaration = _DECL_PATTERN.match(item)
        if declaration and current_domain is not None:
            base = declaration.group("base")
            current_scope = _Scope(
                domain=current_domain,
                kind="projection" if declaration.group("kind") == "projection" else "model",
                name=declaration.group("name"),
                version=int(declaration.group("version")),
                line=index,
                base_version=int(base) if base is not None else None,
            )
    return current_scope
