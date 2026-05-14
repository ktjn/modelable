# System Spec Open Design Decisions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve all five open design decisions in `modellable-system-spec.md` by updating the relevant sections with precise, actionable language and moving each decision to the resolved list.

**Architecture:** Pure documentation edits across two Markdown files. No code is written. Each task targets one section or a closely related pair of sections, commits immediately, and leaves the file in a consistent state.

**Tech Stack:** Markdown, git.

**Design spec:** `docs/superpowers/specs/2026-05-14-system-spec-open-decisions-design.md`

---

## File Map

| File | What changes |
|---|---|
| `docs/specs/modellable-system-spec.md` | Sections 2.5/2.6 (fix duplicate), 3.2 (composite keys), 3.3 (changeKind), 7.2 (plan document), 8.1 (changeKind semantics), 8.2 (version range rules), 12 (storage model), 19 (move decisions to resolved) |
| `docs/specs/cli-spec.md` | Section 5.5 `compile` — note `registry.db` side-effect |

---

## Task 1: Fix duplicate section 2.5 heading

**Files:**
- Modify: `docs/specs/modellable-system-spec.md:54`

The file currently has two headings numbered `2.5`. The second one (`Compatibility Before Runtime`) should be `2.6`.

- [ ] **Step 1: Open the file and locate the duplicate**

Read lines 47–57 of `docs/specs/modellable-system-spec.md`. You will see:

```
### 2.5 Explicit Derivation
...
### 2.5 Compatibility Before Runtime
```

- [ ] **Step 2: Rename the second heading**

Replace:
```
### 2.5 Compatibility Before Runtime
```
With:
```
### 2.6 Compatibility Before Runtime
```

- [ ] **Step 3: Verify**

Read section 2 of the file. Confirm headings 2.1 through 2.6 each appear exactly once, in order, with no duplicates.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: fix duplicate section 2.5 heading — rename to 2.6"
```

---

## Task 2: Update section 3.2 — composite key identity

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 3.2

- [ ] **Step 1: Locate the identity property in section 3.2**

Find this line in the required properties list under `### 3.2 Model`:

```
- `identity`: Key definition for addressable records when applicable.
```

- [ ] **Step 2: Replace with expanded description**

Replace that single line with:

```
- `identity`: Key definition for addressable records when applicable. The `key` field accepts either a single field name (string) or an ordered list of field names for composite keys.
```

- [ ] **Step 3: Verify**

Read section 3.2. Confirm the `identity` bullet mentions both single and composite key forms.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: document composite key support in section 3.2 identity"
```

---

## Task 3: Update section 3.3 — add `changeKind` to model version

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 3.3

- [ ] **Step 1: Locate the required properties list in section 3.3**

Find this block under `### 3.3 Model Version`:

```
Required properties:

- `version`: Integer or semantic version.
- `status`: `draft`, `published`, `deprecated`, or `retired`.
```

- [ ] **Step 2: Replace the properties list**

Replace those two bullet lines with:

```
Required properties:

- `version`: Integer version number. Must be greater than the previous published version for the same model.
- `changeKind`: `additive` or `breaking`. Required when `status` is `published`. Omit for `draft`. See section 8.1 for enforcement rules.
- `status`: `draft`, `published`, `deprecated`, or `retired`.
```

- [ ] **Step 3: Update the example YAML**

Find the example block in section 3.3:

```yaml
domain: customer
model: Customer
version: 2
status: published
```

Replace with:

```yaml
domain: customer
model: Customer
version: 2
changeKind: additive
status: published
```

Also add a composite key example immediately after the single-key example block. Find:

```yaml
identity:
  key: customerId
```

Replace with:

```yaml
# single key
identity:
  key: customerId

# composite key (order line item example)
# identity:
#   key: [orderId, lineItemId]
```

- [ ] **Step 4: Verify**

Read section 3.3. Confirm `changeKind` appears in required properties with its allowed values and a cross-reference to 8.1. Confirm the example YAML contains `changeKind: additive`. Confirm the composite key comment example is present.

