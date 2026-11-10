# Implementation Plan: TLA+ Formal Verification (Slice 1 & 2)

**Goal:** Establish formal verification of Modelable semantic lifecycle, usage, and resolution invariants using TLA+ and TLC, with local verification tooling and a dedicated CI gate.

**Architecture Document:** [`docs/tla-formal-verification.md`](../../tla-formal-verification.md)

---

## Proposed Changes

### 1. Formal Specification Files

#### `formal/tla/ModelLifecycle.tla`
- Implements the finite state machine with:
  - **Constants:** `Declarations`, `Versions`, `Fingerprints`, `Consumers`, `Profiles`.
  - **Variables:** `known`, `published`, `semanticFingerprint`, `lifecycle`, `consumerUses`, `compatibility`, `retirementApproved`, `resolved`.
  - **Transitions:** `Init`, `AdmitVersion`, `PublishVersion`, `RecordCompatibility`, `RecordUsage`, `RemoveUsage`, `DeprecateVersion`, `ApproveRetirement`, `RetireVersion`, `ResolveConsumer`.
  - **Safety Invariants:**
    - `TypeOK`
    - `PublishedIsKnown`
    - `PublishedIdentityIsImmutable`
    - `RetiredIsPublished`
    - `ActiveConsumerNeverReferencesRetired`
    - `ResolutionIsExact`
    - `CompatibilityIsExplicit`
    - `NoEvidenceIsNotSafety`
    - `DeterministicResolution`
  - **Liveness:** Bounded retirement progression under weak fairness.

#### `formal/tla/ModelLifecycle.cfg`
- Defines finite constants:
  - `Declarations = {d1, d2}`
  - `Versions = {v1, v2}`
  - `Fingerprints = {fp1, fp2}`
  - `Consumers = {c1}`
  - `Profiles = {full}`
- Declares `INIT Init`, `NEXT Next`, `INVARIANTS TypeOK ...`.

#### `formal/tla/README.md`
- Documentation covering:
  - Pinned TLA+ version (`tla2tools.jar` v1.7.4 / TLC 2.19, SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`).
  - Local verification command and runner script.
  - State space bounds and budget.
  - Invariant descriptions and how to add new properties.
  - Counterexample scenario interpretation.

### 2. Verification Runner Script

#### `.github/scripts/run_tla_verification.py`
- Python runner to execute TLC deterministically:
  - Accepts `--jar`, `--model`, `--config`, and `--metadir`.
  - Discovers or downloads pinned `tla2tools.jar` matching exact SHA-256 hash.
  - Enforces isolation (keeps TLC metadata/state out of the working tree).
  - Validates exit code and error output; surfaces counterexample traces if violated.
  - Enforces a runtime timeout budget.

### 3. CI Workflow

#### `.github/workflows/formal-verification.yml`
- Runs on push to `main` and pull requests.
- Sets up Java 25.
- Obtains pinned `tla2tools.jar` (verifying SHA-256 `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`).
- Runs `python .github/scripts/run_tla_verification.py`.
- Uploads counterexample traces as artifacts on failure.

---

## Verification Plan

1. **Local TLC execution:** Run TLC on `ModelLifecycle.tla` with `ModelLifecycle.cfg` and verify that all invariants pass across all generated states.
2. **Mutation testing / Counterexample check:** Deliberately mutate a transition (e.g. allow retiring a version with active consumer or allowing mutable semantics for published versions) and confirm that TLC fails and reports the expected counterexample trace.
3. **Runner test:** Run `.github/scripts/run_tla_verification.py` locally and verify clean exit and proper temporary state management.
4. **Standard Modelable gates:** Run `ruff format`, `ruff check`, mypy baseline ratchet, and `pytest`.
