from __future__ import annotations

from dataclasses import dataclass

from modelable.parser.ir import (
    ArrayType,
    DecimalType,
    EnumType,
    FieldType,
    MapType,
    NamedType,
    ObjectType,
    PrimitiveType,
    RefType,
)

_PRIMITIVE_NAMES = {
    "string",
    "int",
    "float",
    "bool",
    "date",
    "time",
    "timestamp",
    "uuid",
    "duration",
    "binary",
}


@dataclass(frozen=True)
class TypeShapeField:
    name: str
    shape: "TypeShape"
    optional: bool = False


@dataclass(frozen=True)
class TypeShape:
    kind: str
    optional: bool = False
    nullable: bool = False
    element: "TypeShape | None" = None
    key: "TypeShape | None" = None
    value: "TypeShape | None" = None
    ref: str | None = None
    enum_values: tuple[str, ...] = ()
    fields: tuple[TypeShapeField, ...] = ()
    precision: int | None = None
    scale: int | None = None

    @classmethod
    def from_field(cls, value: str | FieldType, *, optional: bool = False) -> TypeShape:
        if isinstance(value, str):
            return _parse_type_text(value, optional=optional)
        return cls.from_field_type(value, optional=optional)

    @classmethod
    def from_field_type(cls, field_type: FieldType, *, optional: bool = False) -> TypeShape:
        if isinstance(field_type, PrimitiveType):
            return cls(kind="primitive", optional=optional, ref=field_type.kind)
        if isinstance(field_type, DecimalType):
            return cls(
                kind="decimal",
                optional=optional,
                precision=field_type.precision,
                scale=field_type.scale,
            )
        if isinstance(field_type, ArrayType):
            return cls(kind="array", optional=optional, element=cls.from_field_type(field_type.item))
        if isinstance(field_type, MapType):
            return cls(
                kind="map",
                optional=optional,
                key=cls.from_field_type(field_type.key),
                value=cls.from_field_type(field_type.value),
            )
        if isinstance(field_type, RefType):
            return cls(kind="ref", optional=optional, ref=field_type.target)
        if isinstance(field_type, EnumType):
            return cls(kind="enum", optional=optional, enum_values=tuple(field_type.values))
        if isinstance(field_type, ObjectType):
            return cls(
                kind="object",
                optional=optional,
                fields=tuple(
                    TypeShapeField(
                        name=field.name,
                        shape=cls.from_field_type(field.type, optional=field.optional),
                        optional=field.optional,
                    )
                    for field in field_type.fields
                ),
            )
        if isinstance(field_type, NamedType):
            return cls(kind="named", optional=optional, ref=field_type.name)
        raise TypeError(f"unsupported field type: {type(field_type)!r}")

    def describe(self) -> str:
        text = self._describe_base()
        if self.nullable:
            text += "?"
        return text

    def _describe_base(self) -> str:
        if self.kind == "primitive":
            return self.ref or "primitive"
        if self.kind == "decimal":
            if self.precision is None or self.scale is None:
                return "decimal(p, s)"
            return f"decimal({self.precision}, {self.scale})"
        if self.kind == "array":
            inner = self.element.describe() if self.element is not None else "?"
            return f"array<{inner}>"
        if self.kind == "map":
            key = self.key.describe() if self.key is not None else "?"
            value = self.value.describe() if self.value is not None else "?"
            return f"map<{key}, {value}>"
        if self.kind == "ref":
            return f"ref<{self.ref or '?'}>"
        if self.kind == "enum":
            values = ", ".join(self.enum_values) if self.enum_values else "..."
            return f"enum({values})"
        if self.kind == "object":
            if not self.fields:
                return "object { ... }"
            rendered = ", ".join(
                f"{field.name}{'?' if field.optional else ''}: {field.shape.describe()}"
                for field in self.fields
            )
            return f"object {{ {rendered} }}"
        if self.kind == "named":
            return self.ref or "named"
        return self.kind