- [ ] **Step 5: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: add changeKind and composite key examples to section 3.3"
```

---

## Task 4: Update section 7.2 — plan document description

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 7.2

- [ ] **Step 1: Locate the end of the planner responsibilities list in section 7.2**

Find this block under `### 7.2 Compiler and Planner`:

```
Planner responsibilities:

- Resolve source references.
- Validate field mappings.
- Validate expression types.
- Validate access permissions.
- Validate adapter capabilities.
- Determine whether execution is pushdown, runtime-based, or unsupported.
- Produce executable projection plans.
```

- [ ] **Step 2: Add plan document description after the list**

After the bullet list (after `- Produce executable projection plans.`), insert the following paragraph and code block:

```
The planner's primary output is a **plan document** — a structured, serialisable artifact (JSON) that the runtime engine (Phase 5) interprets at execution time. Plan documents are not generated executable code; they are data that describes how to execute a projection. They are human-readable, diffable in git, and inspectable for debugging.

A plan document contains:

- Resolved source model versions (exact version numbers, not ranges).
- Field mapping table: each target field mapped to its source field and optional transformation expression.
- Filter expression in CEL string form.
- Join descriptors: type (`left`, `inner`), left key, right key, and declared cardinality.
- Aggregation descriptors: group-by fields and aggregate function per output field.
- Adapter capability assertions evaluated during planning.
- Planner metadata: validation timestamp and planner version.

Plan documents are written to `.modellable/plans/<domain>.<Projection>.v<version>.plan.json` by the `compile` command.
```

- [ ] **Step 3: Verify**

Read section 7.2. Confirm the plan document paragraph and its field list appear after the planner responsibilities bullet list.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: describe plan document output format in section 7.2"
```

---

## Task 5: Update section 8.1 — `changeKind` semantics and planner enforcement

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 8.1

- [ ] **Step 1: Locate the end of section 8.1**

Find the end of the `### 8.1 Model Versioning` section — the last bullet in the "Potentially incompatible changes" list:

```
- Change validation constraints in a stricter way.
```

- [ ] **Step 2: Append changeKind subsection after the incompatible changes list**

Insert the following immediately after that last bullet:

```

### 8.1.1 `changeKind` Declaration and Enforcement

When publishing a new model version (`status: published`), authors must declare `changeKind`:

- `additive` — only backward-compatible changes were made. The set of compatible changes is defined in section 8.1 above. Existing projections that pin an earlier version or use a compatible version range remain valid without re-publication.
- `breaking` — at least one incompatible change was made. The set of potentially incompatible changes is defined in section 8.1 above.

**Planner enforcement for `breaking` versions:**

When a new version with `changeKind: breaking` is published, the planner marks all projections that reference any version of that model as requiring re-validation. Subscriptions backed by an affected projection are blocked from planning until the projection author explicitly re-publishes a new projection version that references a valid source version. The registry must expose a `listAffectedProjections(domain, model, breakingVersion)` query to support this workflow.

**Planner enforcement for `additive` versions:**

Projections with exact version pins are unaffected. Projections using version ranges are automatically re-validated against the new version (see section 8.2). If re-validation passes, no author action is required.

**Draft versions:** `changeKind` is not required and is ignored for `draft` status versions.
```

- [ ] **Step 3: Verify**

Read section 8.1. Confirm the `changeKind` subsection appears, defines both values, and describes both the breaking and additive enforcement behavior.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: add changeKind semantics and planner enforcement rules to section 8.1"
```

---

## Task 6: Update section 8.2 — version range resolution rules

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 8.2

- [ ] **Step 1: Locate the version range example in section 8.2**

Find this block under `### 8.2 Projection Versioning`:

```yaml
sources:
  - model: customer.Customer
    version: ">=2 <3"
```

And the sentence immediately after it:

```
Version ranges must be resolved to concrete versions at planning time.
```

- [ ] **Step 2: Replace with expanded version range rules**

Replace the sentence `Version ranges must be resolved to concrete versions at planning time.` with:

