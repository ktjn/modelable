"""Deterministic local ``modelable.package/v1`` artifacts."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from modelable.package_manifest import (
    _EXPORT_WILDCARD,
    load_package_manifest,
    normalize_package_manifest,
    parse_package_manifest,
)
from modelable.registry.snapshot import verify_snapshot

PACKAGE_ARTIFACT_SCHEMA = "modelable.package/v1"


def pack_package_artifact(manifest_path: Path, snapshot_dir: Path, output_path: Path) -> str:
    """Pack one verified package from a local registry snapshot."""
    errors = verify_snapshot(snapshot_dir)
    if errors:
        raise ValueError("cannot pack an invalid registry snapshot:\n" + "\n".join(errors))
    manifest = load_package_manifest(manifest_path)
    normalized = normalize_package_manifest(manifest)
    lock = _read_json(Path(snapshot_dir) / "registry.lock")
    package = _find_package(lock, normalized)
    package_objects = package.get("objects")
    if not isinstance(package_objects, list) or not all(isinstance(item, str) for item in package_objects):
        raise ValueError("package lock entry has invalid objects")
    lock_objects = {
        str(item["identity"]): item
        for item in lock.get("objects", [])
        if isinstance(item, dict) and isinstance(item.get("identity"), str)
    }
    object_payloads: dict[str, dict[str, Any]] = {}
    for identity in package_objects:
        entry = lock_objects.get(identity)
        if entry is None or not isinstance(entry.get("content_hash"), str):
            raise ValueError(f"package lock entry references missing object {identity}")
        object_path = Path(snapshot_dir) / "registry" / "objects" / f"{entry['content_hash']}.json"
        payload = _read_json(object_path)
        if not isinstance(payload, dict) or payload.get("identity") != identity:
            raise ValueError(f"package object identity mismatch for {identity}")
        object_payloads[identity] = payload

    document = {
        "$schema": PACKAGE_ARTIFACT_SCHEMA,
        "package": normalized,
        "objects": [
            {
                "identity": identity,
                "signature": object_payloads[identity].get("signature"),
                "content_hash": lock_objects[identity]["content_hash"],
            }
            for identity in sorted(package_objects)
        ],
        "content_hash": package.get("content_hash"),
    }
    metadata = {
        "format": PACKAGE_ARTIFACT_SCHEMA,
        "content_hash": document["content_hash"],
        "object_count": len(package_objects),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_archive(output_path, document, metadata, object_payloads)
    return _file_hash(output_path)


def verify_package_artifact(path: Path) -> dict[str, Any]:
    """Verify and return a local package artifact's canonical manifest."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = archive.namelist()
            _validate_archive_names(names)
            if "manifest.json" not in names or "package-metadata.json" not in names:
                raise ValueError("package artifact is missing required metadata")
            document = _read_archive_json(archive, "manifest.json")
            metadata = _read_archive_json(archive, "package-metadata.json")
            if document.get("$schema") != PACKAGE_ARTIFACT_SCHEMA:
                raise ValueError("unsupported package artifact schema")
            if metadata.get("format") != PACKAGE_ARTIFACT_SCHEMA:
                raise ValueError("invalid package artifact metadata")
            package_manifest = document.get("package")
            if not isinstance(package_manifest, dict):
                raise ValueError("package artifact manifest must be an object")
            parse_package_manifest(package_manifest)
            objects = document.get("objects")
            if not isinstance(objects, list) or not all(isinstance(item, dict) for item in objects):
                raise ValueError("package artifact objects must be an array")
            object_records = _validate_object_records(objects)
            object_names = {f"objects/{identity}.json" for identity in object_records}
            if set(names) != {"manifest.json", "package-metadata.json"} | object_names:
                raise ValueError("package artifact contains unexpected files")
            for identity, record in object_records.items():
                payload = _read_archive_json(archive, f"objects/{identity}.json")
                if payload.get("identity") != identity:
                    raise ValueError(f"package artifact object identity mismatch for {identity}")
                content_hash = record.get("content_hash")
                actual_hash = _content_hash({key: value for key, value in payload.items() if key != "content_hash"})
                if payload.get("content_hash") != content_hash or actual_hash != content_hash:
                    raise ValueError(f"package artifact object hash mismatch for {identity}")
                if payload.get("signature") != record.get("signature"):
                    raise ValueError(f"package artifact object signature mismatch for {identity}")
            expected_hash = _content_hash(
                {
                    "manifest": package_manifest,
                    "objects": [
                        {"identity": identity, "signature": object_records[identity].get("signature")}
                        for identity in sorted(object_records)
                    ],
                }
            )
            if document.get("content_hash") != expected_hash or metadata.get("content_hash") != expected_hash:
                raise ValueError("package artifact content hash mismatch")
            _validate_exports(package_manifest, object_records)
            if metadata.get("object_count") != len(object_records):
                raise ValueError("package artifact object count mismatch")
            return document
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("invalid package artifact"):
            raise
        raise ValueError(f"invalid package artifact: {exc}") from exc


