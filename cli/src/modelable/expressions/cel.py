"""CEL subset tokenizer, parser, validator, and lineage extractor for Modelable."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

# ── Tokens ────────────────────────────────────────────────────────────────────

_TOKEN_SPEC: list[tuple[str, str]] = [
    ("STRING", r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
    ("FLOAT", r"\d+\.\d+"),
    ("INT", r"\d+"),
    ("AND", r"&&"),
    ("OR", r"\|\|"),
    ("NEQ", r"!="),
    ("LTE", r"<="),
    ("GTE", r">="),
    ("EQ", r"=="),
    ("BANG", r"!"),
    ("PLUS", r"\+"),
    ("MINUS", r"-"),
    ("STAR", r"\*"),
    ("SLASH", r"/"),
    ("PERCENT", r"%"),
    ("LT", r"<"),
    ("GT", r">"),
    ("QUESTION", r"\?"),
    ("COLON", r":"),
    ("DOT", r"\."),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("LBRACKET", r"\["),
    ("RBRACKET", r"\]"),
    ("COMMA", r","),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_]*"),
    ("WS", r"\s+"),
]

_MASTER_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in _TOKEN_SPEC)
)


@dataclass(frozen=True)
class Token:
    type: str
    value: str
    pos: int


class CelParseError(Exception):
    def __init__(self, msg: str, pos: int = -1) -> None:
        super().__init__(msg)
        self.pos = pos


def _tokenize(expr: str) -> list[Token]:
    tokens: list[Token] = []
    for m in _MASTER_RE.finditer(expr):
        kind = m.lastgroup
        assert kind is not None
        if kind == "WS":
            continue
        value = m.group()
        pos = m.start()
        if kind == "IDENT":
            if value == "true":
                kind = "TRUE"
            elif value == "false":
                kind = "FALSE"
            elif value == "null":
                kind = "NULL"
            elif value == "in":
                kind = "IN"
        tokens.append(Token(type=kind, value=value, pos=pos))
    tokens.append(Token(type="EOF", value="", pos=len(expr)))
    return tokens


# ── AST ───────────────────────────────────────────────────────────────────────


@dataclass
class Literal:
    value: str | int | float | bool | None


@dataclass
class FieldRef:
    """alias.field reference against a declared source or join."""

    alias: str
    field: str


@dataclass
class RuntimeRef:
    """request.x, auth.x, or params.x."""

    namespace: str
    name: str


@dataclass
class UnaryOp:
    op: str
    expr: "CelExpr"


@dataclass
class BinaryOp:
    op: str
    left: "CelExpr"
    right: "CelExpr"


@dataclass
class TernaryOp:
    cond: "CelExpr"
    then_: "CelExpr"
    else_: "CelExpr"


@dataclass
class FunctionCall:
    name: str
    args: list["CelExpr"] = field(default_factory=list)


@dataclass
class ListLiteral:
    items: list["CelExpr"] = field(default_factory=list)


CelExpr = Union[
    Literal, FieldRef, RuntimeRef, UnaryOp, BinaryOp, TernaryOp, FunctionCall, ListLiteral
]

# ── Parser ────────────────────────────────────────────────────────────────────

_RUNTIME_NAMESPACES = frozenset({"request", "auth", "params"})


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _consume(self, expected: str | None = None) -> Token:
        tok = self._tokens[self._pos]
        if expected and tok.type != expected:
            raise CelParseError(
                f"expected {expected} but got {tok.type!r} ({tok.value!r})",
                tok.pos,
            )
        self._pos += 1
        return tok

    def _at(self, *types: str) -> bool:
        return self._peek().type in types

    def parse(self) -> CelExpr:
        expr = self._ternary()
        if not self._at("EOF"):
            tok = self._peek()
            raise CelParseError(f"unexpected token {tok.value!r}", tok.pos)
        return expr

    def _ternary(self) -> CelExpr:
        cond = self._or()
        if self._at("QUESTION"):
            self._consume()
            then_ = self._or()
            self._consume("COLON")
            else_ = self._ternary()
            return TernaryOp(cond=cond, then_=then_, else_=else_)
        return cond

    def _or(self) -> CelExpr:
        left = self._and()
        while self._at("OR"):
            self._consume()
            right = self._and()
            left = BinaryOp(op="||", left=left, right=right)
        return left

    def _and(self) -> CelExpr:
        left = self._not()
        while self._at("AND"):
            self._consume()
            right = self._not()
            left = BinaryOp(op="&&", left=left, right=right)
        return left

    def _not(self) -> CelExpr:
        if self._at("BANG"):
            self._consume()
            return UnaryOp(op="!", expr=self._not())
        return self._comparison()

    def _comparison(self) -> CelExpr:
        left = self._add()
        if self._at("EQ", "NEQ", "LT", "LTE", "GT", "GTE", "IN"):
            op = self._consume().value
            right = self._add()
            return BinaryOp(op=op, left=left, right=right)
        return left

    def _add(self) -> CelExpr:
        left = self._mul()
        while self._at("PLUS", "MINUS"):
            op = self._consume().value
            right = self._mul()
            left = BinaryOp(op=op, left=left, right=right)
        return left

    def _mul(self) -> CelExpr:
        left = self._unary()
        while self._at("STAR", "SLASH", "PERCENT"):
            op = self._consume().value
            right = self._unary()
            left = BinaryOp(op=op, left=left, right=right)
        return left

    def _unary(self) -> CelExpr:
        if self._at("MINUS"):
            self._consume()
            return UnaryOp(op="-", expr=self._unary())
        return self._primary()

    def _primary(self) -> CelExpr:
        tok = self._peek()

        if tok.type == "LPAREN":
            self._consume()
            expr = self._ternary()
            self._consume("RPAREN")
            return expr

        if tok.type == "LBRACKET":
            return self._list()

        if tok.type == "TRUE":
            self._consume()
            return Literal(value=True)

        if tok.type == "FALSE":
            self._consume()
            return Literal(value=False)

        if tok.type == "NULL":
            self._consume()
            return Literal(value=None)

        if tok.type == "STRING":
            self._consume()
            raw = tok.value[1:-1]
            unescaped = raw.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            return Literal(value=unescaped)

        if tok.type == "FLOAT":
            self._consume()
            return Literal(value=float(tok.value))

        if tok.type == "INT":
            self._consume()
            return Literal(value=int(tok.value))

        if tok.type == "IDENT":
            return self._ident_or_call()

        raise CelParseError(f"unexpected token {tok.value!r}", tok.pos)

    def _ident_or_call(self) -> CelExpr:
        name_tok = self._consume("IDENT")
        name = name_tok.value

        if self._at("LPAREN"):
            self._consume()
            args: list[CelExpr] = []
            while not self._at("RPAREN", "EOF"):
                args.append(self._ternary())
                if self._at("COMMA"):
                    self._consume()
            self._consume("RPAREN")
            return FunctionCall(name=name, args=args)

        if self._at("DOT"):
            self._consume()
            field_tok = self._consume("IDENT")
            field_name = field_tok.value
            if name in _RUNTIME_NAMESPACES:
                return RuntimeRef(namespace=name, name=field_name)
            return FieldRef(alias=name, field=field_name)

        # Bare identifier — not valid in MVP CEL (alias.field required)
        return FieldRef(alias="", field=name)

    def _list(self) -> ListLiteral:
        self._consume("LBRACKET")
        items: list[CelExpr] = []
        while not self._at("RBRACKET", "EOF"):
            items.append(self._ternary())
            if self._at("COMMA"):
                self._consume()
        self._consume("RBRACKET")
        return ListLiteral(items=items)


def parse_cel(expression: str) -> tuple[CelExpr | None, list[str]]:
    """Parse a CEL expression string. Returns (ast, parse_errors)."""
    try:
        tokens = _tokenize(expression)
        return _Parser(tokens).parse(), []
    except CelParseError as exc:
        return None, [f"CEL001: parse error: {exc}"]


# ── Validation ────────────────────────────────────────────────────────────────

_SCALAR_FUNCTIONS = frozenset(
    {
        "lower",
        "upper",
        "trim",
        "contains",
        "startsWith",
        "endsWith",
        "date",
        "daysBetween",
        "coalesce",
        "toString",
        "toDecimal",
        "hashHmacSha256",
    }
)

_AGGREGATE_FUNCTIONS = frozenset({"count", "sum", "min", "max", "avg"})

_NON_DETERMINISTIC_FUNCTIONS = frozenset({"now", "random", "uuid", "currentUser"})


@dataclass
class CelContext:
    """Validation context built from a projection version's sources."""

    source_fields: dict[str, set[str]]
    has_group_by: bool
    fqn: str