def type_shape_catalog() -> list[tuple[str, TypeShape, str]]:
    return [
        ("primitive string", TypeShape(kind="primitive", ref="string"), "scalar"),
        ("primitive bool", TypeShape(kind="primitive", ref="bool"), "scalar"),
        ("decimal(p, s)", TypeShape(kind="decimal"), "precision and scale preserved separately"),
        ("array<uuid>", TypeShape.from_field("array<uuid>"), "recursive element shape"),
        (
            "map<string, int>",
            TypeShape.from_field("map<string, int>"),
            "key and value shapes are normalized recursively",
        ),
        ("ref<Customer>", TypeShape(kind="ref", ref="Customer"), "reference target"),
        ("enum(active, blocked)", TypeShape(kind="enum", enum_values=("active", "blocked")), "closed value set"),
        (
            "object { ... }",
            TypeShape(
                kind="object",
                fields=(
                    TypeShapeField(
                        name="id",
                        shape=TypeShape(kind="primitive", ref="uuid"),
                    ),
                ),
            ),
            "named member shapes remain recursive",
        ),
        ("named Customer", TypeShape(kind="named", ref="Customer"), "named value object"),
    ]


def _parse_type_text(text: str, *, optional: bool = False) -> TypeShape:
    stripped = text.strip()
    nullable = False
    if stripped.endswith("?"):
        nullable = True
        stripped = stripped[:-1].rstrip()

    if stripped.startswith("array<") and stripped.endswith(">"):
        inner = stripped[len("array<") : -1]
        return TypeShape(
            kind="array",
            optional=optional,
            nullable=nullable,
            element=_parse_type_text(inner),
        )
    if stripped.startswith("map<") and stripped.endswith(">"):
        inner = stripped[len("map<") : -1]
        key_text, value_text = _split_top_level(inner, ",")
        return TypeShape(
            kind="map",
            optional=optional,
            nullable=nullable,
            key=_parse_type_text(key_text),
            value=_parse_type_text(value_text),
        )
    if stripped.startswith("ref<") and stripped.endswith(">"):
        inner = stripped[len("ref<") : -1].strip()
        return TypeShape(kind="ref", optional=optional, nullable=nullable, ref=inner)
    if stripped.startswith("enum(") and stripped.endswith(")"):
        inner = stripped[len("enum(") : -1]
        values = tuple(_split_items(inner))
        return TypeShape(kind="enum", optional=optional, nullable=nullable, enum_values=values)
    if stripped.startswith("object {") and stripped.endswith("}"):
        return TypeShape(kind="object", optional=optional, nullable=nullable)
    if stripped.startswith("decimal(") and stripped.endswith(")"):
        inner = stripped[len("decimal(") : -1]
        first, second = _split_top_level(inner, ",")
        try:
            precision = int(first.strip())
            scale = int(second.strip())
        except ValueError:
            precision = None
            scale = None
        return TypeShape(
            kind="decimal",
            optional=optional,
            nullable=nullable,
            precision=precision,
            scale=scale,
        )
    if stripped in _PRIMITIVE_NAMES:
        return TypeShape(kind="primitive", optional=optional, nullable=nullable, ref=stripped)
    return TypeShape(kind="named", optional=optional, nullable=nullable, ref=stripped)


def _split_top_level(text: str, separator: str) -> tuple[str, str]:
    depth = 0
    current = []
    parts: list[str] = []
    for char in text:
        if char in "<({[":
            depth += 1
        elif char in ">)}]":
            depth = max(depth - 1, 0)
        elif char == separator and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    if len(parts) != 2:
        raise ValueError(f"expected two parts separated by {separator!r}: {text!r}")
    return parts[0], parts[1]


def _split_items(text: str) -> list[str]:
    depth = 0
    current = []
    items: list[str] = []
    for char in text:
        if char in "<({[":
            depth += 1
        elif char in ">)}]":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items