def unpack_package_artifact(path: Path, output_dir: Path) -> None:
    """Verify and unpack a package artifact into a fresh directory."""
    document = verify_package_artifact(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()
    with zipfile.ZipFile(path, "r") as archive:
        names = [
            "manifest.json",
            "package-metadata.json",
            *sorted(name for name in archive.namelist() if name.startswith("objects/")),
        ]
        for name in names:
            destination = output_dir / name
            resolved_destination = destination.resolve()
            if root not in resolved_destination.parents:
                raise ValueError(f"unpack destination escapes output directory for {name}")
            if destination.exists():
                raise ValueError(f"unpack destination already contains {name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    if _read_json(output_dir / "manifest.json") != document:
        raise ValueError("unpacked package manifest does not match artifact")


def _find_package(lock: Mapping[str, Any], manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    packages = lock.get("packages")
    if not isinstance(packages, list):
        raise ValueError("registry lock does not contain package metadata")
    for package in packages:
        if isinstance(package, dict) and package.get("manifest") == manifest:
            return package
    raise ValueError("package manifest is not present in the registry lock")


def _validate_exports(manifest: Mapping[str, Any], objects: Mapping[str, Mapping[str, Any]]) -> None:
    exports = manifest.get("exports")
    declarations = exports.get("declarations") if isinstance(exports, dict) else None
    if not isinstance(declarations, list):
        raise ValueError("package artifact exports are invalid")
    for export in declarations:
        if not isinstance(export, str):
            raise ValueError("package artifact export is not a string")
        if _EXPORT_WILDCARD.fullmatch(export):
            if not any(identity.startswith(f"{export[:-2]}.") for identity in objects):
                raise ValueError(f"package artifact wildcard export {export!r} has no objects")
        elif export not in objects:
            raise ValueError(f"package artifact export {export!r} has no object")


def _validate_object_records(objects: list[object]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in objects:
        if not isinstance(record, dict):
            raise ValueError("package artifact object record must be an object")
        identity = record.get("identity")
        if not isinstance(identity, str) or identity in result:
            raise ValueError("package artifact contains duplicate or invalid object identity")
        if not isinstance(record.get("signature"), str) or not isinstance(record.get("content_hash"), str):
            raise ValueError(f"package artifact object record is incomplete for {identity}")
        result[identity] = record
    return result


def _write_archive(
    path: Path, document: Mapping[str, Any], metadata: Mapping[str, Any], objects: Mapping[str, Mapping[str, Any]]
) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        _write_archive_entry(archive, "manifest.json", _serialize_json(document))
        _write_archive_entry(archive, "package-metadata.json", _serialize_json(metadata))
        for identity in sorted(objects):
            _write_archive_entry(archive, f"objects/{identity}.json", _serialize_json(objects[identity]))


def _write_archive_entry(archive: zipfile.ZipFile, name: str, content: str) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    archive.writestr(info, content.encode("utf-8"))


def _validate_archive_names(names: list[str]) -> None:
    if len(names) != len(set(names)):
        raise ValueError("package artifact contains duplicate files")
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"package artifact contains unsafe path {name!r}")


def _read_archive_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    payload = archive.read(name).decode("utf-8")
    document = json.loads(payload)
    if not isinstance(document, dict) or payload != _serialize_json(document):
        raise ValueError(f"package artifact JSON is not canonical: {name}")
    return document


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _serialize_json(document: object) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _content_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
