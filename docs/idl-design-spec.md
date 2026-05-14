# Design: Modellable IDL

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** New `.mdl` IDL language — syntax, type system, projections, output targets, toolchain

---

## Context

Modellable needs a format for defining domain-owned canonical models, projections with explicit lineage, and output target declarations. Three options were evaluated:

- **Option A — Custom YAML DSL:** Full control, already partially specced, but verbose for complex projections and every emitter must be written from scratch.
- **Option B — Extend TypeSpec:** Gets OpenAPI/Protobuf emitters for free, but TypeSpec's API-centric model fights the projection/lineage/domain-ownership concepts that are Modellable's core.
- **Option C — Custom text IDL (chosen):** Purpose-built grammar for Modellable's concepts. More expressive than YAML for derivation logic, LLM-friendly due to explicit delimiters and consistent structure, enables a language server.

Primary authoring personas are application developers and data/platform engineers. The CLI (including LLM integration) is the primary interaction path — developers use `modellable generate` and `modellable transform` to create and evolve files, then review the output.

---

## 1. Syntax Style and File Structure

### 1.1 File extension

`.mdl`

### 1.2 Overall style

- Brace-delimited blocks — no significant whitespace, unambiguous for LLM generation
- `@decorator` annotations for governance metadata
- `@` to pin a version on a definition (`Customer @ 2`)
- `(additive)` / `(breaking)` inline after the version number
- `?` suffix for optional fields
- No trailing semicolons

```mdl
domain customer {
  owner: "customer-platform"
  description: "Customer identity and lifecycle data."

  model Customer @ 2 (additive) {
    @key       customerId: uuid
               legalName:  string
    @pii       email?:     string
               status:     enum(active, blocked, deleted)
               createdAt:  timestamp
  }
}
```

### 1.3 File layout convention

One domain per file. The compiler merges across files within a workspace.

```
models/
  customer/
    Customer.mdl
    Address.mdl
  billing/
    Invoice.mdl
    projections/
      BillingCustomer.mdl
```

---

## 2. Fields and Type System

### 2.1 Built-in types

| Type | Notes |
|---|---|
| `string` | UTF-8 string |
| `int` | 64-bit integer |
| `float` | 64-bit float |
| `bool` | Boolean |
| `uuid` | UUID v4 |
| `timestamp` | UTC datetime with microsecond precision |
| `date` | Calendar date (no time) |
| `time` | Time of day (no date) |
| `duration` | ISO 8601 duration |
| `decimal(p,s)` | Arbitrary-precision decimal |
| `binary` | Raw bytes |
| `array<T>` | Ordered list |
| `map<K,V>` | Key-value map |
| `ref<Domain.Model>` | Cross-domain reference |
| `enum(a, b, c)` | Inline enumeration |

The type system is platform-neutral. Target emitters map each type to the closest equivalent in the output format (e.g., `uuid` → `string` format `uuid` in JSON Schema, `UUID` in Avro, `uuid` in Postgres DDL).

### 2.2 Field declaration syntax

```mdl
@annotation  fieldName:  Type
@annotation  optional?:  Type
```

### 2.3 Available annotations

| Annotation | Meaning |
|---|---|
| `@key` | Identity field (required for `entity` and `aggregate`) |
| `@pii` | Contains personally identifiable information |
| `@classification("level")` | Governance classification (restricted, internal, public) |
| `@deprecated(replacedBy: "field")` | Field is deprecated |
| `@owner("team")` | Field-level ownership override |

### 2.4 Model kinds

| Keyword | Rules |
|---|---|
| `entity` | Requires `@key`; has independent lifecycle |
| `aggregate` | Requires `@key`; owns a consistency boundary |
| `event` | No `@key` required; immutable fact |
| `value` | No `@key`; embedded in other models |

### 2.5 Versioning

Each version is a full independent declaration. The compiler diffs consecutive versions and enforces `changeKind`.

```mdl
model Customer @ 1 (additive) {
  @key  customerId: uuid
        legalName:  string
        createdAt:  timestamp
}

model Customer @ 2 (additive) {
  @key  customerId: uuid
        legalName:  string
  @pii  email?:     string
        status:     enum(active, blocked, deleted)
        createdAt:  timestamp
}
```

`(additive)` — only backward-compatible changes (new optional fields, deprecation marks, documentation). Existing projections remain valid.

`(breaking)` — at least one incompatible change (field removed, renamed, type changed, required field added). All projections referencing this model must be re-validated.

---

