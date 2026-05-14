# Modellable CLI Specification

## 1. Purpose

The Modellable CLI (`modellable`) is the primary developer interface for working with Modellable definition files locally. It provides commands for validating, resolving, inspecting, compiling, and exporting domain-owned model and projection definitions.

The CLI is designed as a phased tool: early phases focus on local authoring and compilation; later phases integrate with external registries and governance catalogs.

## 2. Delivery Phases

| Phase | Scope | Status |
|:------|:------|:-------|
| 1 | Local modelling compiler (validate, resolve, lineage, diff, compile, docs) | MVP |
| 2 | Artifact registry integration (Apicurio Registry) | Deferred |
| 3 | Catalog / governance integration (OpenMetadata) | Deferred |
| 4 | Contract interchange (Open Data Contract Standard) | Deferred |

## 3. Installation and Runtime

- **Language:** Python 3.11+
- **Framework:** Click
- **Entry point:** `modellable` (installed via `pip install -e cli/`)
- **Build system:** Hatchling (`pyproject.toml`)
- **Required dependencies:** `click>=8.1`, `pyyaml>=6.0`, `ruamel.yaml>=0.18`, `anthropic>=0.40`, `rich>=13.0`, `jsonschema>=4.23`, `referencing>=0.35`

AI-powered commands (`describe`, `generate`) additionally require the `ANTHROPIC_API_KEY` environment variable.

## 4. File Format

Definition files use multi-document YAML (documents separated by `---`). The CLI infers each document's type from its top-level keys:

| Top-level keys present | Inferred document type |
|:-----------------------|:----------------------|
| `scenario` | Scenario metadata |
| `domain` only (no `model`, `projection`, `binding`) | Domain definition |
| `domain` + `model` | Model definition |
| `domain` + `projection` | Projection definition |
| `binding` | Adapter binding |

Model references use the format `domain.ModelName.vVersion` (e.g., `customer.Customer.v1`).

## 5. Commands

### 5.1 `validate` — Validate definition files

```text
modellable validate [PATH] [--strict]
```

Validates Modellable YAML definitions at `PATH` (file or directory). Defaults to the current directory.

**Options:**

| Flag | Description |
|:-----|:------------|
| `--strict` | Treat warnings as errors; exits non-zero if any warning is present |

**Checks performed:**

- Domains have `owner` and `description`
- Models have valid `kind`, `version`, `status`, and `fields`
- Field types are from the supported type list
- Field classifications are valid values
- Projections have at least one source and fields with `from` or `expression`
- Materialisation strategies are valid
- Bindings have `adapter` and `role`

**Exit codes:** `0` on success (or warnings-only without `--strict`); `1` on validation errors.

**Examples:**

```bash
modellable validate samples/scenarios/01-ecommerce-data-warehouse.yaml
modellable validate ./my-project/
modellable validate ./my-project/ --strict
```

---

### 5.2 `resolve` — Look up a model or projection by reference

```text
modellable resolve REF [--path PATH]
```

Resolves a model or projection by its fully-qualified reference and prints the raw YAML document.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF` | Model reference in the form `domain.ModelName.vVersion` |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | `.` | Directory to search for YAML definitions |

**Examples:**

```bash
modellable resolve customer.Customer.v1
modellable resolve billing.BillingCustomer.v1 --path ./models
```

---

### 5.3 `lineage` — Show field-level lineage

```text
modellable lineage REF [--path PATH]
```

Shows field-level lineage for a model or projection.

- **For projections:** Shows which source field each output field derives from, including fully-qualified source references (`domain.Model.vVersion.field`) and computed expressions.
- **For models:** Shows each field with its type and classification, labelled as `(canonical)`.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF` | Model or projection reference in the form `domain.ModelName.vVersion` |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | `.` | Directory to search for YAML definitions |

**Examples:**

```bash
modellable lineage billing.BillingCustomer.v1
modellable lineage customer.Customer.v2
```

---

### 5.4 `diff` — Compare two model versions

```text
modellable diff REF_A REF_B [--path PATH]
```

Compares two model or projection versions field by field and reports additions, removals, and type changes. Intended to support compatibility review before publishing a new version.

**Arguments:**

| Argument | Description |
|:---------|:------------|
| `REF_A` | First model reference (`domain.ModelName.vVersion`) |
| `REF_B` | Second model reference (`domain.ModelName.vVersion`) |

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--path`, `-p` | `.` | Directory to search for YAML definitions |

**Examples:**

```bash
modellable diff customer.Customer.v1 customer.Customer.v2
```

---

### 5.5 `compile` — Compile definitions to artifact formats

```text
modellable compile SOURCE --target TARGET [--out DIR] [--path PATH]
```

Compiles model and projection definitions to a target artifact format. `SOURCE` can be a path to a YAML file or directory, or a model reference (`domain.ModelName.vVersion`).

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
modellable compile ./models --target json-schema --out ./dist/jsonschema
modellable compile customer.Customer.v1 --target json-schema
modellable compile customer.Customer.v1 --target typescript
modellable compile ./models --target markdown --out ./dist/docs
```

