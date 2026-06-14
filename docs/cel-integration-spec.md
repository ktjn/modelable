# CEL Integration Specification

> **Status:** Approved for Phase 1 compiler validation.
>
> **Scope:** How the Common Expression Language (CEL) is embedded in `.mdl` projections, parsed, type-checked, and used for lineage extraction.

## 1. Purpose

CEL is the expression language for computed projection fields, filters, join predicates, aggregation guards, and runtime parameter expressions. Modelable uses CEL because it is deterministic, side-effect free, sandboxable, and expressive enough for data-contract derivation without becoming a general programming language.

The compiler owns expression validation. Runtime adapters must not accept unvalidated CEL from source files.

## 2. Expression Locations

CEL may appear in these `.mdl` locations:

| Location | Example | Phase |
|---|---|---|
| Computed projection field | `isBillable = c.status == "active"` | 1 |
| Join predicate | `join customer.Customer @ 2 as c on o.customerId == c.customerId` | 1 syntax, Phase 5 execution |
| Filter block or filter option | `filter: c.status != "deleted"` | 1 syntax, Phase 5 execution |
| Aggregation expression argument | `sum(o.totalAmount)` | 1 syntax, Phase 5 execution |
| Runtime parameter expression | `request.sellerId == product.sellerId` | Phase 5 |

Phase 1 must parse, type-check, and extract lineage from expressions even when execution is deferred.

## 3. Supported MVP Subset

The Phase 1 compiler supports:

- Literals: strings, integers, decimals/floats, booleans, and `null`.
- Field references: qualified `alias.fieldName` references only.
- Runtime references in deferred contexts: `request.<name>`, `auth.<name>`, and `params.<name>`.
- Operators: `+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `<=`, `>`, `>=`, `&&`, `||`, `!`, and ternary `condition ? a : b`.
- Parentheses for grouping.
- List membership: `value in ["a", "b"]`.
- Closed aggregate functions: `count`, `sum`, `min`, `max`, `avg`.
- Closed scalar functions listed in section 4.

Bare field names are not allowed in projections. Requiring `alias.fieldName` keeps lineage deterministic when projections add joins later.

## 4. Function Catalog

Phase 1 scalar functions:

| Function | Signature | Notes |
|---|---|---|
| `lower` | `string -> string` | Locale-insensitive Unicode lowercase |
| `upper` | `string -> string` | Locale-insensitive Unicode uppercase |
| `trim` | `string -> string` | Removes leading and trailing whitespace |
| `contains` | `string, string -> bool` | Substring check |
| `slice` | `string, int, int -> string` | Extracts characters from start index (inclusive) to end index (exclusive); negative indices count from the end |
| `startsWith` | `string, string -> bool` | Prefix check |
| `endsWith` | `string, string -> bool` | Suffix check |
| `date` | `timestamp -> date` | UTC date extraction |
| `daysBetween` | `date, date -> int` | Signed day difference |
| `coalesce` | `T?, T -> T` | Returns fallback when first argument is null |
| `toString` | `T -> string` | Allowed for scalar types |
| `toDecimal` | `int|string -> decimal` | String input must be decimal formatted |
| `hashHmacSha256` | `string, string -> string` | For pseudonymisation examples; key argument must be a binding or parameter reference, not a literal secret |

Deferred functions:

- Custom CEL macros.
- User-defined functions.
- Non-deterministic functions such as `now()`, random values, network calls, or filesystem access.

## 5. Type Checking

The semantic validator builds a CEL environment from the projection sources:

```text
alias.fieldName -> Modelable field type
request.*       -> runtime parameter type, if declared by the binding or projection
auth.*          -> runtime principal context, if declared by the binding
params.*        -> explicit runtime parameter declarations
```

Validation rules:

- Every `alias.fieldName` must resolve to a declared source field.
- Operators must receive compatible types.
- Comparisons must compare compatible scalar types.
- Logical operators require booleans.
- Arithmetic is allowed only for numeric types.
- String functions require string inputs.
- Aggregate functions may only appear in projections with `group by`.
- Nullable values must be guarded with `coalesce`, explicit null checks, or accepted by a function that supports nullable input.
- Computed projection fields must have an inferred output type that can be emitted to JSON Schema.

The compiler records the inferred output type in the normalized model graph.

## 6. Lineage Extraction

Lineage extraction is syntactic over the parsed CEL expression tree. The compiler records every source field reference used by the expression.

Example:

```mdl
riskTier = c.status == "active" && p.failedPayments30d > 2 ? "review" : "standard"
```

Lineage:

```text
target riskTier
  <- customer.Customer@2.status
  <- payments.PaymentStats@1.failedPayments30d
```

Function calls do not hide lineage. For example, `hashHmacSha256(c.email, params.hashKey)` records `c.email` as a source field and records `params.hashKey` as a runtime parameter dependency.

## 7. Diagnostics

CEL validation errors are normal definition errors and must fail `modelable validate`.

Diagnostic codes:

| Code | Meaning |
|---|---|
| `CEL001` | Parse error |
| `CEL002` | Unknown alias or field |
| `CEL003` | Type mismatch |
| `CEL004` | Nullable value used without guard |
| `CEL005` | Unsupported function |
| `CEL006` | Aggregate function used outside grouped projection |
| `CEL007` | Non-deterministic or side-effecting expression |
| `CEL008` | Runtime parameter used without declaration |

Diagnostics must include file path, line, column, expression text, and a short remediation hint.

## 8. Open Decisions

- Whether to support CEL's `has()` macro for optional field checks.
- Whether runtime parameter declarations live in projections, bindings, or both.
- Whether the compiler should expose a debug command that prints the parsed CEL AST.

## 9. Acceptance Criteria

- Computed fields with valid CEL expressions pass validation.
- Invalid aliases, fields, functions, and type combinations fail validation with deterministic diagnostic codes.
- The compiler extracts all source field references from computed fields, filters, joins, and aggregate arguments.
- Generated JSON Schema includes computed fields with inferred types and `x-modelable-lineage`.
- Expressions with non-deterministic behavior are rejected.

## 10. Dependencies

- `idl-design-spec.md` — projection operators and type system
- `idl-design-spec.md` — parser, IR, and semantic validation requirements
- `modelable-system-spec.md` — lineage and governance requirements
