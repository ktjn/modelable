# Wire-Format Contract First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define and pin a "byte-exact and reproducible across compiler versions" completion bar for the Rust and Protobuf emitters — gap 5 of Scalable's feature-gaps request. Unlike the other gaps, this one adds no grammar, IR, or emitter behavior: it documents the encoding rules the emitters already follow, and adds a golden-fixture regression suite that fails CI the moment generated output drifts from a committed baseline.

**Architecture:** Per
[docs/superpowers/specs/2026-07-07-modelable-feature-gaps-response-design.md](../specs/2026-07-07-modelable-feature-gaps-response-design.md)
section 8, this gap's capability set (descriptor sets, richer index metadata, protobuf compatibility validation) is already covered by the separate, larger, already-in-flight
[2026-07-04-scalable-protobuf-grpc-support-design.md](../specs/2026-07-04-scalable-protobuf-grpc-support-design.md)
(confirmed still open per `ROADMAP.md`: "deleted-field reservations, descriptor sets, richer index metadata, Scalable registration fixtures, and protobuf/gRPC compatibility validation remain follow-up work" — none of that is in scope here). What section 8 actually asks this gap to add is narrower and self-contained: a `docs/wire-format-contract.md` and a golden-fixture regression suite. This plan documents only encoding rules verified against the current `rust.py`/`protobuf.py` source (not aspirational ones) and pins them with a real regression test.

**Tech Stack:** Python 3.14, pytest, existing Rust/Protobuf emitters (no changes to either).

---

## Scope And Version Boundary

This gap has no dependency on and no dependents among the other seven
gaps — it documents and pins existing behavior.

Out of scope for this first slice:

- Descriptor sets, richer index metadata, `validate-compat`, deleted-field
  reservations, Scalable registration fixtures — all tracked separately
  under the protobuf/gRPC initiative's own design doc, not this gap.
- Extending the golden-fixture mechanism to any emitter besides Rust and
  Protobuf — section 8 names only those two.
- Any change to emitter *behavior*. If a documented rule turns out to be
  wrong once verified against the code, the doc is corrected to match the
  code, not the other way around — this slice pins reality, it doesn't
  redesign it.

## File Structure

- Create `docs/wire-format-contract.md`.
- Create `cli/tests/fixtures/wire_golden/wire_golden.mdl`.
- Create `cli/tests/fixtures/wire_golden/golden/rust/platform_widget_v1.rs` and
  `cli/tests/fixtures/wire_golden/golden/protobuf/platform_widget_v1.proto`
  (and any additional per-artifact golden files the fixture emits, e.g. a
  companion enum file).
- Create `cli/tests/test_wire_golden.py`.
- Modify `ROADMAP.md`, `CHANGELOG.md`.

## Task 1: Verify The Actual Encoding Rules

