# Formal Verification: Model Lifecycle

This directory contains the formal TLA+ specification and TLC configuration for Modelable's semantic lifecycle, consumer usage evidence, compatibility, and resolution invariants.

Reference architecture: [`docs/tla-formal-verification.md`](../../docs/tla-formal-verification.md).

## Specification Overview

- **`ModelLifecycle.tla`**: Finite-state machine modeling:
  - Exact declaration version identities `<<declaration, version>>`.
  - Candidate admission and publication with immutable semantic fingerprints.
  - Lifecycle state progression: `candidate -> published -> deprecated -> retired`.
  - Explicit consumer usage evidence (`RecordUsage`, `RemoveUsage`).
  - Explicit pairwise compatibility recording under named profiles (`RecordCompatibility`).
  - Host-authorized retirement approval (`ApproveRetirement`).
  - Safe retirement guarded by active recorded usage and active resolution (`RetireVersion`).
  - Deterministic consumer resolution to non-retired, compatible versions (`ResolveConsumer`).
- **`ModelLifecycle.cfg`**: Finite model configuration establishing:
  - Declarations: `{d1}`
  - Versions: `{1, 2}`
  - Fingerprints: `{fp1}`
  - Consumers: `{c1}`
  - Profiles: `{full}`

## Verified Properties

### Safety Invariants
1. **`TypeOK`**: Every state variable remains within its declared finite domain.
2. **`PublishedIsKnown`**: Every published version is known.
3. **`PublishedFingerprintUnchanged`**: A published exact identity cannot acquire altered semantics.
4. **`RetiredIsPublished`**: A retired version was previously a published contract.
5. **`ActiveConsumerNeverReferencesRetired`**: Active recorded consumers and resolved requirements never reference retired versions.
6. **`ResolutionIsExact`**: Persisted resolution is always an exact version or none, never a mutable tag or range.
7. **`CompatibilityIsExplicit`**: Missing compatibility information is never interpreted as compatible.
8. **`NoEvidenceIsNotSafety`**: Absence of recorded usage alone cannot authorize retirement; explicit `retirementApproved` policy decision is required.
9. **`DeterministicResolution`**: Identical requirement, candidate, and profile inputs produce deterministic exact resolutions.

## Tooling & Verification

### Pinned Tooling
- **Tool:** `tla2tools.jar` v1.7.4 (TLC 2.19, OpenJDK 25 LTS).
- **SHA-256 Digest:** `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`
- **Location:** `.agentbuild/formal/tla2tools.jar` (or downloaded on-demand and verified in CI).

### Running Locally
Using the verification runner:
```bash
python .github/scripts/run_tla_verification.py
```

Direct execution with TLC:
```bash
java -XX:+UseParallelGC -cp <path-to>/tla2tools.jar tlc2.TLC \
  -metadir <temp-dir> \
  -config formal/tla/ModelLifecycle.cfg formal/tla/ModelLifecycle.tla
```

*Note: Always use `-metadir <temp-dir>` to ensure TLC state and disk queues do not pollute the source repository.*

### State Space Bounds
With the configured model bounds (`|Declarations|=1, |Versions|=2, |Consumers|=1`), TLC explores:
- **Reachable States:** ~2,236 distinct states (~19,985 total states generated).
- **Graph Depth:** 16 transitions.
- **Runtime Budget:** < 5 seconds.

## Adding an Invariant
1. Add the invariant predicate to `formal/tla/ModelLifecycle.tla`.
2. Add the predicate name under `INVARIANTS` (for state invariants) or `PROPERTY` (for temporal/action properties) in `formal/tla/ModelLifecycle.cfg`.
3. Run `python .github/scripts/run_tla_verification.py` to verify that TLC confirms the invariant across the finite state space.