---

### 5.6 `docs` — Generate Markdown documentation

```text
modellable docs SOURCE [--out DIR]
```

Generates Markdown documentation for all definitions in a YAML file or directory. This is a convenience wrapper around `compile --target markdown`.

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--out`, `-o` | `./dist/docs` | Output directory |

**Examples:**

```bash
modellable docs ./models --out ./dist/docs
```

---

### 5.7 `scenario` — Browse and load sample scenarios

```text
modellable scenario list
modellable scenario show SCENARIO_ID
modellable scenario load SCENARIO_ID [--output-dir DIR]
```

Manages the bundled sample scenarios shipped with the CLI.

**Subcommands:**

| Subcommand | Description |
|:-----------|:------------|
| `list` | Print all available scenario IDs and titles |
| `show SCENARIO_ID` | Display the scenario YAML with syntax highlighting |
| `load SCENARIO_ID` | Copy the scenario YAML into a working directory |

**Options for `load`:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--output-dir`, `-d` | `.` | Destination directory for the copied file |

**Bundled scenario IDs:**

| ID | Title |
|:---|:------|
| `ecommerce-data-warehouse` | E-Commerce Data Warehouse |
| `realtime-fraud-detection` | Real-Time Fraud Detection |
| `order-saga-microservices` | Order Saga Microservices |
| `credit-risk-feature-store` | Credit Risk Feature Store |
| `partner-marketplace-api` | Partner Marketplace API |
| `gdpr-compliance-audit` | GDPR Compliance Audit |

**Examples:**

```bash
modellable scenario list
modellable scenario show ecommerce-data-warehouse
modellable scenario load credit-risk-feature-store --output-dir ./my-project
```

---

### 5.8 `create` — Create definitions interactively

```text
modellable create domain [--output-dir DIR]
modellable create model  [--output-dir DIR]
modellable create projection [--output-dir DIR]
```

Walks through an interactive prompt sequence and writes a YAML definition file.

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
modellable create domain --output-dir ./my-project
modellable create model --output-dir ./my-project
modellable create projection --output-dir ./my-project
```

---

### 5.9 `describe` — Explain definitions with AI

```text
modellable describe PATH
```

Requires `ANTHROPIC_API_KEY`.

Reads a YAML definition file and uses Claude to explain it in plain English, covering:

- What problem the scenario solves
- Which domains are involved and what they own
- What each projection does and why it is designed that way
- Notable design decisions (e.g., why PIT joins, why specific materialisation strategies)

The Modellable DSL specification is sent as a cached system prompt. Repeated calls within a session reuse the cached context and respond faster.

**Examples:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
modellable describe samples/scenarios/03-order-saga-microservices.yaml
modellable describe ./my-project/my-definitions.yaml
```

---

### 5.10 `generate` — Generate definitions with AI

```text
modellable generate [--platform PLATFORM] [--suggest-platform] [--context FILE] [--output FILE]
```

Requires `ANTHROPIC_API_KEY`.

Generates Modellable YAML definitions from a natural language description using Claude. When `--output` is provided, the result is also automatically validated.

**Options:**

| Flag | Description |
|:-----|:------------|
| `--platform PLATFORM` | Target platform type (e.g., `data-warehouse`, `high-performance-service`, `event-driven-microservices`) |
| `--suggest-platform` | Ask Claude to recommend a platform type before generating |
| `--context FILE` | Existing definition file to use as context for generation |
| `--output FILE` | Write output to a file and auto-validate (default: print to stdout) |

**Examples:**

```bash
modellable generate
modellable generate --platform data-warehouse
modellable generate --suggest-platform
modellable generate --platform high-performance-service --output my-fraud-signals.yaml
modellable generate --context existing-domains.yaml --platform event-driven-microservices
```

---

### 5.11 `codegen` — Explore artifact formats and type mappings

```text
modellable codegen formats
modellable codegen types [--format FORMAT]
```

