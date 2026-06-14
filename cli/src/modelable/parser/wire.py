from __future__ import annotations

from modelable.parser.ir import AnnWire, WireTargetHint


def wire_targets_from_annotations(annotations) -> dict[str, WireTargetHint]:
    targets: dict[str, WireTargetHint] = {}
    for annotation in annotations:
        if isinstance(annotation, AnnWire):
            for target, hint in annotation.targets.items():
                merged = targets.get(target, WireTargetHint())
                if hint.encoding is not None:
                    if merged.encoding is not None and merged.encoding != hint.encoding:
                        raise ValueError(
                            f"conflicting wire encodings for target '{target}': "
                            f"{merged.encoding!r} vs {hint.encoding!r}"
                        )
                    merged.encoding = hint.encoding
                if hint.type is not None:
                    if merged.type is not None and merged.type != hint.type:
                        raise ValueError(
                            f"conflicting wire types for target '{target}': {merged.type!r} vs {hint.type!r}"
                        )
                    merged.type = hint.type
                if hint.case is not None:
                    if merged.case is not None and merged.case != hint.case:
                        raise ValueError(
                            f"conflicting wire cases for target '{target}': {merged.case!r} vs {hint.case!r}"
                        )
                    merged.case = hint.case
                if hint.overrides:
                    overlap = sorted(set(merged.overrides) & set(hint.overrides))
                    for key in overlap:
                        if merged.overrides[key] != hint.overrides[key]:
                            raise ValueError(
                                f"conflicting wire override for target '{target}' member '{key}': "
                                f"{merged.overrides[key]!r} vs {hint.overrides[key]!r}"
                            )
                    merged.overrides.update(hint.overrides)
                if hint.field_case is not None:
                    if merged.field_case is not None and merged.field_case != hint.field_case:
                        raise ValueError(
                            f"conflicting wire field cases for target '{target}': "
                            f"{merged.field_case!r} vs {hint.field_case!r}"
                        )
                    merged.field_case = hint.field_case
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
            overrides = ", ".join(f'{key}: "{value}"' for key, value in sorted(hint.overrides.items()))
            parts.append(f"{target}.overrides: {{ {overrides} }}")
        if hint.field_case is not None:
            parts.append(f'{target}.fieldCase: "{hint.field_case}"')
    if not parts:
        raise ValueError("AnnWire must contain at least one wire option")
    return f"@wire({', '.join(parts)})"
