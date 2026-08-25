"""Explicit enum extraction (evolution plan A1, instruction #2's direct-
reference case).

Converts a set of hand-selected `enum(...)` field-type occurrences (see the
`ENUMSHAPE` discovery lint in `compiler/workspace.py`) that share an exact
member set into references to a single new named `semantic` enum
declaration.

Deliberately **not** built on `llm/workspace_editor.py`'s IR-mutate-and-
`render_mdl`-the-whole-file approach: `render_mdl` operates on the parsed
IR, which never carries comments (`COMMENT` is a `%ignore`d lexer token,
absent from the grammar's parse tree entirely) -- re-rendering a changed
file through it would silently drop any comment that file has, regardless
of whether the comment is anywhere near the edit. This module instead
performs surgical, line-level text edits: every line the plan does not
explicitly touch is copied through byte-for-byte, so comments elsewhere in
an edited file are never at risk, and a location this module cannot safely
rewrite aborts instead of guessing (instruction #4).

**Instruction #2's "whether intentional subsets become enum projections"
case is deliberately not implemented here.** Routing a subset occurrence
through an `enum projection` requires that occurrence's field to be
*retyped to reference the projection* -- and the language does not support
that today: `resolve_semantic_type_ref` (`registry/resolver.py`), the only
resolution path a field's `NamedType`/`EnumRefType` goes through, looks up
`domain.semantic_types` exclusively and has no fallback to
`domain.enum_projections`. Verified directly: `status: PublicOrderStatus @
1` on a model field is rejected today with `ENUMREF: unknown semantic type
'PublicOrderStatus'`, even though the exact same projection name resolves
fine as an `enum projection`'s own declaration. This is a genuine,
separate, pre-existing gap in field-type resolution, not an extraction-
tooling gap -- fixing it means extending `resolve_semantic_type_ref` (or
adding a parallel resolution path) to recognize enum projections as valid
field types, which is compiler surface area with its own audit, well
beyond this refactor tool. Left as an explicit follow-up.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from modelable.compiler.workspace import (
    Workspace,
    WorkspaceDocumentSource,
    load_workspace,
    load_workspace_from_sources,
)
from modelable.diagnostics.model import render_diagnostic
from modelable.parser.ir import EnumType
from modelable.refactor._target_emitters import TARGET_EMITTERS

_DOMAIN_PATTERN = re.compile(r'^\s*domain\s+(?:"(?P<quoted>[^"]+)"|(?P<name>[A-Za-z_][A-Za-z0-9_]*))')
_DOMAIN_ATTR_PATTERN = re.compile(r"^\s*(?:owner|contact|description)\s*:")
_DECL_PATTERN = re.compile(
    r"^\s*(?P<kind>entity|aggregate|event|value)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*@\s*(?P<version>\d+)"
    r"(?:.*?\bevolves\s*@\s*(?P<base>\d+))?"
)
_FIELD_ENUM_TYPE_PATTERN = re.compile(
    r"^(?P<prefix>\s*(?:@[A-Za-z_][A-Za-z0-9_]*(?:\([^)]*\))?\s+)*"
    r"(?P<field_name>[A-Za-z_][A-Za-z0-9_]*)\??\s*:\s*)"
    r"enum\(\s*(?P<members>[^)]*)\)"
    r"(?P<suffix>.*)$"
)


class ExtractEnumError(ValueError):
    pass


@dataclass(frozen=True)
class FieldLocation:
    domain: str
    model: str
    version: int
    field: str

    def __str__(self) -> str:
        return f"{self.domain}.{self.model}@{self.version}.{self.field}"


@dataclass(frozen=True)
class ExtractEnumPlan:
    canonical_name: str
    owning_domain: str
    change_kind: str
    fields: tuple[FieldLocation, ...]


@dataclass(frozen=True)
class ExtractEnumResult:
    canonical_members: tuple[str, ...]
    written_paths: tuple[Path, ...]
    diff_text: str
    workspace: Workspace


def parse_field_location(text: str) -> FieldLocation:
    if "@" not in text:
        raise ExtractEnumError(f"invalid field location '{text}': expected domain.Model@version.field")
    model_ref, rest = text.split("@", 1)
    if "." not in model_ref or "." not in rest:
        raise ExtractEnumError(f"invalid field location '{text}': expected domain.Model@version.field")
    domain, model = model_ref.split(".", 1)
    version_text, field_name = rest.split(".", 1)
    if "." in field_name:
        raise ExtractEnumError(
            f"invalid field location '{text}': nested object fields are not supported by extraction yet"
        )
    try:
        version = int(version_text)
    except ValueError as exc:
        raise ExtractEnumError(f"invalid field location '{text}': version must be an integer") from exc
    return FieldLocation(domain=domain, model=model, version=version, field=field_name)


def extract_enum(root: Path, plan: ExtractEnumPlan) -> ExtractEnumResult:
    if len(plan.fields) < 2:
        raise ExtractEnumError("at least two field selections are required to extract a shared enum")
    if len(set(plan.fields)) != len(plan.fields):
        raise ExtractEnumError("duplicate field selection: each location may only be selected once")

    workspace = load_workspace(root)
    error_diagnostics = [d for d in workspace.errors if d.severity == "error"]
    if error_diagnostics:
        rendered = "; ".join(render_diagnostic(d) for d in error_diagnostics)
        raise ExtractEnumError(f"workspace has validation errors: {rendered}")

    owning_domain_def = next((d for d in workspace.mdl.domains if d.name == plan.owning_domain), None)
    if owning_domain_def is None:
        raise ExtractEnumError(f"domain '{plan.owning_domain}' not found")
    if (
        plan.canonical_name in owning_domain_def.models
        or plan.canonical_name in owning_domain_def.projections
        or any(item.name == plan.canonical_name for item in owning_domain_def.semantic_types)
        or any(item.name == plan.canonical_name for item in owning_domain_def.enum_projections)
    ):
        raise ExtractEnumError(f"'{plan.canonical_name}' already exists in domain '{plan.owning_domain}'")

    member_sets = [frozenset(_field_enum_values(workspace, location)) for location in plan.fields]
    if len(set(member_sets)) > 1:
        mismatched = ", ".join(str(location) for location in plan.fields)
        raise ExtractEnumError(
            f"selections do not all share the same member set: {mismatched} -- extraction never "
            "merges differently-shaped fields automatically; select occurrences with an identical "
            "member set (see the ENUMSHAPE discovery lint)"
        )
    canonical_members = sorted(member_sets[0])

    sources_by_path: dict[Path, list[str]] = {
        source.path: source.text.splitlines() for source in workspace.sources if source.path is not None
    }

    rewrites: list[tuple[Path, int, str]] = [
        _rewrite_field_line(sources_by_path, location, f"{plan.canonical_name} @ 1") for location in plan.fields
    ]
    for path, line_index, new_line in rewrites:
        sources_by_path[path][line_index] = new_line

    semantic_decl_lines = [
        f"  semantic {plan.canonical_name} @ 1 ({plan.change_kind}): enum({', '.join(canonical_members)})",
    ]
    _insert_domain_declaration(sources_by_path, plan.owning_domain, semantic_decl_lines)

    candidate_texts = {path: "\n".join(lines) + "\n" for path, lines in sources_by_path.items()}
    changed_paths = {path for path, _, _ in rewrites} | {_domain_source_path(workspace, plan.owning_domain)}

    candidate_sources = [
        WorkspaceDocumentSource(path=path, uri=path.resolve().as_uri(), text=candidate_texts[path])
        for path in sorted(candidate_texts)
    ]
    candidate_workspace = load_workspace_from_sources(candidate_sources)
    candidate_errors = [d for d in candidate_workspace.errors if d.severity == "error"]
    if candidate_errors:
        rendered = "; ".join(render_diagnostic(d) for d in candidate_errors)
        raise ExtractEnumError(f"extraction would produce an invalid workspace: {rendered}")

    _validate_target_outputs(candidate_workspace)

    diff_text = _build_diff(workspace, candidate_texts, changed_paths)

    return ExtractEnumResult(
        canonical_members=tuple(canonical_members),
        written_paths=tuple(sorted(changed_paths)),
        diff_text=diff_text,
        workspace=candidate_workspace,
    )


def apply_extract_enum(root: Path, plan: ExtractEnumPlan) -> ExtractEnumResult:
    result = extract_enum(root, plan)
    written_paths = set(result.written_paths)
    candidate_texts = {source.path: source.text for source in result.workspace.sources if source.path in written_paths}
    originals: dict[Path, bytes] = {}
    written: list[Path] = []
    try:
        for path in result.written_paths:
            originals[path] = path.read_bytes()
        for path in result.written_paths:
            path.write_text(candidate_texts[path], encoding="utf-8", newline="\n")
            written.append(path)
        reloaded = load_workspace(root)
        reload_errors = [d for d in reloaded.errors if d.severity == "error"]
        if reload_errors:
            rendered = "; ".join(render_diagnostic(d) for d in reload_errors)
            raise ExtractEnumError(f"reloaded workspace has validation errors: {rendered}")
    except Exception:
        for path in written:
            path.write_bytes(originals[path])
        raise
    return result


def _field_enum_values(workspace: Workspace, location: FieldLocation) -> list[str]:
    domain = next((d for d in workspace.mdl.domains if d.name == location.domain), None)
    if domain is None:
        raise ExtractEnumError(f"{location}: domain not found")
    versions = domain.models.get(location.model, [])
    version = next((v for v in versions if v.version == location.version), None)
    if version is None:
        raise ExtractEnumError(f"{location}: model version not found")
    model_field = next((f for f in version.fields if f.name == location.field), None)
    if model_field is None:
        raise ExtractEnumError(f"{location}: field not found")
    if not isinstance(model_field.type, EnumType):
        raise ExtractEnumError(f"{location}: field is not an anonymous enum(...) type")
    return list(model_field.type.values)


def _domain_source_path(workspace: Workspace, domain_name: str) -> Path:
    for source in workspace.sources:
        if any(d.name == domain_name for d in source.mdl.domains) and source.path is not None:
            return source.path
    raise ExtractEnumError(f"domain '{domain_name}' not found in any source file")


def _rewrite_field_line(
    sources_by_path: dict[Path, list[str]],
    location: FieldLocation,
    replacement_type_text: str,
) -> tuple[Path, int, str]:
    for path, lines in sources_by_path.items():
        current_domain: str | None = None
        in_target_model = False
        for index, line in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line)
            if domain_match:
                current_domain = domain_match.group("quoted") or domain_match.group("name")
                in_target_model = False
                continue
            if current_domain != location.domain:
                continue
            decl_match = _DECL_PATTERN.match(line)
            if decl_match:
                in_target_model = (
                    decl_match.group("name") == location.model and int(decl_match.group("version")) == location.version
                )
                if in_target_model and decl_match.group("base") is not None:
                    raise ExtractEnumError(
                        f"{location}: this version is declared via `evolves` -- extraction only supports a "
                        "version where the field's enum(...) type is textually declared directly; extract "
                        "from the version where it was originally written instead"
                    )
                continue
            if not in_target_model:
                continue
            if line.strip() == "}":
                in_target_model = False
                continue
            field_match = _FIELD_ENUM_TYPE_PATTERN.match(line)
            if field_match is None or field_match.group("field_name") != location.field:
                continue
            new_line = f"{field_match.group('prefix')}{replacement_type_text}{field_match.group('suffix')}"
            return path, index, new_line
    raise ExtractEnumError(
        f"{location}: could not locate a single-line `enum(...)` field declaration to rewrite -- "
        "aborting rather than guess (this can happen if the type spans multiple lines, or the field "
        "does not exist at this exact location)"
    )


def _insert_domain_declaration(
    sources_by_path: dict[Path, list[str]],
    domain_name: str,
    declaration_lines: list[str],
) -> None:
    for lines in sources_by_path.values():
        for index, line in enumerate(lines):
            domain_match = _DOMAIN_PATTERN.match(line)
            if not domain_match:
                continue
            if (domain_match.group("quoted") or domain_match.group("name")) != domain_name:
                continue
            insert_at = index + 1
            while insert_at < len(lines) and _DOMAIN_ATTR_PATTERN.match(lines[insert_at]):
                insert_at += 1
            lines[insert_at:insert_at] = ["", *declaration_lines]
            return
    raise ExtractEnumError(f"domain '{domain_name}' not found in any source file")


def _validate_target_outputs(workspace: Workspace) -> None:
    out_dir = Path("extract-enum-preview")
    for target_name, emitter in TARGET_EMITTERS.items():
        try:
            emitter(workspace, out_dir)  # type: ignore[operator]
        except Exception as exc:
            raise ExtractEnumError(f"extraction would break target '{target_name}': {exc}") from exc


def _build_diff(original_workspace: Workspace, candidate_texts: dict[Path, str], changed_paths: set[Path]) -> str:
    original_by_path = {source.path: source.text for source in original_workspace.sources if source.path is not None}
    chunks: list[str] = []
    for path in sorted(changed_paths):
        original_text = original_by_path.get(path, "")
        candidate_text = candidate_texts[path]
        diff = difflib.unified_diff(
            original_text.splitlines(keepends=True),
            candidate_text.splitlines(keepends=True),
            fromfile=str(path),
            tofile=str(path),
        )
        chunks.append("".join(diff))
    return "\n".join(chunks)