Displays supported artifact output formats and the type mapping from Modellable field types to each target format.

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
modellable publish apicurio PATH [--url URL] [--group GROUP]
```

**Phase 2 — not yet implemented.**

Pushes compiled JSON Schema artifacts to an Apicurio Schema Registry instance. Artifact IDs follow the convention `domain.Name.vVersion`.

**Options:**

| Flag | Default | Description |
|:-----|:--------|:------------|
| `--url` | — | Apicurio Registry base URL |
| `--group` | `modellable` | Artifact group ID |

**Intended workflow:**

```bash
modellable compile ./models --target json-schema --out ./dist/jsonschema
modellable publish apicurio ./dist/jsonschema --url http://localhost:8080
```

---

### 5.13 `pull apicurio` — Pull schema artifacts

```text
modellable pull apicurio REF [--url URL] [--out DIR]
```

**Phase 2 — not yet implemented.**

Pulls a specific schema artifact from an Apicurio Registry instance by model reference.

---

### 5.14 `export openmetadata` — Export catalog metadata

```text
modellable export openmetadata [PATH] --out FILE
```

**Phase 3 — implemented (export only; push requires `publish openmetadata`).**

Exports domain, model, and projection metadata to a JSON file suitable for OpenMetadata catalog ingestion.

**Modellable → OpenMetadata mapping:**

| Modellable concept | OpenMetadata concept |
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
modellable export openmetadata ./models --out ./dist/openmetadata.json
modellable publish openmetadata ./dist/openmetadata.json
```

---

### 5.15 `publish openmetadata` — Push metadata to OpenMetadata

```text
modellable publish openmetadata PATH [--url URL]
```

**Phase 3 — not yet implemented.**

Pushes the OpenMetadata export document to a live OpenMetadata instance.

---

### 5.16 `export odcs` — Export an Open Data Contract Standard document

```text
modellable export odcs REF --out FILE [--path PATH]
```

**Phase 4 — implemented (structural export).**

Exports a single model or projection as an Open Data Contract Standard (ODCS) v1.0.0 YAML document. The output can be linted with `datacontract lint`.

**ODCS document structure:**

```yaml
dataContractSpecification: "1.0.0"
id: "modellable://<domain>/<name>/v<version>"
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
modellable export odcs customer.Customer.v1 --out ./dist/customer.contract.yaml
datacontract lint ./dist/customer.contract.yaml
```

---

## 6. AI Integration Details

The `describe` and `generate` commands use the Claude API (model: `claude-opus-4-7`).

- The full Modellable DSL specification is sent as a cached system prompt.
- Repeated calls within a session reuse the cached prompt and respond faster.
- Generated YAML is automatically validated when `--output` is supplied to `generate`.
- Complex scenario generation may take 10–30 seconds.

## 7. Quick-Start Workflow

```bash
# 1. Start from the closest sample scenario
modellable scenario load realtime-fraud-detection --output-dir ./fraud-signals

# 2. Validate it
modellable validate ./fraud-signals/

# 3. Understand what it does
modellable describe ./fraud-signals/02-realtime-fraud-detection.yaml

# 4. Extend it with AI
modellable generate \
  --platform high-performance-service \
  --context ./fraud-signals/02-realtime-fraud-detection.yaml \
  --output ./fraud-signals/03-new-account-signals.yaml

# 5. Validate the new file
modellable validate ./fraud-signals/03-new-account-signals.yaml

# 6. Inspect lineage
modellable lineage billing.BillingCustomer.v1 --path ./fraud-signals

# 7. Compare versions
modellable diff customer.Customer.v1 customer.Customer.v2 --path ./fraud-signals

# 8. Compile to JSON Schema and TypeScript
modellable compile ./fraud-signals --target json-schema --out ./dist/jsonschema
modellable compile ./fraud-signals --target typescript --out ./dist/types

# 9. Generate documentation
modellable docs ./fraud-signals --out ./dist/docs
```

## 8. Output and Exit Codes

- All human-readable output uses `rich` for colored, formatted terminal output.
- Exit code `0` indicates success.
- Exit code `1` indicates a validation error, resolution failure, or unrecoverable CLI error.
- Commands that produce no input (e.g., no YAML files found) exit `0` with a warning message.

## 9. Open Design Decisions

- **Schema validation backend:** The current validator performs structural checks. Whether to adopt JSON Schema Draft 2020-12 as the authoritative validation schema for definition files is an open decision.
- **Plugin architecture for compilers:** The compile targets are currently hard-coded. A plugin registry for third-party targets is deferred.
- **Authentication for registry commands:** Apicurio and OpenMetadata authentication mechanisms (API keys, OAuth, mTLS) are not yet specified.
- **Incremental compilation:** Whether `compile` should track which files changed and only recompile affected artifacts is deferred.
- **Version pinning for AI model:** The `describe`/`generate` commands currently hard-code `claude-opus-4-7`. Whether to make this configurable or always use the latest capable model is an open decision.
