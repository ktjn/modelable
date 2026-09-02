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


def enum_member_collision(target: str, owner: str, identifier: str, members: list[str]) -> str:
    quoted = ", ".join(f"'{member}'" for member in members)
    return emit_warning(
        "EMIT006",
        f"{target} enum '{owner}' member collision: {quoted} all generate identifier '{identifier}'",
    )


def storage_bound_field_case_default(target: str, owner: str, fields: list[str]) -> str:
    quoted = ", ".join(f"'{field}'" for field in fields)
    return emit_warning(
        "EMIT007",
        f"{target} struct '{owner}' is bound to a storage adapter but has no explicit "
        f"@wire(json.fieldCase: ...) override: field(s) {quoted} default to their declared "
        "IDL casing on the wire, which will not match a differently-cased physical column "
        'name; add @wire(json.fieldCase: "snake_case") to the projection (or source model) '
        "if the physical schema uses snake_case columns",
    )