## 3. Projections, Lineage, and Derivation

### 3.1 Lineage operators

| Syntax | Meaning |
|---|---|
| `target <- source.field` | Direct mapping — lineage is unambiguous |
| `target = expression` | Computed field — compiler extracts referenced source fields from the CEL expression |

Every field in a projection carries an explicit back-reference to its origin. No field can exist in a projection without a `<-` or `=`.

### 3.2 Simple projection (subset)

```mdl
domain billing {

  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
  {
    billingCustomerId <- c.customerId
    name             <- c.legalName
    @pii invoiceEmail <- c.email
    isBillable        = c.status == "active"
  }
}
```

### 3.3 Multi-source join

```mdl
projection OrderWithCustomer @ 1
  from orders.Order @ 3 as o
  join customer.Customer @ 2 as c on o.customerId == c.customerId
{
  orderId      <- o.orderId
  customerName <- c.legalName
  @pii email   <- c.email
  total        <- o.totalAmount
  isHighValue   = o.totalAmount > 1000.00
}
```

### 3.4 Aggregation

```mdl
projection CustomerOrderStats @ 1
  from orders.Order @ 3 as o
  group by o.customerId
{
  customerId  <- o.customerId
  orderCount   = count(o.orderId)
  totalSpent   = sum(o.totalAmount)
  lastOrderAt  = max(o.createdAt)
}
```

Aggregation functions (`count`, `sum`, `min`, `max`, `avg`) are a closed set — not arbitrary expressions — so lineage remains fully traceable.

### 3.5 Version ranges

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ >=2 <3 as c
{
  ...
}
```

Resolved to the highest published version satisfying the constraint at compile time. If that version carries `changeKind: breaking`, the compiler raises an error until the projection is updated.

### 3.6 Lineage record (compiler output per field)

| Field | Kind | Source fields |
|---|---|---|
| `billingCustomerId` | direct | `customer.Customer@2.customerId` |
| `invoiceEmail` | direct | `customer.Customer@2.email` |
| `isBillable` | computed | `customer.Customer@2.status` |
| `totalSpent` | aggregation | `orders.Order@3.totalAmount` |

---

## 4. Output Targets

### 4.1 Workspace-level generate block

```mdl
workspace {
  generate {
    openapi       -> ./generated/api/
    typescript    -> ./generated/types/
    avro          -> ./generated/avro/
    sql(postgres) -> ./generated/sql/
    jsonschema    -> ./generated/jsonschema/
    docs          -> ./generated/docs/
  }
}
```

### 4.2 Per-domain override

```mdl
domain customer {
  generate {
    openapi
    typescript
    avro
    sql(postgres)
  }
  ...
}
```

### 4.3 Target catalog

| Target | Output |
|---|---|
| `openapi` | OpenAPI 3.1 schema objects per model and projection |
| `typescript` | TypeScript interfaces with `x-modellable` JSDoc lineage tags |
| `avro` | Avro Schema JSON, one file per model version |
| `protobuf` | `.proto` file per domain |
| `sql(postgres / mysql / sqlite)` | `CREATE TABLE` DDL |
| `jsonschema` | JSON Schema 2020-12 with `x-modellable` vendor extensions |
| `asyncapi` | AsyncAPI 3.0 message schemas for event models |
| `docs` | Markdown documentation with lineage tables |

### 4.4 Adapter bindings

Bindings wire a model to a specific runtime instance. They are separate from output targets.

```mdl
binding customer-postgres {
  model: customer.Customer @ 2
  adapter: postgres
  table: customers
  fields: {
    customerId -> customer_id
    legalName  -> legal_name
    createdAt  -> created_at
  }
}
```

---

## 5. Toolchain

### 5.1 Parser

**Library:** Lark (Python PEG/EBNF parser)

The grammar lives in `modellable.lark` alongside the CLI source. This file is the canonical language definition and is versioned with the CLI.

```
.mdl file
  → Lark parser (EBNF grammar)
  → parse tree
  → Pydantic model graph
  → semantic validation
  → normalized IR
  → target emitters
