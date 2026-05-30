# Modelable CLI Specification

## 1. Purpose

The Modelable CLI (`modelable`) is the primary developer interface for working with Modelable definition files locally. It provides commands for validating, resolving, inspecting, compiling, and exporting domain-owned model and projection definitions.

The CLI is designed as a phased tool: early phases focus on local authoring and compilation; later phases integrate with external registries and governance catalogs.

## 2. Delivery Phases

| Phase | Scope | Status |
|:------|:------|:-------|
| 1 | Local modelling compiler (validate, resolve, lineage, diff, compile, docs) | MVP |
| 2 | Artifact registry integration (Apicurio Registry) | Deferred |
| 3 | Catalog / governance integration (OpenMetadata) | Deferred |
| 4 | Contract interchange (Open Data Contract Standard) | Deferred |

## 3. Installation and Runtime

- **Language:** Python 3.14+
- **Framework:** Click
- **Package manager:** [uv](https://docs.astral.sh/uv/) — handles virtual environment, dependency resolution, lock file, and CLI installation
- **Build backend:** Hatchling (`pyproject.toml`)
- **Entry point:** `modelable` (installed via `uv tool install cli/` for end users; `uv sync --extra dev` for development)
- **Required dependencies:** `click>=8.1`, `lark>=1.1`, `pydantic>=2.0`, `rich>=13.0`, `jsonschema>=4.23`, `referencing>=0.35`

For full tooling setup, developer workflow, and CI integration, see `cli-tooling-spec.md`.

AI-assisted commands (`update`, `chat`) and local authoring helpers (`describe`, `generate`, `transform`, `suggest-projection`) are implemented as CLI workflows in the current repo. Provider SDK dependencies and credentials such as `ANTHROPIC_API_KEY` are only needed when a remote provider is configured for `update` or `chat`.

## 4. File Format

Definition files use the Modelable IDL with the `.mdl` extension. The grammar is defined in `cli/src/modelable/grammar/modelable.lark` and parsed by Lark (Earley).

**Syntax summary:**

- Brace-delimited blocks — no significant whitespace, LLM-friendly
- `@decorator` annotations inline before field declarations
- `@` pins a version on a model or projection declaration: `Customer @ 2`
- `(additive)` or `(breaking)` follows the version number
- `?` suffix marks an optional field
- `//` line comments

**Top-level constructs:**

| Keyword | Purpose |
|:--------|:--------|
| `domain` | Owns models, projections, and a `generate` block |
| `binding` | Wires a model to a concrete adapter instance |
| `workspace` | Workspace-level `generate` block |

**Within a domain:**

| Keyword | Purpose |
|:--------|:--------|
| `entity` | Addressable business entity (requires `@key`) |
| `aggregate` | Consistency boundary (requires `@key`) |
| `event` | Immutable fact (no `@key`) |
| `value` | Embedded value object (no `@key`) |
| `projection` | Versioned derived contract |
| `generate` | Output target declarations |

**Projection field operators:**

| Operator | Meaning |
|:---------|:--------|
| `targetField <- alias.sourceField` | Direct mapping — lineage is unambiguous |
| `targetField = expression` | Computed field — compiler extracts source field references from the CEL expression |

**Model references** use the form `domain.ModelName@version` (e.g., `customer.Customer@2`) or a range (`customer.Customer@>=2<3`).

> For the complete type system, grammar, and advanced features (joins, aggregations, auto projections, federation), see `idl-design-spec.md`.

## 5. Commands

### 5.1 `validate` — Validate definition files

```text
modelable validate [PATH] [--strict]
```

Validates Modelable `.mdl` definitions at `PATH` (file or directory). Defaults to the current directory.

**Options:**

| Flag | Description |
|:-----|:------------|
| `--strict` | Treat warnings as errors; exits non-zero if any warning is present |

**Checks performed:**

- Syntax: `.mdl` files parse without errors against the Lark grammar
- `entity` and `aggregate` models have exactly one `@key` field
- `event` and `value` models have no `@key` field
- Field types are from the supported type list (section 4 of system spec)
- Field annotations are valid (`@pii`, `@classification`, `@deprecated`, `@owner`)
- Model versions are strictly ascending within a domain block
- Projection fields each have exactly one mapping operator (`<-` or `=`)
- Aggregation functions (`count`, `sum`, `min`, `max`, `avg`) only appear in projections with `group by`
- Version ranges resolve to at least one published version

**Exit codes:** `0` on success (or warnings-only without `--strict`); `1` on validation errors.

**Examples:**

```bash
modelable validate models/customer/Customer.mdl
modelable validate ./my-project/
modelable validate ./my-project/ --strict
```

---

### 5.2 `resolve` — Look up a model or projection by reference

```text
modelable resolve REF [--path PATH]
```

Resolves a model or projection by its fully-qualified reference and prints the normalized definition.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF` | Model reference in the form `domain.ModelName@version` (e.g., `customer.Customer@2`) |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | `.` | Directory to search for `.mdl` definitions |

**Examples:**

```bash
modelable resolve customer.Customer@2
modelable resolve billing.BillingCustomer@1 --path ./models
```

---

### 5.3 `lineage` — Show field-level lineage

```text
modelable lineage REF [--path PATH]
```

Shows field-level lineage for a model or projection.

- **For projections:** Shows which source field each output field derives from, including fully-qualified source references (`domain.Model.vVersion.field`) and computed expressions.
- **For models:** Shows each field with its type and classification, labelled as `(canonical)`.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF` | Model or projection reference in the form `domain.ModelName@version` |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | `.` | Directory to search for `.mdl` definitions |

**Examples:**

```bash
modelable lineage billing.BillingCustomer@1
modelable lineage customer.Customer@2
```

---

### 5.4 `diff` — Compare two model versions

```text
modelable diff REF_A REF_B --path PATH
```

Compares two published model versions field by field and reports additions, removals, renames, nullability changes, identity changes, enum changes, and type changes. Intended to support compatibility review before publishing a new version.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF_A` | First model reference (`domain.ModelName@version`) |
| `REF_B` | Second model reference (`domain.ModelName@version`) |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | required | Directory to search for `.mdl` definitions |

**Examples:**

```bash
modelable diff customer.Customer@1 customer.Customer@2
```

---

### 5.5 `compile` — Compile definitions to artifact formats

```text
modelable compile SOURCE --target TARGET [--out DIR] [--path PATH]
```

Compiles model and projection definitions to a target artifact format. `SOURCE` can be a path to a `.mdl` file or directory, or a model reference (`domain.ModelName@version`).

In addition to the requested artifact format, `compile` always writes a `registry.db` SQLite index and plan documents to `.modelable/` in the current directory. These derived files are build artifacts — not source files — and should be added to `.gitignore`.

**Options:**

| Flag | Required | Default | Description |
|:-----|:---------|:--------|:------------|
| `--target`, `-t` | Yes | — | Output format: `json-schema`, `typescript`, or `markdown` |
| `--out`, `-o` | No | `./dist/<format>` | Output directory |
| `--path`, `-p` | No | `.` | Search path when SOURCE is a model reference |

**Default output subdirectories:**

| Target | Default output directory |
|:-------|:------------------------|
| `json-schema` | `./dist/jsonschema` |
| `typescript` | `./dist/types` |
| `markdown` | `./dist/docs` |

**Artifact ID convention:** `domain.Name.vVersion` (used as filename stem).

**Examples:**

```bash
modelable compile ./models --target json-schema --out ./dist/jsonschema
modelable compile customer.Customer@2 --target json-schema
modelable compile customer.Customer@2 --target typescript
modelable compile ./models --target markdown --out ./dist/docs
```

---

### 5.6 `docs` — Generate Markdown documentation

```text
modelable docs SOURCE [--out DIR]
```

Generates Markdown documentation for all definitions in a `.mdl` file or directory. This is a convenience wrapper around `compile --target markdown`.

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--out`, `-o` | `./dist/docs` | Output directory |

**Examples:**

```bash
modelable docs ./models --out ./dist/docs
```

---

### 5.7 `scenario` — Browse and load sample scenarios

```text
modelable scenario list
modelable scenario show SCENARIO_ID
modelable scenario load SCENARIO_ID [--output-dir DIR]
```

Manages the bundled sample scenarios shipped with the CLI.

**Subcommands:**

| Subcommand | Description |
|:-----------|:------------|
| `list` | Print all available scenario IDs and titles |
| `show SCENARIO_ID` | Display the scenario `.mdl` files with syntax highlighting |
| `load SCENARIO_ID` | Copy the scenario `.mdl` files into a working directory |

**Options for `load`:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--output-dir`, `-d` | `.` | Destination directory for the copied file |

**Bundled scenario IDs:**

| ID | Title |
|:---|:------|
| `01-ecommerce-data-warehouse` | E-Commerce Data Warehouse |
| `02-realtime-fraud-detection` | Real-Time Fraud Detection |
| `03-order-saga-microservices` | Order Saga Microservices |
| `04-credit-risk-feature-store` | Credit Risk Feature Store |
| `05-partner-marketplace-api` | Partner Marketplace API |
| `06-gdpr-compliance-audit` | GDPR Compliance Audit |
| `07-multi-system-master-data` | Enterprise Multi-System Master Data |
| `08-distributed-multi-registry` | Distributed Multi-Registry |
| `09-auto-projections` | Auto Projections |

**Examples:**

```bash
modelable scenario list
modelable scenario show 01-ecommerce-data-warehouse
modelable scenario load 04-credit-risk-feature-store --output-dir ./my-project
```

---

### 5.8 `create` — Create definitions interactively

```text
modelable create domain [--output-dir DIR]
modelable create model  [--output-dir DIR]
modelable create projection [--output-dir DIR]
```

Walks through an interactive prompt sequence and writes a `.mdl` definition file.

**Subcommands:**

| Subcommand | Description |
|:-----------|:------------|
| `domain` | Create a domain definition |
| `model` | Create a model definition |
| `projection` | Create a projection definition |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--output-dir`, `-d` | `.` | Directory to write the generated file |

**Examples:**

```bash
modelable create domain --output-dir ./my-project
modelable create model --output-dir ./my-project
modelable create projection --output-dir ./my-project
```

---

### 5.9 `describe` — Explain definitions

```text
modelable describe <target> [--path PATH]
```

Reads a `.mdl` file, directory, or model ref and prints a deterministic summary in plain English, covering:

- What problem the scenario solves
- Which domains are involved and what they own
- What each projection does and why it is designed that way
- Notable design decisions (e.g., why PIT joins, why specific materialisation strategies)

No remote provider is required. When a workspace path is supplied, repeated calls reuse the loaded workspace context.

**Examples:**

```bash
modelable describe models/orders/Order.mdl
modelable describe customer.Customer@1 --path ./my-project/
modelable describe ./my-project/
```

---

### 5.10 `generate` — Generate definitions

```text
modelable generate --from <source> [--format FORMAT] [--domain DOMAIN] [--name NAME] [--output FILE]
```

Generates Modelable `.mdl` definitions from a natural language description or existing schemas (DDL, JSON Schema, OpenAPI, Avro, Protobuf, or SQL) using the local import or deterministic draft scaffolding path. When `--output` is provided, the result is automatically validated through the Lark parser pipeline before writing.
When `--output` is provided, the command also writes a deterministic `.provenance.json` sidecar next to the generated file.

**Options:**

| Flag | Description |
|:-----|:------------|
| `--from SOURCE` | Natural language prompt, existing source file, or inline source text |
| `--format FORMAT` | Source format for import paths, such as `json-schema`, `openapi`, `avro`, `protobuf`, or `sql` |
| `--domain DOMAIN` | Override the output domain when importing source files |
| `--name NAME` | Override the output model name when drafting from text |
| `--output FILE` | Write output to a file and auto-validate (default: print to stdout) |

**Examples:**

```bash
modelable generate --from "customer lifecycle data" --output my-customer.mdl
modelable generate --from ./existing-schema.json --format json-schema --domain customer --output imported.mdl
modelable generate --from ./existing.sql --format sql --domain customer
```

---

### 5.11 `codegen` — Explore artifact formats and type mappings

```text
modelable codegen formats
modelable codegen types [--format FORMAT]
```

Displays supported artifact output formats and the type mapping from Modelable field types to each target format.

**Subcommands:**

| Subcommand | Description |
|:-----------|:------------|
| `formats` | List all supported compilation targets |
| `types` | Show the field-type mapping for a given target format |

**Options for `types`:**

| Flag | Description |
|:-----|:------------|
| `--format FORMAT` | Target format to show type mappings for (`json-schema`, `typescript`, `markdown`) |

---

### 5.12 `publish apicurio` — Push artifacts to Apicurio Registry

```text
modelable publish apicurio PATH [--url URL] [--group GROUP]
```

**Phase 2 — not yet implemented.**

Pushes compiled JSON Schema artifacts to an Apicurio Schema Registry instance. Artifact IDs follow the convention `domain.Name.vVersion`.

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--url` | — | Apicurio Registry base URL |
| `--group` | `modelable` | Artifact group ID |

**Intended workflow:**

```bash
modelable compile ./models --target json-schema --out ./dist/jsonschema
modelable publish apicurio ./dist/jsonschema --url http://localhost:8080
```

---

### 5.13 `pull apicurio` — Pull schema artifacts

```text
modelable pull apicurio REF [--url URL] [--out DIR]
```

**Phase 2 — not yet implemented.**

Pulls a specific schema artifact from an Apicurio Registry instance by model reference.

---

### 5.14 `export openmetadata` — Export catalog metadata

```text
modelable export openmetadata [PATH] --out FILE
```

**Phase 3 — not yet implemented.**

Exports domain, model, and projection metadata to a JSON file suitable for OpenMetadata catalog ingestion.

**Modelable → OpenMetadata mapping:**

| Modelable concept | OpenMetadata concept |
|:-------------------|:--------------------|
| Domain | Domain |
| Model | Custom asset |
| Projection | Data product / custom asset |
| Field classification | Tags / Glossary terms |
| Lineage (`from` references) | Lineage edges |

The output document contains three top-level arrays: `domains`, `assets`, and `lineage`.

**Options:**

| Flag | Required | Description |
|:-----|:---------|:------------|
| `--out`, `-o` | Yes | Output JSON file path |

**Examples:**

```bash
modelable export openmetadata ./models --out ./dist/openmetadata.json
modelable publish openmetadata ./dist/openmetadata.json
```

---

### 5.15 `publish openmetadata` — Push metadata to OpenMetadata

```text
modelable publish openmetadata PATH [--url URL]
```

**Phase 3 — not yet implemented.**

Pushes the OpenMetadata export document to a live OpenMetadata instance.

---

### 5.16 `export odcs` — Export an Open Data Contract Standard document

```text
modelable export odcs REF --out FILE [--path PATH]
```

**Phase 4 — not yet implemented.**

Exports a single model or projection as an Open Data Contract Standard (ODCS) v1.0.0 YAML document. The output can be linted with `datacontract lint`.

**ODCS document structure:**

```yaml
dataContractSpecification: "1.0.0"
id: "modelable://<domain>/<name>/v<version>"
info:
  title: "<domain>.<name>.v<version>"
  version: "<version>"
  owner: "<domain>"
  description: "<model description>"
schema:
  <model_name>:
    type: object
    properties:
      <field_name>:
        type: <field_type>
        required: <bool>          # if set on the field
        classification: <value>   # if set on the field
        description: <value>      # if set on the field
```

**Options:**

| Flag | Required | Default | Description |
|:-----|:---------|:--------|:------------|
| `--out`, `-o` | Yes | — | Output YAML file path |
| `--path`, `-p` | No | `.` | Directory to search for definitions |

**Examples:**

```bash
modelable export odcs customer.Customer@1 --out ./dist/customer.contract.yaml
datacontract lint ./dist/customer.contract.yaml
```

---

## 6. AI Integration Details

The `update` and `chat` commands use the configured LLM provider. The model is configurable by command flag, environment variable, or workspace config; see [LLM Integration Specification](llm-integration-spec.md).

- `describe` and `generate` use local workspace summaries and import/scaffolding logic.
- Generated `.mdl` output is validated through the Lark parser pipeline when `--output` is supplied to `generate`. Malformed output is caught before writing to disk.
- Complex scenario generation may take 10–30 seconds.

## 7. Quick-Start Workflow

```bash
# 1. Create a domain definition
modelable create domain --output-dir ./my-models

# 2. Add a model with local generation
modelable generate --from "order processing model" --output ./my-models/Order.mdl

# 3. Validate the new file
modelable validate ./my-models/Order.mdl

# 4. Understand what it does
modelable describe ./my-models/Order.mdl

# 5. Inspect lineage
modelable lineage billing.BillingCustomer@1 --path ./my-models

# 6. Compare versions
modelable diff customer.Customer@1 customer.Customer@2 --path ./my-models

# 7. Compile to JSON Schema and TypeScript
modelable compile ./my-models --target json-schema --out ./dist/jsonschema
modelable compile ./my-models --target typescript --out ./dist/types

# 8. Generate documentation
modelable docs ./my-models --out ./dist/docs
```

## 8. Output and Exit Codes

- All human-readable output uses `rich` for colored, formatted terminal output.
- Exit code `0` indicates success.
- Exit code `1` indicates a validation error, resolution failure, or unrecoverable CLI error.
- Commands that produce no output (e.g., no matching models found) exit `0` with a warning message.

## 9. Open Design Decisions

- **Plugin architecture for compilers:** The compile targets are currently hard-coded. A plugin registry for third-party targets is deferred.
- **Authentication for registry commands:** Apicurio and OpenMetadata authentication mechanisms (API keys, OAuth, mTLS) are not yet specified.
- **Incremental compilation:** Whether `compile` should track which files changed and only recompile affected artifacts is deferred.
- **LSP parser mode:** The language server currently uses Lark Earley for correctness. Whether to migrate to LALR for lower-latency IDE responses is deferred.

**Resolved:**

- **Definition format:** Custom text IDL (`.mdl`), parsed with Lark (Earley). See `idl-design-spec.md`.
- **AI model configuration:** LLM-backed commands use configurable model selection by flag, environment variable, workspace config, then CLI default. See `llm-integration-spec.md`.

---

## 10. Deferred and Federated Commands

The following commands are defined in other specifications and will be added to the CLI in later phases. They are collected here to keep the CLI specification complete.

The current `codegen` command reports the implemented formats in this repository, including C#, Java, Python, Rust, and Go. Additional future first-class generated-language targets remain deferred until their dedicated emitters exist.

### 10.1 `inspect` — Inspect compiler-expanded definitions

```text
modelable inspect <Entity>@<version> --auto [--path PATH]
```

Displays the compiler-expanded auto projections (`db`, `request`, `reply`, `event`) for a given entity version. The output is a `.mdl`-like representation of the generated projection fields with full lineage annotations.

**Defined in:** `idl-design-spec.md` §3.7, `modelable-system-spec.md` §17.

### 10.2 `transform` — Emit and explain a target artifact

```text
modelable transform <Entity>@<version> --to <target> [--explain] [--path PATH]
```

Emits the target artifact (e.g., Avro schema, JSON Schema) for a single model version and optionally prints an explanation of mapping decisions.

When `--out` is supplied, the command writes the artifact to disk, writes a `.provenance.json` sidecar next to it, and prints the standard audit summary to stdout.

**Defined in:** `idl-design-spec.md` §5.1.

### 10.3 `suggest-projection` — AI-assisted projection proposal

```text
modelable suggest-projection --source <Domain.Model@version> --consumer <domain>
```

Proposes a projection definition with field derivations tailored to a consuming domain, using the AI integration described in §3.7.

The generated `.mdl` is validated before any file write.

When `--output` is supplied, the command writes the generated projection to disk, writes a `.provenance.json` sidecar next to it, and prints the standard audit summary to stdout.

**Defined in:** `idl-design-spec.md` §5.1.

### 10.4 `update` — Natural-language model or projection edit

```text
modelable update <Domain.Model@version> "<edit instruction>" --path PATH [--output FILE] [--preview]
```

Applies a natural-language change request to an existing model or projection version, rewrites the `.mdl` source, and validates the result before writing. `--preview` shows the rendered diff without writing changes.

When `MODELABLE_LLM_PROVIDER=ollama` and `MODELABLE_LLM_MODEL=<model>` are set, `update` asks the local Ollama server for a structured edit plan before applying the change. Without a configured provider, it falls back to the deterministic local editor path.
When the command writes a file, it prints a concise audit summary including the provider, model, validation status, written path, source ref, and repair count, and it writes a `.provenance.json` sidecar next to the updated `.mdl`.

**Defined in:** `llm-integration-spec.md` §6.4.

### 10.5 `chat` — Interactive model conversation

```text
modelable chat --path PATH [--ref <Domain.Model@version>] [--message TEXT] [--provider NAME] [--model MODEL] [--base-url URL]
```

Starts a conversational session against the configured model. Without `--message`, the command prompts for turns until `/exit` or EOF. `--message` sends a single turn and exits, which is useful for tests and scripts. The chat command never writes files; editing still goes through `update`.

Within the session, slash commands provide structured actions:

- `/help` prints the available chat commands.
- `/ref <ref>` sets the focused model or projection.
- `/context` prints the current workspace or focused-ref summary.
- `/describe [ref]` prints a summary without changing state.
- `/recommend <ref> [consumer]` prints a recommendation from the current workspace.
- `/ask <question>` asks a workspace question using the same reasoning helpers.
- `/update <ref> <instruction>` shows a validated preview diff without writing.

**Defined in:** `llm-integration-spec.md` §6.6.

### 10.6 `registry` — Federated registry management

```text
modelable registry init --id <registry-id> --owns <domain>[,<domain>...]
modelable registry peer add --id <peer-id> --git <url> [--branch <branch>] [--sync <mode>] [--writeback <mode>]
modelable registry graph
modelable registry sync [--peer <peer-id>]
```

- `registry init` — Initialize a workspace as a named registry node.
- `registry peer add` — Register an upstream peer registry.
- `registry graph` — Print the federation DAG with sync state.
- `registry sync` — Force-sync all peers (or a single peer) regardless of sync mode.

**Defined in:** `distributed-lineage-spec.md` §5.

### 10.5 `dependents` — List downstream consumers

```text
modelable dependents <Domain.Model@version>
```

Lists all downstream projections and consumer entries that depend on the given model version. Reads the `consumers/` tree across the workspace and peer mirrors.

**Defined in:** `distributed-lineage-spec.md` §6.

### 10.6 `lineage verify` — Verify content signatures

```text
modelable lineage verify <REF>
```

Verifies that the content signature (SHA-256) of the given model or projection matches the cached mirror. Reports mismatches that indicate upstream drift.

**Defined in:** `distributed-lineage-spec.md` §6.

### 10.7 `lineage export` — Export lineage as NDJSON

```text
modelable lineage export --format ndjson --output <path>
```

Exports the full lineage graph from `registry.db` as NDJSON for external catalog ingestion.

**Defined in:** `distributed-lineage-spec.md` §6.
