from __future__ import annotations

from modelable.parser.ir import AnnWire, WireTargetHint


def wire_targets_from_annotations(annotations) -> dict[str, WireTargetHint]:
    targets: dict[str, WireTargetHint] = {}
    for annotation in annotations:
        if isinstance(annotation, AnnWire):
            for target, hint in annotation.targets.items():
                merged = targets.get(target, WireTargetHint())
                if hint.encoding is not None:
                    merged.encoding = hint.encoding
                if hint.type is not None:
                    merged.type = hint.type
                if hint.case is not None:
                    merged.case = hint.case
                if hint.overrides:
                    merged.overrides.update(hint.overrides)
                targets[target] = merged
    return targets


def render_wire_annotation(annotation: AnnWire) -> str:
    parts: list[str] = []
    for target in sorted(annotation.targets):
        hint = annotation.targets[target]
        if hint.encoding is not None:
            parts.append(f'{target}: "{hint.encoding}"')
        if hint.type is not None:
            parts.append(f'{target}.type: "{hint.type}"')
        if hint.case is not None:
            parts.append(f'{target}.case: "{hint.case}"')
        if hint.overrides:
            overrides = ", ".join(
                f'{key}: "{value}"' for key, value in sorted(hint.overrides.items())
            )
            parts.append(f"{target}.overrides: {{ {overrides} }}")
    if not parts:
        raise ValueError("AnnWire must contain at least one wire option")
    return f"@wire({', '.join(parts)})"
