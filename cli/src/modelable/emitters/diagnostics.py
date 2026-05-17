from __future__ import annotations


def emit_warning(code: str, message: str) -> str:
    return f"[{code}] {message}"


def unsupported_target(target: str) -> str:
    return emit_warning("EMIT001", f"Unsupported target: {target}")


def type_loss(field_type: str) -> str:
    return emit_warning("EMIT002", f"Type '{field_type}' cannot be represented without loss")


def missing_metadata(field: str) -> str:
    return emit_warning("EMIT003", f"Missing metadata required by target: {field}")


def validation_failed(path: str, detail: str) -> str:
    return emit_warning("EMIT004", f"Generated artifact failed validation: {path} ({detail})")


def deferred_target(target: str) -> str:
    return emit_warning("EMIT005", f"Deferred target requested in current phase: {target}")
