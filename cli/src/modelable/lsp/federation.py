from __future__ import annotations

import re
from pathlib import Path

from modelable.diagnostics.model import Diagnostic
from modelable.lsp.workspace import LspWorkspaceIndex
from modelable.parser.parse import parse_text_to_ir
from modelable.registry.signature import compute_version_signature

_PINNED_IMPORT_PATTERN = re.compile(
    r"^\s*import\s+domain\s+(?P<domain>[A-Za-z_][A-Za-z0-9_-]*)\s+"
    r"from\s+registry\s+\"(?P<peer>[^\"]+)\""
    r"(?:\s+at\s+(?P<ref_domain>[A-Za-z_][A-Za-z0-9_-]*)\."
    r"(?P<ref_model>[A-Za-z_][A-Za-z0-9_-]*)\s*@\s*"
    r"(?P<version>\d+)\#(?P<signature>[0-9a-fA-F]+))?"
)
_PINNED_REFERENCE_PATTERN = re.compile(
    r"^\s*from\s+(?P<domain>[A-Za-z_][A-Za-z0-9_-]*)\."
    r"(?P<model>[A-Za-z_][A-Za-z0-9_-]*)\s*@\s*"
    r"(?P<version>\d+)\#(?P<signature>[0-9a-fA-F]+)\s+as\s+"
    r"(?P<alias>[A-Za-z_][A-Za-z0-9_-]*)"
)
_PEERS_BLOCK_PATTERN = re.compile(r"peers\s*:\s*\[(?P<body>.*?)\]", re.DOTALL)
_PEER_ID_PATTERN = re.compile(r"id\s*:\s*\"(?P<id>[^\"]+)\"")


def build_import_diagnostics(index: LspWorkspaceIndex, uri: str) -> list[Diagnostic]:
    source = index.documents.get(uri)
    if source is None:
        return []

    diagnostics: list[Diagnostic] = []
    declared_peers = _declared_peer_ids(index)
    mirror_domains = set(mirror_domain_names(index))
    mirror_signatures = _mirror_model_signatures(index)

    for line_no, line in enumerate(source.text.splitlines()):
        match = _PINNED_IMPORT_PATTERN.match(line)
        if match is None:
            match = _PINNED_REFERENCE_PATTERN.match(line)
            if match is None:
                continue

            domain_name = match.group("domain")
            model_name = match.group("model")
            version = int(match.group("version"))
            signature = match.group("signature")
            actual_signature = mirror_signatures.get((domain_name, model_name, version))
            if actual_signature is None:
                diagnostics.append(
                    Diagnostic(
                        code="FED",
                        message=(
                            f"pinned reference '{domain_name}.{model_name}@{version}#{signature}' "
                            "is not available in the local mirror cache"
                        ),
                        severity="error",
                        path=uri,
                        line=line_no + 1,
                        column=match.start("signature") + 1,
                        end_line=line_no + 1,
                        end_column=match.end("signature") + 1,
                    )
                )
                continue
            if signature.lower() != actual_signature.lower():
                diagnostics.append(
                    Diagnostic(
                        code="FED",
                        message=(
                            f"pinned reference '{domain_name}.{model_name}@{version}#{signature}' "
                            f"does not match local mirror signature '{actual_signature}'"
                        ),
                        severity="error",
                        path=uri,
                        line=line_no + 1,
                        column=match.start("signature") + 1,
                        end_line=line_no + 1,
                        end_column=match.end("signature") + 1,
                    )
                )
            continue

        domain_name = match.group("domain")
        peer_id = match.group("peer")

        if declared_peers is not None and peer_id not in declared_peers:
            diagnostics.append(
                Diagnostic(
                    code="FED",
                    message=f"import peer '{peer_id}' is not declared in workspace.mdl",
                    severity="warning",
                    path=uri,
                    line=line_no + 1,
                    column=match.start("peer") + 1,
                    end_line=line_no + 1,
                    end_column=match.end("peer") + 1,
                )
            )

        if domain_name not in mirror_domains:
            diagnostics.append(
                Diagnostic(
                    code="FED",
                    message=f"import domain '{domain_name}' is not available in the local mirror cache",
                    severity="error",
                    path=uri,
                    line=line_no + 1,
                    column=match.start("domain") + 1,
                    end_line=line_no + 1,
                    end_column=match.end("domain") + 1,
                )
            )

        ref_domain = match.group("ref_domain")
        if ref_domain is not None:
            ref_model = match.group("ref_model")
            version = int(match.group("version"))
            signature = match.group("signature")
            actual_signature = mirror_signatures.get((ref_domain, ref_model, version))
            if actual_signature is None:
                diagnostics.append(
                    Diagnostic(
                        code="FED",
                        message=(
                            f"pinned reference '{ref_domain}.{ref_model}@{version}#{signature}' "
                            "is not available in the local mirror cache"
                        ),
                        severity="error",
                        path=uri,
                        line=line_no + 1,
                        column=match.start("signature") + 1,
                        end_line=line_no + 1,
                        end_column=match.end("signature") + 1,
                    )
                )
                continue
            if signature.lower() != actual_signature.lower():
                diagnostics.append(
                    Diagnostic(
                        code="FED",
                        message=(
                            f"pinned reference '{ref_domain}.{ref_model}@{version}#{signature}' "
                            f"does not match local mirror signature '{actual_signature}'"
                        ),
                        severity="error",
                        path=uri,
                        line=line_no + 1,
                        column=match.start("signature") + 1,
                        end_line=line_no + 1,
                        end_column=match.end("signature") + 1,
                    )
                )

    return diagnostics