```

Lark was chosen over ANTLR (no code generation step, native Python, good error messages) and pyparsing (cleaner grammar notation for a non-trivial language).

### 5.2 Language Server (LSP)

A `modellable-lsp` server (same repo, separate package) provides IDE support via the Language Server Protocol:

- Autocomplete for keywords, type names, domain references
- Inline diagnostics (type mismatches, broken `ref<>` links, version conflicts, missing `@key`)
- Go-to-definition for `ref<customer.Customer>` → opens `Customer.mdl`
- Hover showing lineage for a projected field

**Implementation:** pygls (Python LSP framework). VS Code extension ships a thin wrapper that starts the server. JetBrains and Neovim via standard LSP protocol.

### 5.3 LLM integration

LLM commands operate on `.mdl` text output — reviewable, diffable, committable. All LLM output is validated through the normal Lark parser pipeline before files are written.

| Command | Behaviour |
|---|---|
| `modellable describe Customer@2` | Plain-English explanation of the model and its lineage |
| `modellable generate --from "<description or DDL/JSON Schema>"` | Produces a `.mdl` file from freeform input |
| `modellable transform Customer@2 --to avro --explain` | Emits the target artifact and explains mapping decisions |
| `modellable suggest-projection --source Customer@2 --consumer billing` | Proposes a projection with field derivations |

---

## 6. Registry Federation and Imports

See [distributed-lineage-spec.md](distributed-lineage-spec.md) for the full design. This section covers only the IDL additions.

### 6.1 `registry` Block in `workspace.mdl`

A `registry` block turns the workspace into a named federation node.

```mdl
workspace "ecommerce-platform" {
  description: "E-commerce platform registry."

  registry {
    id:       "billing-registry"
    owns:     ["billing"]
    endpoint: "https://reg.billing.example.com"
  }

  peers: [
    { id: "customer-platform-registry", endpoint: "https://reg.customer-platform.example.com", sync: lazy  },
    { id: "orders-registry",            endpoint: "https://reg.orders.example.com",            sync: eager }
  ]

  generate {
    docs       -> "./generated/docs/"
    typescript -> "./generated/types/"
    jsonschema -> "./generated/jsonschema/"
  }
}
```

**`registry` block fields:**

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Stable unique name for this node; used as `registryId` in lineage events. |
| `owns` | Yes | Domains this node is authoritative for. |
| `endpoint` | No | Base URL of this node's Registry API (required for peers to sync from this node). |

**`peers` entry fields:**

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Peer registry identifier; used in `import … from registry "…"`. |
| `endpoint` | Yes | Base URL of the peer's Registry API. |
| `sync` | No | `eager`, `lazy` (default), or `pinned`. |
| `auth` | No | `mtls`, `bearer`, or omit for unauthenticated local dev. |

A workspace without a `registry` block operates in **local mode** (no event log, no peer syncs). This is the default and requires no migration from existing workspaces.

### 6.2 `import domain` Declaration

Makes a foreign domain available within the current workspace. Place these at the top of any `.mdl` file that references a foreign domain, before any `domain`, `projection`, or `binding` block.

```mdl
import domain customer from registry "customer-platform-registry"
import domain orders   from registry "orders-registry"
```

A pinned import locks to a specific model version and content signature:

```mdl
import domain customer from registry "customer-platform-registry"
  at customer.Customer@3#a3f8b2c1d4e5f6a7
```

The compiler rejects the import if the fetched model's content does not hash to the declared value.

### 6.3 Content Signature Suffix in References

Any `from … @` version reference may append `#<hash>` to lock to a specific content signature:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
{
  billingCustomerId  <- c.customerId
  invoiceEmail       <- c.email
}
```

The `#` suffix is optional in hand-authored files. The compiler always writes it into plan documents and lineage records.

### 6.4 LSP Changes for Federation

The language server is extended to:

- Resolve `import domain … from registry "…"` by querying the local `mirror.db`.
- Provide autocomplete for foreign model names, field names, and version numbers from the mirror.
- Show a diagnostic warning when an import references a peer registry that is not declared in `workspace.mdl`.
- Show a diagnostic error when a `#`-pinned reference does not match the mirrored model.

---

## 7. Files to Create

| File | Purpose |
|---|---|
| `idl-spec.md` | Full IDL language reference (grammar, all constructs, type system) |
| `cli/grammar/modellable.lark` | Lark EBNF grammar |
| `cli/parser/` | Parse tree → Pydantic IR |
| `cli/emitters/` | One module per output target |
| `cli/lsp/` | pygls language server |
| `editors/vscode/` | VS Code extension |
| `cli/registry/` | Federation peer sync, lineage log writer, cross-registry edge push |

---

## 8. Out of Scope for This Design

- Subscription runtime execution (Phase 5)
- Registry server integration (Phase 2)
- Catalog / governance sync (Phase 3)
- GraphQL target (post-MVP)
- Non-Python parser implementations


