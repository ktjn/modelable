from __future__ import annotations


def explain_validation_errors(errors: list[str]) -> str:
    if not errors:
        return "No validation errors found."
    lines = ["Validation guidance:"]
    for error in errors:
        lines.append(f"- {error}")
    return "\n".join(lines)