@dataclass
class CelValidationResult:
    errors: list[str]
    field_refs: list[tuple[str, str]]


def validate_cel_expr(expr: CelExpr, context: CelContext) -> CelValidationResult:
    """Validate a parsed CEL expression against a projection context."""
    errors: list[str] = []
    refs: list[tuple[str, str]] = []
    _walk(expr, context, errors, refs)
    return CelValidationResult(errors=errors, field_refs=refs)


def _walk(
    expr: CelExpr,
    ctx: CelContext,
    errors: list[str],
    refs: list[tuple[str, str]],
) -> None:
    if isinstance(expr, Literal):
        return

    if isinstance(expr, FieldRef):
        if expr.alias == "":
            errors.append(
                f"CEL002: {ctx.fqn}: bare identifier '{expr.field}' is not allowed — "
                "use alias.field notation"
            )
            return
        if expr.alias not in ctx.source_fields:
            errors.append(f"CEL002: {ctx.fqn}: unknown alias '{expr.alias}'")
            return
        if expr.field not in ctx.source_fields[expr.alias]:
            errors.append(f"CEL002: {ctx.fqn}: unknown field '{expr.alias}.{expr.field}'")
            return
        refs.append((expr.alias, expr.field))
        return

    if isinstance(expr, RuntimeRef):
        # Phase 1: accept all request/auth/params references without declaration check
        return

    if isinstance(expr, UnaryOp):
        _walk(expr.expr, ctx, errors, refs)
        return

    if isinstance(expr, BinaryOp):
        _walk(expr.left, ctx, errors, refs)
        _walk(expr.right, ctx, errors, refs)
        return

    if isinstance(expr, TernaryOp):
        _walk(expr.cond, ctx, errors, refs)
        _walk(expr.then_, ctx, errors, refs)
        _walk(expr.else_, ctx, errors, refs)
        return

    if isinstance(expr, FunctionCall):
        name = expr.name
        if name in _NON_DETERMINISTIC_FUNCTIONS:
            errors.append(
                f"CEL007: {ctx.fqn}: non-deterministic function '{name}' is not allowed"
            )
        elif name not in _SCALAR_FUNCTIONS and name not in _AGGREGATE_FUNCTIONS:
            errors.append(f"CEL005: {ctx.fqn}: unsupported function '{name}'")
        if name in _AGGREGATE_FUNCTIONS and not ctx.has_group_by:
            errors.append(
                f"CEL006: {ctx.fqn}: aggregate function '{name}' used in projection without group by"
            )
        for arg in expr.args:
            _walk(arg, ctx, errors, refs)
        return

    if isinstance(expr, ListLiteral):
        for item in expr.items:
            _walk(item, ctx, errors, refs)
        return


# ── Lineage extraction ────────────────────────────────────────────────────────


def extract_field_refs(expr: CelExpr) -> list[tuple[str, str]]:
    """Collect all (alias, field_name) pairs referenced in a CEL expression."""
    refs: list[tuple[str, str]] = []
    _collect_refs(expr, refs)
    return refs


def _collect_refs(expr: CelExpr, refs: list[tuple[str, str]]) -> None:
    if isinstance(expr, FieldRef) and expr.alias:
        refs.append((expr.alias, expr.field))
    elif isinstance(expr, BinaryOp):
        _collect_refs(expr.left, refs)
        _collect_refs(expr.right, refs)
    elif isinstance(expr, UnaryOp):
        _collect_refs(expr.expr, refs)
    elif isinstance(expr, TernaryOp):
        _collect_refs(expr.cond, refs)
        _collect_refs(expr.then_, refs)
        _collect_refs(expr.else_, refs)
    elif isinstance(expr, FunctionCall):
        for arg in expr.args:
            _collect_refs(arg, refs)
    elif isinstance(expr, ListLiteral):
        for item in expr.items:
            _collect_refs(item, refs)
