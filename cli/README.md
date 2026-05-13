# Modellable CLI

A command-line tool for creating, validating, and describing Modellable definitions. Includes AI-powered commands for generating definitions from natural language and explaining existing YAML in plain English.

## Installation

```bash
pip install -e cli/
```

Requires Python 3.11+. Dependencies: `click`, `pyyaml`, `anthropic`, `rich`.

## Commands

### `modellable scenario` — Browse sample scenarios

```bash
# List all bundled scenarios
modellable scenario list

# Show a scenario with syntax highlighting
modellable scenario show ecommerce-data-warehouse
modellable scenario show realtime-fraud-detection

# Copy a scenario into a working directory
modellable scenario load credit-risk-feature-store --output-dir ./my-project

# Available scenario IDs:
#   ecommerce-data-warehouse
#   realtime-fraud-detection
#   order-saga-microservices
#   credit-risk-feature-store
#   partner-marketplace-api
#   gdpr-compliance-audit
```

### `modellable validate` — Validate definitions

```bash
# Validate a single file
modellable validate samples/scenarios/01-ecommerce-data-warehouse.yaml

# Validate all YAML files in a directory
modellable validate ./my-project/

# Treat warnings as errors (strict mode)
modellable validate ./my-project/ --strict
```

Checks performed:
- Domains have `owner` and `description`
- Models have valid `kind`, `version`, `status`, and `fields`
- Field types are from the supported type list
- Classifications are valid values
- Projections have at least one source and fields with `from` or `expression`
- Materialisation strategies are valid
- Bindings have `adapter` and `role`

### `modellable create` — Create definitions interactively

```bash
# Create a domain definition
modellable create domain --output-dir ./my-project

# Create a model definition
modellable create model --output-dir ./my-project

# Create a projection definition
modellable create projection --output-dir ./my-project
```

Each command walks through an interactive prompt sequence and writes a YAML file.

### `modellable describe` — Explain definitions with AI

Requires `ANTHROPIC_API_KEY` environment variable.

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Explain what a YAML file does in plain English
modellable describe samples/scenarios/03-order-saga-microservices.yaml
modellable describe ./my-project/my-definitions.yaml
```

Claude reads the YAML and explains:
- What problem the scenario solves
- Which domains are involved and what they own
- What each projection does and why it's designed that way
- Notable design decisions (e.g. why PIT joins, why specific materialisation strategies)

### `modellable generate` — Generate definitions with AI

Requires `ANTHROPIC_API_KEY` environment variable.

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Interactive generation (prompts for description)
modellable generate

# Specify a target platform type
modellable generate --platform data-warehouse

# Ask AI to recommend a platform type first
modellable generate --suggest-platform

# Save output to a file (also auto-validates)
modellable generate --platform high-performance-service --output my-fraud-signals.yaml

# Build on existing context
modellable generate --context existing-domains.yaml --platform event-driven-microservices
```

When run without `--output`, the generated YAML is printed to stdout with syntax highlighting. Use `--output` to save to a file and automatically validate the result.

## Workflow Example

```bash
# 1. Start from the closest sample scenario
modellable scenario load realtime-fraud-detection --output-dir ./fraud-signals

# 2. Validate the sample
modellable validate ./fraud-signals/

# 3. Understand what it does
modellable describe ./fraud-signals/02-realtime-fraud-detection.yaml

# 4. Extend it with a new projection using AI
modellable generate \
  --platform high-performance-service \
  --context ./fraud-signals/02-realtime-fraud-detection.yaml \
  --output ./fraud-signals/03-new-account-signals.yaml

# 5. Validate the new file
modellable validate ./fraud-signals/03-new-account-signals.yaml

# 6. Create a new domain by hand
modellable create domain --output-dir ./fraud-signals
```

## LLM Details

The `describe` and `generate` commands use **Claude claude-opus-4-7** (the most capable Claude model). The Modellable DSL specification is sent as a cached system prompt, so repeated calls in a session reuse the cached context and respond faster.

Usage notes:
- Set `ANTHROPIC_API_KEY` before running LLM commands
- Generated YAML is automatically validated when using `--output`
- The `--suggest-platform` flag adds a recommendation step before generation
- Complex scenarios may take 10–30 seconds for generation

## File Format Reference

Scenario files use multi-document YAML (documents separated by `---`). The CLI detects each document's type from its top-level keys:

| Key present | Document type |
|:------------|:-------------|
| `scenario` | Scenario metadata |
| `domain` (no `model`/`projection`/`binding`) | Domain definition |
| `domain` + `model` | Model definition |
| `domain` + `projection` | Projection definition |
| `binding` | Adapter binding |
