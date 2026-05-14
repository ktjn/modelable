# Design: Resolve System Spec Open Design Decisions

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** `docs/specs/modellable-system-spec.md`, `docs/specs/cli-spec.md`

---

## Context

Section 19 of the system spec listed five open design decisions deferred at initial authoring. These decisions affect the versioning model, identity key shape, projection source pinning, registry persistence, and plan execution strategy. Leaving them open creates ambiguity in downstream spec sections and makes it impossible to write accurate MVP acceptance tests. This design resolves all five.

---

## Decisions

### 1. Version Scheme — Integer + `changeKind`

Model versions remain integers (`version: 2`). When publishing a new version, authors must declare `changeKind: additive | breaking`. The planner enforces this declaration and uses it to evaluate projection compatibility.

**What `additive` means:** Only backward-compatible changes were made — new optional fields, added documentation, metadata updates, field deprecation marks. Existing projections pinning a lower version or using a version range remain valid without re-publication.

**What `breaking` means:** At least one incompatible change was made — field removed, field renamed, type changed, required field added, identity changed, nullability tightened. All projections referencing any version of this model must be re-validated. The planner rejects subscriptions that depend on an affected projection until the projection author explicitly republishes.

**Section changes:**
- Section 3.3 (Model Version): add `changeKind` to required properties and example YAML.
- Section 8.1 (Model Versioning): add a subsection defining `changeKind`, planner enforcement behavior, and the re-validation cascade rule.
- Section 19: move to resolved.

---

### 2. Composite Keys in MVP

`identity.key` accepts either a single field name (string) or an ordered list of field names. Both forms are valid in MVP.

```yaml
# single key
identity:
  key: customerId

# composite key
identity:
  key: [orderId, lineItemId]
```

The planner treats composite keys as a tuple. Idempotency keys in subscriptions must concatenate composite key fields in declaration order. Materialization adapters must map the composite key to a multi-column primary key or equivalent.

**Section changes:**
- Section 3.2 (Model): update `identity` description to mention both forms.
- Section 3.3 (Model Version): update example to show composite form alongside single.
- Section 19: move to resolved.

---

### 3. Version Ranges in Projections (Allowed in MVP)

Projections may declare a version range on source models:

```yaml
sources:
  - model: customer.Customer
    version: ">=2 <3"
```

**Resolution rules:**
- Ranges are resolved to the highest published version that satisfies the constraint at plan time.
- If the resolved version changes (a new compatible version is published), the projection is re-validated automatically against the new version. If validation passes, no author action is required.
- If the new version carries `changeKind: breaking` and falls within the declared range, the planner raises a validation error and blocks the subscription until the projection is updated.
- Exact version pins (`version: 2`) remain the default and are recommended for production projections that require maximum stability.

**Syntax:** Follows semantic range syntax (e.g., `>=2 <3`, `>=1.0`). Since model versions are integers, `<3` means "any version less than 3."

**Section changes:**
- Section 8.2 (Projection Versioning): add a subsection documenting resolution rules, re-validation triggers, and the breaking-version-in-range error.
- Section 19: move to resolved.

---

### 4. Registry Storage — File-First + SQLite Derived Index

Source of truth is the YAML files on disk, authored and version-controlled by developers. The compiler writes a derived `registry.db` (SQLite) alongside other generated artifacts.

**File layout (post-compile):**
```
.modellable/
  registry.db          # derived — rebuilt by `modellable compile`
  artifacts/
    customer/
      Customer.v2.json  # generated JSON Schema
      Customer.v2.md    # generated Markdown
      Customer.v2.ts    # generated TypeScript types
```

**registry.db schema** corresponds to the 15 logical entities in section 12. It is a build artifact — never edited directly. Deleting it and re-running `compile` must produce an identical result from the source files.

**Why SQLite:** Efficient querying for lineage traversal, consumer lookup, and compatibility checks across large graphs. Zero setup for local use. No server required.

**Section changes:**
- Section 12 (Storage Model): replace vague "relational or document" statement with the concrete file-first + SQLite approach; document the `.modellable/` output layout.
- Section 19: move to resolved.

**CLI change:**
- `cli-spec.md` — `compile` command: note that `registry.db` is written to `.modellable/` as part of the compile step.

---

### 5. Runtime Plans — Interpreted Plan Documents

The planner produces a **plan document** — a structured, inspectable data artifact (JSON or YAML) — not generated executable code. The runtime engine (Phase 5) will walk this document at execution time.

**Plan document contains:**
- Resolved source model versions.
- Field mapping table (target field → source field + transformation).
- Filter expressions (CEL AST or string).
- Join descriptors (type, left key, right key, cardinality).
- Aggregation descriptors.
- Adapter capability assertions used during planning.
- Validation timestamp and planner version.

Plans are serializable to disk, diffable in git, and human-readable for debugging. This is the correct artifact boundary between the Phase 1 compiler and the future Phase 5 runtime.

**Section changes:**
- Section 7.2 (Compiler and Planner): add a paragraph describing plan documents as the planner's primary output artifact, with the fields listed above.
- Section 19: move to resolved.

---

## Files to Modify

| File | Sections |
|---|---|
| `docs/specs/modellable-system-spec.md` | 2.6 (fix duplicate heading), 3.2, 3.3, 7.2, 8.1, 8.2, 12, 19 |
| `docs/specs/cli-spec.md` | `compile` command description |

## Files NOT Modified

- `samples/` — existing YAMLs already use integer versions and compatible identity structures; no changes needed.
- `docs/research/` — decisions do not affect research docs.
- `docs/external-tools-data-modelling.md` — unaffected.

---

## Verification

After implementing:

1. Read section 19 — all 5 decisions must appear under "resolved", none under "open".
2. Read section 3.3 — `changeKind` must appear in required properties and the example YAML.
3. Read section 8.1 — `additive` and `breaking` semantics must be defined with planner enforcement described.
4. Read section 8.2 — version range resolution rules and re-validation trigger must be present.
5. Read section 12 — file-first + SQLite approach and `.modellable/` layout must be documented.
6. Read section 7.2 — plan document description and field list must be present.
7. Read section 2 — confirm only one section is numbered 2.5 and a new 2.6 exists.
8. Read CLI spec `compile` command — `registry.db` output must be mentioned.