```
**Version range resolution rules:**

- Ranges are resolved to the **highest published version** that satisfies the constraint at plan time.
- Since model versions are integers, range syntax uses integer comparisons: `>=2 <3` means "version 2 only", `>=2` means "version 2 or higher".
- Exact version pins (`version: 2`) are resolved immediately and are not affected by future publications. They are recommended for production projections that require maximum stability.
- When a new compatible (`changeKind: additive`) version is published within the declared range, the planner **automatically re-validates** the projection against the new resolved version. If re-validation passes, no projection author action is required.
- When a new version with `changeKind: breaking` is published and falls within the declared range, the planner raises a validation error and blocks the subscription. The projection author must update the version range and re-publish.
- The resolved concrete version is recorded in the plan document (see section 7.2). Re-planning uses the latest resolved version, not the version that was resolved at the last plan time.
```

- [ ] **Step 3: Verify**

Read section 8.2. Confirm the resolution rules are present, cover both additive and breaking cases, and clarify the integer comparison semantics.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: add version range resolution rules to section 8.2"
```

---

## Task 7: Update section 12 — file-first + SQLite storage model

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 12

- [ ] **Step 1: Locate section 12**

Find `## 12. Storage Model for Registry` and read the full section. It currently reads:

```
The registry should be persisted using relational tables or equivalent collections.

Minimum logical entities:
...
Published definitions should also be stored as complete immutable documents to preserve exact historical contracts.
```

- [ ] **Step 2: Replace section 12 content**

Replace the entire body of section 12 (everything from "The registry should be persisted..." through "...preserve exact historical contracts.") with:

```
The registry uses a **file-first, SQLite-indexed** storage model.

**Source of truth: YAML files on disk.** Authors write and version-control YAML definition files. The registry never modifies these files. All definitions live in source control alongside application code.

**Derived index: SQLite.** The `modellable compile` command reads all YAML files and writes a derived `registry.db` (SQLite) file to the `.modellable/` output directory. The database is a build artifact — never edited directly. Deleting it and re-running `compile` must produce an identical result.

SQLite is used because it provides efficient relational queries for lineage traversal, consumer lookup, and compatibility checks without requiring a server or any setup for local use.

**Output layout (post-compile):**

```
.modellable/
  registry.db                          # derived — rebuilt by `modellable compile`
  plans/
    customer.Customer.v2.plan.json     # interpreted plan document
  artifacts/
    customer/
      Customer.v2.json                 # generated JSON Schema
      Customer.v2.md                   # generated Markdown
      Customer.v2.ts                   # generated TypeScript types
```

**Minimum logical entities in `registry.db`:**

- `domains`
- `models`
- `model_versions`
- `fields`
- `projections`
- `projection_versions`
- `projection_sources`
- `projection_fields`
- `field_mappings`
- `aggregations`
- `subscriptions`
- `adapter_bindings`
- `compatibility_reports`
- `lineage_edges`
- `access_policies`

Published definitions are also stored as complete immutable YAML documents within the source files to preserve exact historical contracts. The SQLite index is derived from these documents, not the other way around.
```

- [ ] **Step 3: Verify**

Read section 12. Confirm it describes file-first + SQLite, the `.modellable/` output layout, and the entity list. Confirm the SQLite database is described as a derived artifact.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: replace vague storage model with file-first + SQLite spec in section 12"
```

---

## Task 8: Update section 19 — move all five decisions to resolved

**Files:**
- Modify: `docs/specs/modellable-system-spec.md` — section 19

- [ ] **Step 1: Locate section 19**

Find `## 19. Open Design Decisions`. It currently reads:

```
The following have been resolved:

- **Definition DSL:** YAML-first, parsed with `ruamel.yaml`.
- **Expression language for computed fields:** CEL (Common Expression Language). Deterministic, non-Turing-complete, sandboxable.
- **Internal parser models:** `pydantic`. Not exposed as the external contract format.
- **First generated artifact:** JSON Schema 2020-12.
- **TypeScript generation:** Delegated to `json-schema-to-typescript`. No custom generator.

The following remain open:

- Whether versions are integers, semantic versions, or both.
- Whether model identity supports composite keys in MVP.
- Whether projections can reference compatible version ranges in MVP.
- Whether registry state is stored relationally, document-first, or both.
- Whether runtime plans are interpreted or compiled into generated code.
```

