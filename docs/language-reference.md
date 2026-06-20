# Modelable Language Reference

> **Authority:** This document defines the current `.mdl` language. Governance
> annotations and CEL expression rules are included here so authors do not need
> to reconcile separate language specifications.

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** New `.mdl` IDL language — syntax, type system, projections, output targets, toolchain

---

## Context

Modelable needs a format for defining domain-owned canonical models, projections with explicit lineage, and output target declarations. Three options were evaluated:

- **Option A — Custom YAML DSL:** Full control, already partially specced, but verbose for complex projections and every emitter must be written from scratch.
- **Option B — Extend TypeSpec:** Gets OpenAPI/Protobuf emitters for free, but TypeSpec's API-centric model fights the projection/lineage/domain-ownership concepts that are Modelable's core.
- **Option C — Custom text IDL (chosen):** Purpose-built grammar for Modelable's concepts. More expressive than YAML for derivation logic, LLM-friendly due to explicit delimiters and consistent structure, enables a language server.

Primary authoring personas are application developers and data/platform engineers. The CLI (including LLM integration) is the primary interaction path — developers use `modelable generate` and `modelable transform` to create and evolve files, then review the output.

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

  entity Customer @ 2 (additive) {
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
| `json` | Arbitrary JSON value, opaque to Modelable; maps to `serde_json::Value` (Rust), `unknown` (TypeScript), `{}` (JSON Schema) |

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
| `@classification("level")` | Governance classification (open, internal, confidential, secret) |
| `@deprecated(replacedBy: "field")` | Field is deprecated |
| `@owner("team")` | Field-level ownership override |
| `@server` | Field is assigned by the server at write time (e.g. auto-generated IDs, timestamps). Excluded from `request` auto projections by default. |

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

### 3.7 Auto Projections

Auto projections generate four standard derived models from a single `entity` or `aggregate` definition. They eliminate the need to hand-author repetitive projection boilerplate for the most common use cases: a persistence contract, an API write model, an API read model, and a change event.

#### Kinds

| Kind | Generated name | Purpose | Excludes by default |
|---|---|---|---|
| `db` | `{Entity}Db` | Persistence contract; used for SQL DDL generation | Nothing |
| `request` | `{Entity}Request` | Write model for API create/update | Fields annotated `@server` |
| `reply` | `{Entity}Reply` | Read model for API responses | Nothing |
| `event` | `{Entity}Event` | Change event emitted on entity state transitions | Nothing |

#### Syntax

```mdl
domain customer {
  entity Customer @ 1 (additive) {
    @key       customerId:   uuid
               legalName:    string
    @pii       email:        string
               phoneNumber?: string
               status:       enum(active, suspended, deleted)
    @server    createdAt:    timestamp
    @server    updatedAt?:   timestamp
  }

  auto projections Customer @ 1 {
    db
    request
    reply
    event
  }
}
```

The compiler expands this into four fully explicit projections, each carrying complete field-level lineage. The expansion is included in the plan document and is inspectable with `modelable inspect Customer@1 --auto`.

#### Compiler expansion

The example above expands to the following four projections:

```mdl
// CustomerDb — full entity, for persistence layer
projection CustomerDb @ 1
  from customer.Customer @ 1 as c
{
  customerId   <- c.customerId
  legalName    <- c.legalName
  email        <- c.email
  phoneNumber  <- c.phoneNumber
  status       <- c.status
  createdAt    <- c.createdAt
  updatedAt    <- c.updatedAt
}

// CustomerRequest — write model, @server fields excluded
projection CustomerRequest @ 1
  from customer.Customer @ 1 as c
{
  legalName    <- c.legalName
  email        <- c.email
  phoneNumber  <- c.phoneNumber
  status       <- c.status
}

// CustomerReply — read model, all fields
projection CustomerReply @ 1
  from customer.Customer @ 1 as c
{
  customerId   <- c.customerId
  legalName    <- c.legalName
  email        <- c.email
  phoneNumber  <- c.phoneNumber
  status       <- c.status
  createdAt    <- c.createdAt
  updatedAt    <- c.updatedAt
}

// CustomerEvent — change-event projection, all fields
projection CustomerEvent @ 1
  from customer.Customer @ 1 as c
  on [created, updated, deleted]
{
  customerId   <- c.customerId
  legalName    <- c.legalName
  email        <- c.email
  phoneNumber  <- c.phoneNumber
  status       <- c.status
  createdAt    <- c.createdAt
  updatedAt    <- c.updatedAt
}
```

The event projection maps to the standard change event envelope defined in the system spec (section 6.1). The `on` list controls which operations emit events. When omitted, all operations (`created`, `updated`, `deleted`) are included.

#### Customisation

Individual kinds can be customised with inline options. Unspecified kinds use their defaults.

```mdl
auto projections Customer @ 1 {
  db

  // Exclude a specific field from the write model
  request exclude [status]

  // Exclude all PII from API responses
  reply   exclude [@pii]

  // Emit events only on creation and deletion
  event   on [created, deleted]
}
```

**`exclude` accepts:**
- A list of field names: `exclude [fieldName, ...]`
- An annotation filter: `exclude [@pii]`, `exclude [@classification("secret")]`
- A combination: `exclude [internalScore, @pii]`

**`on` accepts:** any subset of `[created, updated, deleted]`.

#### Versioning

Each `auto projections` block is bound to one entity version. When the entity is updated to a new version, add a new `auto projections` block for that version.

```mdl
entity Customer @ 2 (additive) {
  @key       customerId:   uuid
             legalName:    string
  @pii       email:        string
             tier:         enum(standard, premium)   // new field
  @server    createdAt:    timestamp
}

auto projections Customer @ 2 {
  db
  request
  reply
  event
}
```

The compiler generates `CustomerDb @ 2`, `CustomerRequest @ 2`, `CustomerReply @ 2`, and `CustomerEvent @ 2` — each a distinct immutable projection version, separately tracked in lineage records.

#### Constraints

- `auto projections` may only target `entity` or `aggregate` models.
- The generated names (`CustomerDb`, `CustomerRequest`, `CustomerReply`, `CustomerEvent`) are reserved for the entity in that domain. Defining an explicit projection with one of those names for the same entity version is a compile error.
- All auto-generated projections follow the same immutability rules as hand-authored projections.
- Auto projections do not support joins, aggregations, or computed fields. Use explicit projections for those cases.

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

### 4.1.1 Workspace-level AI configuration

LLM-backed CLI commands may read optional AI defaults from `workspace.mdl`. Command flags and environment variables take precedence over this block.

```mdl
workspace "commerce-platform" {
  ai {
    provider: "anthropic"
    model:    "claude-opus-4-7"
  }
}
```

The `ai` block is authoring configuration only. It does not affect published model or projection semantics, and changing it does not require new model or projection versions.

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
| `typescript` | TypeScript interfaces with `x-modelable` JSDoc lineage tags |
| `avro` | Avro Schema JSON, one file per model version |
| `protobuf` | `.proto` file per domain |
| `sql(postgres / mysql / sqlite)` | `CREATE TABLE` DDL |
| `jsonschema` | JSON Schema 2020-12 with `x-modelable` vendor extensions |
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

**Library:** Lark (Python EBNF parser)

The grammar lives in `modelable.lark` alongside the CLI source. This file is the canonical language definition and is versioned with the CLI.

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

A `modelable-lsp` server (same repo, separate package) provides IDE support via the Language Server Protocol:

- Autocomplete for keywords, type names, domain references
- Inline diagnostics (type mismatches, broken `ref<>` links, version conflicts, missing `@key`)
- Go-to-definition for `ref<customer.Customer>` → opens `Customer.mdl`
- Hover showing lineage for a projected field

**Implementation:** pygls (Python LSP framework). VS Code extension ships a thin wrapper that starts the server. JetBrains and Neovim via standard LSP protocol.

### 5.3 LLM integration

LLM commands operate on `.mdl` text output — reviewable, diffable, committable. All LLM output is validated through the normal Lark parser pipeline before files are written.

| Command | Behaviour |
|---|---|
| `modelable describe Customer@2` | Plain-English explanation of the model and its lineage |
| `modelable generate --from "<description or source artifact>"` | Produces a `.mdl` file from freeform input or supported schema/contract files |
| `modelable transform Customer@2 --to avro --explain` | Emits the target artifact and explains mapping decisions |
| `modelable suggest-projection --source Customer@2 --consumer billing` | Proposes a projection with field derivations |

---

## 6. Registry Federation and Imports

See [compiler-reference.md](compiler-reference.md) for registry and distributed-lineage behavior. This section covers only the IDL syntax.

### 6.1 `registry` Block in `workspace.mdl`

A `registry` block turns the workspace into a named node in the federation graph. Peers are other git repositories that own domains this workspace depends on.

```mdl
workspace "analytics-platform" {
  description: "Analytics registry — projects across customer and orders."

  registry {
    id:   "analytics-registry"
    owns: ["analytics"]
  }

  peers: [
    {
      id:        "customer-platform-registry"
      git:       "git@github.com:acme/customer-models.git"
      branch:    "main"
      sync:      eager
      writeback: pr
    },
    {
      id:        "orders-registry"
      git:       "git@github.com:acme/orders-models.git"
      branch:    "main"
      sync:      eager
      writeback: commit
    }
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
| `id` | Yes | Stable unique name for this node. Used as `registryId` in lineage events and as the directory name written into peer `consumers/` trees. |
| `owns` | Yes | Domains this node is authoritative for. |

**`peers` entry fields:**

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Peer registry identifier. Must match the peer's own `registry.id`. Used in `import … from registry "…"`. |
| `git` | Yes | Git remote URL. The CLI runs `git fetch` against this remote to sync the mirror. Authentication uses the host machine's git credential configuration. |
| `branch` | No | Branch to track. Default: `main`. |
| `sync` | No | `eager` — sync on every `compile`; `lazy` — sync on first reference (default); `pinned` — never sync, always use local mirror. |
| `writeback` | No | How consumer entries are pushed back to the peer: `commit` — push directly; `pr` — open a pull request via the git hosting API; `none` — skip. Default: `commit`. |

A workspace without a `registry` block operates in **local mode** — no sync, no write-back, no lineage log. This is the default for single-team workspaces and requires no migration.

### 6.2 `import domain` Declaration

Placed at the top of any `.mdl` file that references a foreign domain, before any `domain`, `projection`, or `binding` block.

```mdl
import domain customer from registry "customer-platform-registry"
import domain orders   from registry "orders-registry"
```

A pinned import locks to a specific model version and content signature:

```mdl
import domain customer from registry "customer-platform-registry"
  at customer.Customer@3#a3f8b2c1d4e5f6a7
```

The compiler rejects the import if the fetched model does not hash to the declared value.

### 6.3 Content Signature Suffix in References

Any `from … @` version reference may append `#<hash>` to pin to a specific content:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
{
  billingCustomerId  <- c.customerId
  invoiceEmail       <- c.email
}
```

The `#` suffix is optional in hand-authored files. The compiler always writes it into plan documents and lineage records.

### 6.4 Consumer Entry (Written by the CLI)

The compiler writes a small MDL file back to each upstream peer's `consumers/` directory during the write-back phase. This file is never authored by hand.

```mdl
// consumers/analytics-registry/CustomerOrderSummary@1.mdl
consumer {
  registry:   "analytics-registry"
  projection: "analytics.CustomerOrderSummary@1"
  uses: [
    "customer.Customer@3#a3f8b2c1d4e5f6a7"
  ]
  registeredAt: "2026-05-14T09:05:00Z"
}
```

### 6.5 LSP Changes for Federation

- Resolve `import domain … from registry "…"` against the local `mirror/` directory.
- Autocomplete foreign model names, field names, and version numbers from the mirror.
- Warn when an import references a peer not declared in `workspace.mdl`.
- Error when a `#`-pinned reference does not match the mirrored model.

---

## 7. Implementation Map

| File | Purpose |
|---|---|
| `language-reference.md` | Full IDL language reference (grammar, all constructs, type system) — this document |
| `cli/src/modelable/grammar/modelable.lark` | Lark EBNF grammar |
| `cli/src/modelable/parser/` | Parse tree to Pydantic IR |
| `cli/src/modelable/emitters/` | Generated artifact backends |
| `cli/src/modelable/lsp/` | pygls language server |
| `vscode/` | VS Code extension |
| `cli/src/modelable/registry/` | Local registry graph and lineage index |

---

## 8. Deferred Language Scope

- Subscription runtime execution (Phase 5)
- Registry HTTP server (no server needed for dev-time use; deferred if ever needed)
- Catalog / governance sync (Phase 3)
- GraphQL target (post-MVP)
- Non-Python parser implementations

---

## 9. CEL Expression Rules

CEL is the expression language for computed projection fields, join predicates,
filters, aggregation guards, and future runtime parameter expressions. The
compiler parses and type-checks CEL and extracts field-level lineage before an
expression can reach a runtime adapter.

The supported compiler subset includes literals, field selection, boolean and
arithmetic operators, comparisons, conditional expressions, list membership,
and the deterministic helper functions implemented by the validator. Expression
types must be assignable to the declared destination field. Unknown aliases,
unknown fields, unsafe functions, and type mismatches are validation errors.

Runtime namespaces such as `request`, `auth`, and `params` are reserved for
deferred runtime contexts. Their presence in the grammar does not imply that a
runtime feature is currently available.

## 10. Ownership, Classification, and Access

Ownership and governance metadata are definition-time contract metadata:

- Every model belongs to one domain and has an explicit owner.
- Published versions are immutable, including their governance metadata.
- `@pii` identifies personally identifiable information.
- `@classification` uses the ordered levels `open`, `internal`, `confidential`,
  and `secret`.
- Projection fields inherit source restrictions through lineage. A projection
  may narrow access but must not silently broaden it or lower classification.
- Access declarations document `read`, `project`, and related grants. The local
  compiler reports deterministic governance findings; it does not claim to be
  an organizational authorization service.

Generated artifacts must preserve ownership, classification, lineage, and
point-of-record metadata where the target supports extensions. Otherwise the
compiler must emit companion metadata or an explicit loss diagnostic.

## 11. Language Authority

This file is the detailed syntax and language-semantics reference. The
[architecture](architecture.md) remains authoritative for product concepts and
published-contract guarantees. If an example here conflicts with the grammar
or validator, the implementation and its tests identify a documentation defect;
they do not silently redefine the product model.
