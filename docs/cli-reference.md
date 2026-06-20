# Modelable Tooling Reference

> **Scope:** CLI commands, language-server behavior, AI-assisted authoring, and
> the local development toolchain.

## 1. Purpose

The Modelable CLI (`modelable`) is the primary developer interface for working with Modelable definition files locally. It provides commands for validating, resolving, inspecting, compiling, and exporting domain-owned model and projection definitions.

The CLI is designed as a phased tool: early phases focus on local authoring and compilation; later phases integrate with external registries and governance catalogs.

## 2. Delivery Phases

| Phase | Scope | Status |
|:------|:------|:-------|
| 1 | Local modelling compiler (validate, resolve, lineage, diff, compile, docs, local artifact targets) | MVP |
| 2 | Artifact registry integration (Apicurio Registry) | Implemented JSON Schema artifact publish/pull |
| 3 | Catalog / governance integration (OpenMetadata / OpenLineage) | Local export targets implemented; live publish and runtime collection deferred |
| 4 | Contract interchange and external spec tracking | Tracked dbt/FHIR/ODCS drift workflow implemented; local dbt/FHIR/ODCS bootstrapping and ODCS compile target implemented |

## 3. Installation and Runtime

- **Language:** Python 3.14+
- **Framework:** Click
- **Package manager:** [uv](https://docs.astral.sh/uv/) — handles virtual environment, dependency resolution, lock file, and CLI installation
- **Build backend:** Hatchling (`pyproject.toml`)
- **Entry point:** `modelable` (installed via `uv tool install cli/` for end users; `uv sync --extra dev` for development)
- **Required dependencies:** `click>=8.1`, `lark>=1.1`, `pydantic>=2.0`, `rich>=13.0`, `jsonschema>=4.23`, `referencing>=0.35`

Development and CI commands are consolidated in section 13 and [maintainers.md](maintainers.md).

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

> For the complete type system, grammar, and advanced features, see [language-reference.md](language-reference.md).

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
If the comparison is breaking, the command prints the report and exits with code `1`.

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
modelable compile SOURCE --target TARGET [--out DIR] [--registry PATH]
```

Compiles model and projection definitions to a target artifact format. `SOURCE`
is a path to a `.mdl` file or directory.

In addition to the requested artifact format, `compile` always writes a `registry.db` SQLite index and plan documents to `.modelable/` in the current directory. These derived files are build artifacts — not source files — and should be added to `.gitignore`.

**Options:**

| Flag | Required | Default | Description |
|:-----|:---------|:--------|:------------|
| `--target` | Yes | — | Output format: `json-schema`, `markdown`, `typescript`, `csharp`, `java`, `python`, `rust`, `go`, `sql-postgres`, `sql-clickhouse`, `dbt-yaml`, `fhir-profile`, `openmetadata`, `openlineage`, or `odcs` |
| `--out`, `-o` | No | `./dist/<format>` | Output directory |
| `--registry` | No | `.modelable/registry.db` | Registry index path |

**Default output subdirectories:**

| Target | Default output directory |
|:-------|:------------------------|
| `json-schema` | `./dist/jsonschema` |
| `markdown` | `./dist/docs` |
| `typescript` | `./dist/types` |
| `csharp` | `./dist/csharp` |
| `java` | `./dist/java` |
| `python` | `./dist/python` |
| `rust` | `./dist/rust` |
| `go` | `./dist/go` |
| `sql-postgres` | `./dist/sql/postgres` |
| `sql-clickhouse` | `./dist/sql/clickhouse` |
| `dbt-yaml` | `./dist/dbt` |
| `fhir-profile` | `./dist/fhir` |
| `openmetadata` | `./dist/openmetadata` |
| `openlineage` | `./dist/openlineage` |
| `odcs` | `./dist/odcs` |

**Artifact ID convention:** `domain.Name.vVersion` (used as filename stem).

**Examples:**

```bash
modelable compile ./models --target json-schema --out ./dist/jsonschema
modelable compile ./models --target typescript
modelable compile ./models --target markdown --out ./dist/docs
modelable compile ./models --target fhir-profile --out ./dist/fhir
modelable compile ./models --target openmetadata --out ./dist/openmetadata
modelable compile ./models --target openlineage --out ./dist/openlineage
modelable compile ./models --target odcs --out ./dist/odcs
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

Generates Modelable `.mdl` definitions from a natural language description or
existing schemas (DDL, JSON Schema, OpenAPI, Avro, Protobuf, SQL, dbt
`schema.yml`/`manifest.json` models or source tables, FHIR R4
`StructureDefinition`, or ODCS YAML)
using the local import or deterministic draft scaffolding path. When `--output`
is provided, the result is automatically validated through the Lark parser
pipeline before writing.
When `--output` is provided, the command also writes a deterministic `.provenance.json` sidecar next to the generated file.

**Options:**

| Flag | Description |
|:-----|:------------|
| `--from SOURCE` | Natural language prompt, existing source file, or inline source text |
| `--format FORMAT` | Source format for import paths, such as `json-schema`, `openapi`, `avro`, `protobuf`, `sql`, `dbt`, `fhir`, or `odcs` |
| `--domain DOMAIN` | Override the output domain when importing source files |
| `--name NAME` | Override the output model name when drafting from text; selects a named model/source table for dbt and a named schema object for ODCS |
| `--output FILE` | Write output to a file and auto-validate (default: print to stdout) |

**Examples:**

```bash
modelable generate --from "customer lifecycle data" --output my-customer.mdl
modelable generate --from ./existing-schema.json --format json-schema --domain customer --output imported.mdl
modelable generate --from ./existing.sql --format sql --domain customer
modelable generate --from ./dbt/schema.yml --domain customer --output customer.mdl
modelable generate --from ./dbt/schema.yml --name customers --domain customer --output customer-source.mdl
modelable generate --from ./fhir/PatientProfile.json --domain clinical --output patient.mdl
modelable generate --from ./contracts/customer.yml --domain customer --output customer.mdl
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
| `--format FORMAT` | Target format to show type mappings for any implemented target listed by `modelable codegen formats` |

---

### 5.12 `publish apicurio` — Push artifacts to Apicurio Registry

```text
modelable publish apicurio SOURCE --url URL [--group GROUP] [--token TOKEN] [--dry-run]
```

Publishes JSON Schema 2020-12 artifacts generated from `SOURCE` to an
Apicurio Registry 3.x Core Registry API endpoint. Apicurio stores derived
artifacts only; `.mdl` files and the normalized Modelable graph remain the
source of truth for contract semantics, lineage, compatibility, and governance.
Artifact IDs follow the convention `domain.Name.vVersion`.

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--url` | — | Apicurio Registry base URL or `/apis/registry/v3` URL |
| `--group` | `default` | Artifact group ID |
| `--token` | `MODELABLE_APICURIO_TOKEN` | Bearer token for authenticated registries |
| `--dry-run` | `false` | List generated artifact IDs without publishing |

**Example:**

```bash
modelable publish apicurio ./models --url http://localhost:8080 --group contracts
```

---

### 5.13 `pull apicurio` — Pull schema artifacts

```text
modelable pull apicurio REF --url URL [--group GROUP] [--out DIR] [--token TOKEN]
```

Pulls a specific JSON Schema artifact from Apicurio Registry by Modelable
reference, using the same `domain.Name@version` form accepted by local
Modelable commands. The pulled artifact is written to
`DIR/domain/Name.vVersion.json`.

---

### 5.14 `graph export` — Export the normalized model graph

```text
modelable graph export SOURCE [--path PATH] [--focus REF] [--out FILE]
```

Exports deterministic JSON for the normalized model/projection graph. JSON is the canonical first slice for this command, and the output is intended for inspection, demo flows, and later renderers. `SOURCE` can be a workspace path, `.mdl` file, or directory. `--focus` narrows the export to a model or projection and its immediate neighborhood. The command does not mutate source files.

**Options:**

| Flag | Required | Default | Description |
|:-----|:---------|:--------|:------------|
| `--path`, `-p` | No | `.` | Directory to search for definitions when resolving the source workspace |
| `--focus` | No | — | Optional model or projection reference to center the exported graph |
| `--out`, `-o` | No | — | Output JSON file path |

**Examples:**

```bash
modelable graph export ./models --out ./dist/modelable-graph.json
modelable graph export ./models --focus customer.Customer@1 --out ./dist/customer-graph.json
modelable graph export ./models --focus customer.CustomerView@1 --out ./dist/customer-view-graph.json
```

---

### 5.15 `export openmetadata` — Export catalog metadata

```text
modelable export openmetadata [PATH] --out FILE
```

**Phase 3 — command form not yet implemented.** The shipped local export path is
`modelable compile PATH --target openmetadata --out DIR`. Live catalog publish
remains deferred.

The planned `export openmetadata` command would export domain, model, and
projection metadata to a single JSON file suitable for OpenMetadata catalog
ingestion. The current compile target writes one JSON artifact per domain.

**Modelable → OpenMetadata mapping:**

| Modelable concept | OpenMetadata concept |
|:-------------------|:--------------------|
| Domain | Domain |
| Model | Custom asset |
| Projection | Data product / custom asset |
| Field classification | Tags / Glossary terms |
| Lineage (`from` references) | Lineage edges |

The compile target writes one JSON file per Modelable domain. Each file includes
the domain owner and description, model and projection assets, field-level key /
PII / classification / owner metadata, projection source metadata, and direct
field lineage edges.

**Options:**

| Flag | Required | Description |
|:-----|:---------|:------------|
| `--out`, `-o` | Yes | Output JSON file path |

**Examples:**

```bash
modelable compile ./models --target openmetadata --out ./dist/openmetadata
```

---

### 5.16 `compile --target openlineage` — Export OpenLineage events

```text
modelable compile PATH --target openlineage --out DIR
```

**Phase 3 — implemented as a compile target.**

Exports each model and projection version as a deterministic OpenLineage
`COMPLETE` run event. The event output dataset includes a schema facet, and
projection outputs include an OpenLineage column-lineage facet derived from
Modelable direct and computed projection mappings. These are design-time
artifacts for catalog ingestion; runtime OpenLineage event collection remains
deferred.

**Examples:**

```bash
modelable compile ./models --target openlineage --out ./dist/openlineage
```

---

### 5.17 `compile --target fhir-profile` — Export FHIR R4 profiles

```text
modelable compile PATH --target fhir-profile --out DIR
```

**Phase 4b — implemented as a local compile target.**

Exports each projection version as a FHIR R4 `StructureDefinition` constraint
profile. The current supported base-resource set is `Patient`, `Observation`,
and `Encounter`, selected from the projection source model name. Other source
models emit a warning and use FHIR `Basic` as the base resource so the artifact
remains explicit about representational loss.

The generated profile includes deterministic root and field
`ElementDefinition` entries, projection lineage under the `modelable` mapping
identity, required/optional cardinality from the source field, primitive type
mapping, enum bindings to Modelable ValueSet URLs, FHIR `Reference` target
profiles, and Modelable classification/PII extensions.

Maintainers can run the external HL7 FHIR Validator smoke when the official
`validator_cli.jar` is available:

```bash
MODELABLE_FHIR_VALIDATOR=1 MODELABLE_FHIR_VALIDATOR_JAR=/path/to/validator_cli.jar uv run pytest tests/test_fhir_validator.py --tb=short -q
```

The current smoke uses a representative FHIR-native Patient profile. Mapping
Modelable-only fields that are not legal base-resource child elements into FHIR
extensions remains a deferred conformance-hardening task.

**Examples:**

```bash
modelable compile ./models --target fhir-profile --out ./dist/fhir
```

---

### 5.18 `publish openmetadata` — Push metadata to OpenMetadata

```text
modelable publish openmetadata PATH [--url URL]
```

**Phase 3 — not yet implemented.**

Pushes the OpenMetadata export document to a live OpenMetadata instance.

---

### 5.19 `compile --target odcs` — Export Open Data Contract Standard documents

```text
modelable compile PATH --target odcs --out DIR
```

**Phase 4 — implemented as a compile target.**

Exports each model and projection version as an Open Data Contract Standard
(ODCS) v3.1.0 YAML document. The output preserves Modelable reference,
version, ownership, classification, PII, projection source, and field lineage
metadata under ODCS-native fields and `customProperties`.

**ODCS document structure:**

```yaml
apiVersion: v3.1.0
kind: DataContract
id: modelable://<domain>/<name>/v<version>
name: <domain>.<name>.v<version>
version: "<version>"
domain: <domain>
status: active
description:
  purpose: <domain or generated description>
schema:
  - name: <model_or_projection_name>
    logicalType: object
    physicalName: <model_or_projection_name>
    properties:
      - name: <field_name>
        logicalType: <field_type>
        required: true
        primaryKey: true
        pii: true
        classificationLevel: <classification>
        customProperties:
          modelable_type: <original Modelable type>
          modelable_lineage:
            - <source_ref.field>
```

**Options:**

| Flag | Required | Default | Description |
|:-----|:---------|:--------|:------------|
| `--target` | Yes | — | Must be `odcs` |
| `--out`, `-o` | No | `./dist/odcs` | Output directory |
| `--registry` | No | `.modelable/registry.db` | Registry index path |

**Examples:**

```bash
modelable compile ./models --target odcs --out ./dist/odcs
datacontract lint ./dist/odcs/customer.Customer.v1.odcs.yaml
```

---

### 5.20 `spec` — Track external specifications

```text
modelable spec add ID --kind <dbt|fhir|odcs> --source PATH --ref Domain.Model@version [--source-name NAME] [--path PATH]
modelable spec status [--path PATH] [--json] [--fail-on drifted,error]
modelable spec diff ID [--path PATH] [--json]
modelable spec sync [ID] [--path PATH] [--preview|--write]
```

Tracks external specification files in `.modelable/specs.yml`, compares their
current content to a bound Modelable model version, and reuses the same
compatibility rules as `diff`/`attach` to classify drift.

- `spec add` records the source path, source kind, target ref, optional source
  object name, and default update policy. The config is intended to be
  source-controlled.
- `spec status` reports `clean`, `drifted`, or `error` for each tracked source.
  `--json` is intended for CI and automation.
- `spec diff` lists field-level changes for one tracked source.
- `spec sync --preview` renders the proposed `.mdl` version update without
  writing; `--write` appends a new model version and records the source hash
  and change set in the `.attachments.json` sidecar.

This command tracks static local files only. Live catalog publishing,
scheduled polling, and remote source authentication remain deferred.

**Examples:**

```bash
modelable spec add customer-dbt --kind dbt --source ./dbt/schema.yml --source-name Customer --ref customer.Customer@1
modelable spec status --json --fail-on drifted,error
modelable spec sync customer-dbt --preview
modelable spec sync customer-dbt --write
```

---

## 6. AI Integration Details

The `update` and `chat` commands use the configured LLM provider. The model is configurable by command flag, environment variable, or workspace config; see section 12.

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
- **Authentication for registry commands:** Apicurio supports an explicit bearer
  token or `MODELABLE_APICURIO_TOKEN`. OAuth, mTLS, and OpenMetadata
  authentication mechanisms remain deferred.
- **Incremental compilation:** Whether `compile` should track which files changed and only recompile affected artifacts is deferred.
- **LSP parser mode:** The language server currently uses Lark Earley for correctness. Whether to migrate to LALR for lower-latency IDE responses is deferred.

**Resolved:**

- **Definition format:** Custom text IDL (`.mdl`), parsed with Lark (Earley). See [language-reference.md](language-reference.md).
- **AI model configuration:** LLM-backed commands use configurable model selection by flag, environment variable, workspace config, then CLI default. See section 12.

---

## 10. Additional Command Contracts

Sections 10.1 through 10.5 and 10.9 describe shipped local commands. Federated
registry management, dependent write-back queries, and signature verification
in sections 10.6 through 10.8 remain deferred.

The current `codegen` command reports all implemented formats in this repository,
including C#, Java, Python, Rust, Go, SQL DDL, dbt YAML, FHIR R4 profiles,
OpenMetadata JSON, and OpenLineage events. Additional future first-class
generated-language targets remain deferred until their dedicated emitters exist.

### 10.1 `inspect` — Inspect compiler-expanded definitions

```text
modelable inspect <Entity>@<version> --auto [--path PATH]
```

Displays the compiler-expanded auto projections (`db`, `request`, `reply`, `event`) for a given entity version. The output is a `.mdl`-like representation of the generated projection fields with full lineage annotations.

**Defined in:** [language-reference.md](language-reference.md) §3.7 and [architecture.md](architecture.md) §17.

### 10.2 `transform` — Emit and explain a target artifact

```text
modelable transform <Entity>@<version> --to <target> [--explain] [--path PATH]
```

Emits the target artifact (e.g., Avro schema, JSON Schema) for a single model version and optionally prints an explanation of mapping decisions.

When `--out` is supplied, the command writes the artifact to disk, writes a `.provenance.json` sidecar next to it, and prints the standard audit summary to stdout.

**Defined in:** [language-reference.md](language-reference.md) §5.1.

### 10.3 `suggest-projection` — AI-assisted projection proposal

```text
modelable suggest-projection --source <Domain.Model@version> --consumer <domain>
```

Proposes a projection definition with field derivations tailored to a consuming domain, using the AI integration described in §3.7.

The generated `.mdl` is validated before any file write.

When `--output` is supplied, the command writes the generated projection to disk, writes a `.provenance.json` sidecar next to it, and prints the standard audit summary to stdout.

**Defined in:** [language-reference.md](language-reference.md) §5.1.

### 10.4 `update` — Natural-language model or projection edit

```text
modelable update <Domain.Model@version> "<edit instruction>" --path PATH [--output FILE] [--preview] [--provider NAME] [--model MODEL] [--base-url URL]
```

Applies a natural-language change request to an existing model or projection version, rewrites the `.mdl` source, and validates the result before writing. By default it updates the source file for the referenced definition; `--output` can direct the result to an alternate path. `--preview` shows the rendered diff without writing changes.

When `MODELABLE_LLM_PROVIDER=ollama` or `MODELABLE_LLM_PROVIDER=anthropic`, or the matching `--provider` flag is set, and `--model <model>` is supplied, `update` asks the configured provider for a structured edit plan before applying the change. Without a configured provider, it falls back to the deterministic local editor path.
When the command writes a file, it prints a concise audit summary including the provider, model, validation status, written path, source ref, and repair count, and it writes a `.provenance.json` sidecar next to the updated `.mdl`.

**Defined in:** section 12.

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

**Defined in:** section 12.

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

See [compiler-reference.md](compiler-reference.md) §14.

### 10.7 `dependents` — List downstream consumers

```text
modelable dependents <Domain.Model@version>
```

Lists all downstream projections and consumer entries that depend on the given model version. Reads the `consumers/` tree across the workspace and peer mirrors.

See [compiler-reference.md](compiler-reference.md) §14.

### 10.8 `lineage verify` — Verify content signatures

```text
modelable lineage verify <REF>
```

Verifies that the content signature (SHA-256) of the given model or projection matches the cached mirror. Reports mismatches that indicate upstream drift.

See [compiler-reference.md](compiler-reference.md) §14.

### 10.9 `attach` — Attach a model version to an external dbt, FHIR, or ODCS source

```text
modelable attach <Domain.Model@version> --source <path> --source-format <dbt|fhir|odcs> [--source-name NAME] --path PATH [--output FILE] [--preview]
```

Imports fields from an external dbt `schema.yml` model, FHIR R4
`StructureDefinition`, or ODCS YAML contract and compares them against the
referenced model version using the same field-by-field comparison as `diff`.
`--source-name` selects a specific dbt model or ODCS schema object when the
source file declares more than one; it is ignored for FHIR sources, which
describe a single resource.

- If the imported fields match the referenced version, no changes are made.
- Otherwise, a new model version is appended to the `.mdl` source with fields derived
  from the external source (existing field annotations such as `@key`, `@pii`, and
  `@classification` are preserved by field name) and a `change_kind` of `additive` or
  `breaking` computed from the same rules as `diff` (removed fields, type changes, enum
  changes, identity changes, and optional-to-required narrowing are breaking; everything
  else is additive).

By default the command writes the source file for the referenced definition; `--output`
directs the result to an alternate path. `--preview` shows the rendered diff without
writing changes.

When the command writes a file, it appends a record to a `.attachments.json` sidecar
next to the `.mdl` file describing the source format, matched source name, source
content hash, the version transition, the computed change kind, and the field-level
changes, and it prints the standard audit summary.

See [external integrations](integrations.md) for dbt, FHIR, and ODCS mappings.

## 11. Language Server

`modelable lsp` exposes the same parser, transformer, semantic validator, and
workspace index used by CLI validation. Supported editor behavior includes
diagnostics, semantic highlighting, definition lookup, hover information,
workspace-aware completion, references, rename, formatting, code actions, and
workspace commands. The LSP is an authoring aid, never a second source of
validation rules.

Workspace indexing includes local `.mdl` files and available local mirrors.
Network peer fetch and write-back are not editor responsibilities and remain
deferred. Protocol behavior is covered by `pytest-lsp` tests and the VS Code
extension smoke suite.

## 12. AI-Assisted Authoring

`update` and `chat` may call a configured provider. `generate`, `describe`,
`transform`, and `suggest-projection` retain deterministic local paths. Provider
output is treated as an edit proposal: it must parse, pass semantic validation,
and satisfy compatibility and governance checks before Modelable writes it.

Provider configuration is explicit through command flags, environment variables,
or workspace configuration. Prompts must redact sensitive binding values, and
written changes include an auditable summary and provenance sidecar where the
command contract requires one.

## 13. Development Toolchain

The CLI uses Python 3.14+, `uv`, Hatchling, Click, Lark, Pydantic, Ruff, mypy,
and pytest. The committed `cli/uv.lock` is the reproducible dependency graph.
Run development commands from `cli/`:

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/ -v
```

The VS Code extension is built and tested from `vscode/` with `npm ci`,
`npm run build`, and `npm test`. See [maintainers](maintainers.md) for the full
repository gate and release policy.