**Files:** none (research only — this task's output feeds Task 2 and 3)

- [ ] **Step 1: Confirm field-ordering and field-numbering rules**

Re-read `cli/src/modelable/emitters/protobuf.py`'s `_emit_model_version`
(field numbers: `enumerate(version.fields, start=1)`, i.e. 1-indexed,
declaration order) and `cli/src/modelable/emitters/rust.py`'s struct
field emission (`enumerate(version.fields)`, declaration order, no
explicit wire-position semantics since Rust output targets
`serde`-derived JSON, not a positional binary codec).

- [ ] **Step 2: Confirm per-type encoding for both targets**

Cross-check every `FieldType` variant's mapping in both files:
`PrimitiveType` (all kinds, note `u128`/`i128`'s `bytes`+`fixed_length:
16` special case in Protobuf vs. native `u128`/`i128` in Rust),
`DecimalType` (`string` in both — no numeric canonicalization of the
value itself; only the *type* is `string`, `.mdl`-authored decimal
literals are not currently emitted into generated code at all),
`FixedBinaryType` (`[u8; N]` in Rust vs. `bytes` + `fixed_length: N`
manifest metadata in Protobuf), `EnumType` (Protobuf: synthetic
`_UNSPECIFIED = 0` sentinel plus declaration-order sequential values
starting at 1, via `enumerate(enum.values, start=1)`; Rust: a plain
`pub enum` with no numeric discriminant — enum wire stability in Rust
is a serde-rename-string concern, not a positional one), `timestamp`
(Rust: bare `String`, verbatim ISO-8601 text with no truncation applied
by the compiler; Protobuf: `google.protobuf.Timestamp`, full
nanosecond-precision structured type, also no truncation applied).

- [ ] **Step 3: Note what's deliberately not claimed**

The original design doc sketch mentioned "canonical decimal-as-string
form" and "timestamp truncation precision" as if the compiler actively
canonicalizes/truncates values. It doesn't — decimal values pass through
as authored, and timestamps aren't given a truncation precision by
either emitter today. Document the *type* mapping accurately; do not
invent a canonicalization/truncation guarantee that doesn't exist in the
code, since that would make the contract doc aspirational rather than a
real, testable pin.

## Task 2: `docs/wire-format-contract.md`

**Files:**
- Create: `docs/wire-format-contract.md`

- [ ] **Step 1: Write the document**

Structure, matching the verified rules from Task 1:

1. **Status and scope** — what this document guarantees (deterministic,
   byte-identical generated output for the same `.mdl` input, pinned by
   the golden-fixture suite in `cli/tests/fixtures/wire_golden/`) and what
   it explicitly doesn't cover (wire *compatibility* across schema
   changes — that's `validate-compat`, tracked separately and not yet
   implemented).
2. **Field ordering** — declaration order in both targets; Protobuf field
   numbers are `1..N` assigned by declaration order (not stable across a
   field being reordered in the source — reordering fields in `.mdl` is a
   wire-breaking change today with no guard rail, call this out
   explicitly as a known gap `validate-compat` will eventually close, not
   silently gloss over it).
3. **Per-type encoding table** — one row per `FieldType` variant, Rust
   column and Protobuf column, mirroring `compiler-reference.md`'s
   existing per-target table style.
4. **Enum discriminant stability** — Protobuf's `_UNSPECIFIED = 0` +
   declaration-order sequential assignment; note that removing or
   reordering enum values changes wire meaning today with no compiler
   guard (same caveat as field ordering).
5. **How the golden-fixture suite enforces this** — points at
   `cli/tests/fixtures/wire_golden/` and `cli/tests/test_wire_golden.py`,
   explains the update workflow (regenerate, diff, review, commit) for
   the one case this doc anticipates changing on purpose: an intentional
   emitter change.

## Task 3: Golden-Fixture Regression Suite

**Files:**
- Create: `cli/tests/fixtures/wire_golden/wire_golden.mdl`
- Create: `cli/tests/fixtures/wire_golden/golden/rust/*.rs`
- Create: `cli/tests/fixtures/wire_golden/golden/protobuf/*.proto`
- Create: `cli/tests/test_wire_golden.py`

- [ ] **Step 1: Write the fixture**

One domain, one entity (`Widget`) covering every `FieldType` variant this
contract documents: every `PrimitiveType` kind including `uuid(7)`, a
`decimal(10,2)` field, a `binary(32)` field, an `enum(...)` field, an
`array<string>` field, a `map<string,int>` field, and a field referencing
a `semantic` declaration — representative, not exhaustive-of-every-model-
kind (no projections; those aren't part of this gap's scope).

- [ ] **Step 2: Generate the golden output**

Run `emit_rust`/`emit_protobuf` against the fixture workspace (a small
throwaway script or an interactive `uv run python` session is fine — this
is a one-time generation step, not a task with its own test) and write
each artifact's `.content` verbatim to the corresponding path under
`cli/tests/fixtures/wire_golden/golden/`. Manually read the generated
output once before committing it, to confirm it matches what Task 1/2
documented — if it doesn't, the doc (not the golden file) is wrong and
needs fixing first.

- [ ] **Step 3: Write the regression test**

`cli/tests/test_wire_golden.py`: load the fixture workspace once
(module-scoped fixture, matching `test_conformance_fixture.py`'s
pattern), emit Rust and Protobuf, and for every artifact assert
`artifact.content == golden_path.read_text(encoding="utf-8")` — a direct
byte-for-byte comparison, not a substring check. Include one test that
enumerates the golden directory and confirms every golden file has a
corresponding emitted artifact (catches the fixture silently losing
coverage as much as the emitter silently changing).

- [ ] **Step 4: Verify the suite passes**

Run from `cli/`: `uv run pytest tests/test_wire_golden.py -q`. It should
pass immediately since the golden files were generated from the same
code being tested — this step is a sanity check on the harness itself,
not a red/green TDD cycle (there's no "new behavior" here to drive with a
failing test first; the behavior already exists, only the pin is new).

- [ ] **Step 5: Prove the regression guard actually guards something**

Temporarily hand-edit one golden file (e.g. flip a field's Rust type),
re-run the test, confirm it fails with a clear diff-shaped assertion
message, then revert the edit. This confirms the byte-exact comparison
actually catches drift rather than silently passing due to a fixture bug
(e.g. comparing a file to itself). Do not leave this edit in the
committed state.

## Task 4: Documentation

**Files:**
- Modify: `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Update ROADMAP and CHANGELOG**

Mark gap 5 shipped in `ROADMAP.md`'s feature-gaps response entry, noting
explicitly that it adds documentation and regression-test infrastructure
only — no emitter behavior changed — and that the larger protobuf/gRPC
capability set (descriptor sets, compat validation, etc.) remains tracked
under the separate, older design doc, unaffected by this gap. Add a
`CHANGELOG.md` `[Unreleased]` entry with the same scope note.

- [ ] **Step 2: Verify docs mention the new artifacts**

Run from repo root:
`rg -n "wire-format-contract|wire_golden" ROADMAP.md CHANGELOG.md docs/wire-format-contract.md`.

## Task 5: Final Verification

- [ ] **Step 1: Run the new test file and the full Rust/Protobuf emitter suites**

```bash
uv run pytest tests/test_wire_golden.py tests/test_emit_rust.py tests/test_emit_protobuf.py --tb=short -q
```

- [ ] **Step 2: Run the full suite, ruff, and the mypy baseline ratchet**

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest --tb=short
uv run python ../.github/scripts/check_mypy_baseline.py --baseline mypy-baseline.txt -- uv run mypy src/modelable --no-error-summary --show-error-codes
```

No source files change in this slice, so the mypy baseline should not
need regeneration — run the ratchet as a confirmation, not an expected-
change step. If it does show drift, regenerate per the established
lesson (after `ruff format`'s final pass).

- [ ] **Step 3: Inspect the final diff**

```bash
git diff --stat
```

Expected: diff touches only new files (`docs/wire-format-contract.md`,
the fixture `.mdl`, the golden files, the test file) plus `ROADMAP.md`
and `CHANGELOG.md` — zero lines changed in any existing `src/` file.

## Self-Review

Spec coverage:

- Covered: a wire-format contract document scoped to verified,
  already-true encoding rules; a golden-fixture regression suite that
  fails CI on generated-output drift for Rust and Protobuf.
- Deferred by design (see Scope section and the design doc itself):
  descriptor sets, richer index metadata, `validate-compat`, deleted-field
  reservations — all tracked under the separate protobuf/gRPC design doc.
- Explicitly **not** claimed: value-level canonicalization (decimal
  literal formatting, timestamp truncation) that the original design
  sketch implied but the current emitters don't actually perform.

Placeholder scan: none.

Type consistency: no source code changes in this slice — nothing to
check.
