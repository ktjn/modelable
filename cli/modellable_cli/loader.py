"""Multi-document YAML loading and document-type detection."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DocType = str  # "scenario" | "domain" | "model" | "projection" | "binding" | "unknown"


def detect_doc_type(doc: dict[str, Any]) -> DocType:
    """Infer the document type from which top-level keys are present."""
    if "scenario" in doc:
        return "scenario"
    if "binding" in doc:
        return "binding"
    if "projection" in doc:
        return "projection"
    if "model" in doc:
        return "model"
    if "domain" in doc:
        return "domain"
    return "unknown"


def load_multidoc(path: str | Path) -> list[dict[str, Any]]:
    """Parse a multi-document YAML file and return a list of dicts."""
    path = Path(path)
    with open(path) as f:
        raw = f.read()
    docs = list(yaml.safe_load_all(raw))
    return [d for d in docs if d is not None]


def group_by_type(docs: list[dict[str, Any]]) -> dict[DocType, list[dict[str, Any]]]:
    """Group a flat list of parsed documents by their detected type."""
    groups: dict[DocType, list[dict[str, Any]]] = {}
    for doc in docs:
        t = detect_doc_type(doc)
        groups.setdefault(t, []).append(doc)
    return groups


def scenarios_dir() -> Path:
    """Return the path to the bundled sample scenarios directory."""
    here = Path(__file__).parent
    # When installed as a package the samples live two levels up in the repo.
    candidates = [
        here.parent.parent / "samples" / "scenarios",
        here.parent / "samples" / "scenarios",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError("Could not locate samples/scenarios directory.")


def load_scenario_index() -> list[dict[str, Any]]:
    """Return scenario metadata for every YAML file in the scenarios directory."""
    sdir = scenarios_dir()
    index = []
    for f in sorted(sdir.glob("*.yaml")):
        docs = load_multidoc(f)
        meta = next((d for d in docs if detect_doc_type(d) == "scenario"), None)
        if meta:
            meta["_file"] = str(f)
            index.append(meta)
    return index


def load_scenario_by_id(scenario_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a scenario by its `scenario` id field. Returns (metadata, all_docs)."""
    sdir = scenarios_dir()
    for f in sdir.glob("*.yaml"):
        docs = load_multidoc(f)
        meta = next((d for d in docs if detect_doc_type(d) == "scenario"), None)
        if meta and meta.get("scenario") == scenario_id:
            return meta, docs
    raise ValueError(f"No scenario with id '{scenario_id}' found in {sdir}")


def load_definitions_from_path(path: str | Path) -> list[tuple[Path, list[dict[str, Any]]]]:
    """
    Recursively load all YAML files from a path (file or directory).
    Returns a list of (file_path, [documents]) tuples.
    """
    path = Path(path)
    results = []
    if path.is_file():
        results.append((path, load_multidoc(path)))
    elif path.is_dir():
        for f in sorted(path.rglob("*.yaml")):
            results.append((f, load_multidoc(f)))
    return results
