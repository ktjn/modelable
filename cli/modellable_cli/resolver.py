"""Model reference resolution for Modellable definitions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .loader import detect_doc_type, load_definitions_from_path

# domain.ModelName.vVersion  e.g. customer.Customer.v1
_REF_RE = re.compile(r"^([a-z][a-z0-9_-]*)\.([A-Za-z][A-Za-z0-9_]*)\.v(\d+)$")


class ModelRef:
    def __init__(self, domain: str, name: str, version: int) -> None:
        self.domain = domain
        self.name = name
        self.version = version

    def __str__(self) -> str:
        return f"{self.domain}.{self.name}.v{self.version}"

    @classmethod
    def parse(cls, ref: str) -> "ModelRef":
        m = _REF_RE.match(ref)
        if not m:
            raise ValueError(
                f"Invalid reference '{ref}'. Expected format: domain.ModelName.vN "
                f"(e.g. customer.Customer.v1)"
            )
        return cls(m.group(1), m.group(2), int(m.group(3)))


def find_doc(ref: ModelRef, search_path: str | Path = ".") -> dict[str, Any] | None:
    """Search YAML files under search_path for a document matching ref."""
    for _path, docs in load_definitions_from_path(search_path):
        for doc in docs:
            dtype = detect_doc_type(doc)
            if dtype not in ("model", "projection"):
                continue
            name_key = "model" if dtype == "model" else "projection"
            if (
                doc.get("domain") == ref.domain
                and doc.get(name_key) == ref.name
                and doc.get("version") == ref.version
            ):
                return doc
    return None