- [ ] **Step 2: Replace section 19 body**

Replace the entire body with:

```
All design decisions have been resolved.

**Resolved:**

- **Definition DSL:** YAML-first, parsed with `ruamel.yaml`.
- **Expression language for computed fields:** CEL (Common Expression Language). Deterministic, non-Turing-complete, sandboxable.
- **Internal parser models:** `pydantic`. Not exposed as the external contract format.
- **First generated artifact:** JSON Schema 2020-12.
- **TypeScript generation:** Delegated to `json-schema-to-typescript`. No custom generator.
- **Version scheme:** Integer versions with a required `changeKind: additive | breaking` declaration on publish. See section 8.1.
- **Composite keys:** Supported in MVP. `identity.key` accepts a string (single field) or a list (composite). See section 3.3.
- **Version ranges in projections:** Allowed in MVP. The planner resolves to the highest satisfying published version at plan time. See section 8.2.
- **Registry storage:** File-first (YAML source of truth) with a SQLite derived index written by `compile`. See section 12.
- **Runtime plan execution:** Interpreted plan documents (structured JSON artifacts). Not generated code. See section 7.2.
```

- [ ] **Step 3: Verify**

Read section 19. Confirm all 10 decisions (5 original + 5 new) appear under "Resolved" and the "open" list is gone.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/modellable-system-spec.md
git commit -m "docs: resolve all five open design decisions in section 19"
```

---

## Task 9: Update CLI spec — `compile` command registry.db output

**Files:**
- Modify: `docs/specs/cli-spec.md` — section 5.5

- [ ] **Step 1: Locate the compile command description**

Find `### 5.5 \`compile\` — Compile definitions to artifact formats` (around line 170). Read the description paragraph:

```
Compiles model and projection definitions to a target artifact format. `SOURCE` can be a path to a YAML file or directory, or a model reference (`domain.ModelName.vVersion`).
```

- [ ] **Step 2: Replace the description paragraph**

Replace that paragraph with:

```
Compiles model and projection definitions to a target artifact format. `SOURCE` can be a path to a YAML file or directory, or a model reference (`domain.ModelName.vVersion`).

In addition to the requested artifact format, `compile` always writes a `registry.db` SQLite index and plan documents to `.modellable/` in the current directory. These derived files are build artifacts — not source files — and should be added to `.gitignore`.
```

- [ ] **Step 3: Verify**

Read section 5.5 of `cli-spec.md`. Confirm the paragraph about `registry.db` and `.modellable/` is present.

- [ ] **Step 4: Commit**

```bash
git add docs/specs/cli-spec.md
git commit -m "docs: note registry.db side-effect of compile command in cli-spec"
```

---

## Verification Checklist

Run these checks after all tasks complete:

- [ ] `grep -n "### 2\." docs/specs/modellable-system-spec.md` — output must show 2.1 through 2.6 with no duplicate numbers.
- [ ] `grep -n "changeKind" docs/specs/modellable-system-spec.md` — must appear in sections 3.3, 8.1, 8.1.1, 8.2, and 19.
- [ ] `grep -n "composite" docs/specs/modellable-system-spec.md` — must appear in sections 3.2, 3.3, and 19.
- [ ] `grep -n "registry.db" docs/specs/modellable-system-spec.md docs/specs/cli-spec.md` — must appear in sections 7.2, 12, and cli-spec 5.5.
- [ ] `grep -n "remain open" docs/specs/modellable-system-spec.md` — must return no results (section 19 open list is gone).
- [ ] `grep -n "plan document" docs/specs/modellable-system-spec.md` — must appear in sections 7.2 and 8.2.
- [ ] `git log --oneline -9` — must show 9 commits (one per task + the design doc commit).