def mirror_domain_names(index: LspWorkspaceIndex) -> list[str]:
    names: set[str] = set()
    for source in _mirror_sources(index):
        for domain in source.domains:
            names.add(domain.name)
    return sorted(names)


def mirror_reference_names(index: LspWorkspaceIndex) -> list[tuple[str, str]]:
    names: set[tuple[str, str]] = set()
    for source in _mirror_sources(index):
        for domain in source.domains:
            for model_name in domain.models:
                names.add((domain.name, model_name))
            for projection_name in domain.projections:
                names.add((domain.name, projection_name))
    return sorted(names)


def mirror_model_versions(index: LspWorkspaceIndex) -> list[tuple[str, str, int]]:
    versions: set[tuple[str, str, int]] = set()
    for source in _mirror_sources(index):
        for domain in source.domains:
            for model_name, model_versions in domain.models.items():
                for version in model_versions:
                    versions.add((domain.name, model_name, version.version))
    return sorted(versions)


def mirror_field_names(index: LspWorkspaceIndex, domain_name: str, model_name: str, version: int) -> list[str]:
    names: set[str] = set()
    for source in _mirror_sources(index):
        for domain in source.domains:
            if domain.name != domain_name:
                continue
            versions = domain.models.get(model_name)
            if versions is None:
                continue
            for item in versions:
                if item.version != version:
                    continue
                for field in item.fields:
                    names.add(field.name)
    return sorted(names)


def _declared_peer_ids(index: LspWorkspaceIndex) -> set[str] | None:
    workspace_text = None
    for source in index.documents.values():
        if source.path is not None and source.path.name == "workspace.mdl":
            workspace_text = source.text
            break
    if workspace_text is None:
        return None

    match = _PEERS_BLOCK_PATTERN.search(workspace_text)
    if match is None:
        return set()

    return {item.group("id") for item in _PEER_ID_PATTERN.finditer(match.group("body"))}


def _mirror_sources(index: LspWorkspaceIndex):
    root = _workspace_root(index)
    if root is None:
        return []

    mirror_root = root / ".modelable" / "mirror"
    if not mirror_root.exists():
        return []

    parsed_sources = []
    for path in sorted(mirror_root.rglob("*.mdl"), key=lambda item: item.as_posix()):
        try:
            parsed_sources.append(parse_text_to_ir(path.read_text(encoding="utf-8"), path=path))
        except Exception:
            continue
    return parsed_sources


def _mirror_model_signatures(index: LspWorkspaceIndex) -> dict[tuple[str, str, int], str]:
    signatures: dict[tuple[str, str, int], str] = {}
    for source in _mirror_sources(index):
        for domain in source.domains:
            for model_name, versions in domain.models.items():
                for version in versions:
                    signatures[(domain.name, model_name, version.version)] = compute_version_signature(
                        domain.name,
                        model_name,
                        version,
                    )
    return signatures


def _workspace_root(index: LspWorkspaceIndex) -> Path | None:
    paths = [source.path for source in index.documents.values() if source.path is not None]
    if not paths:
        return None

    workspace_files = [path for path in paths if path.name == "workspace.mdl"]
    if workspace_files:
        return workspace_files[0].parent
    return paths[0].parent
