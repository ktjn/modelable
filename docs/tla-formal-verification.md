# TLA+ Formal Verification

> **Status:** Proposed implementation specification.
> **Scope:** Development-time verification of Modelable semantic invariants.
> TLA+ is not a runtime dependency, a second semantic implementation, or a replacement for compiler tests.

## Goal

Use TLA+ and TLC to verify stateful invariants that are difficult to establish from example-based tests alone, especially where model evolution, lifecycle metadata, usage evidence, package resolution, and compatibility interact.

The formal model verifies rules already owned by Modelable. It must not invent a parallel product model.

## Architectural fit

Modelable remains:

```text
.mdl -> semantic graph -> usage/change graphs -> consequence graph -> plan
```

Formal verification is development tooling beside that pipeline:

```text
architecture + protocol invariants
              |
              v
       formal/tla/*.tla
              |
              v
             TLC
              |
              +--> counterexample traces
              +--> CI gate
```

TLA+ specifications describe abstract states and transitions. Python remains the production implementation.

### Non-goals

- No TLA+ execution in normal `modelable` commands.
- No generated Python implementation from TLA+.
- No hosted or distributed registry service.
- No runtime subscription/materialization semantics.
- No parser, LSP, emitter, or UI implementation model.
- No automatic proof that Python conforms to the model in the first slice.
- No reimplementation of target-specific or field-level compatibility rules.

## First verification boundary: `ModelLifecycle.tla`

Model exact declaration identities and these abstract facts:

- known declaration versions;
- immutable published versions;
- external lifecycle state;
- consumer usage evidence;
- compatibility between exact versions;
- retirement eligibility;
- exact consumer resolution.

Declaration contents stay opaque. The shipped compiler determines concrete compatibility; TLA+ verifies the lifecycle and resolution consequences of those facts.

Use small finite constants for `Declarations`, `Versions`, `Consumers`, and `CompatibilityProfiles`. Represent a declaration version as `<<declaration, version>>`; production canonical identity remains `<domain>.<declaration>@<version>`.

State variables should represent:

```text
known
published
semanticFingerprint
lifecycle
consumerUses
compatibility
retirementApproved
resolved
```

Lifecycle vocabulary may use `candidate`, `published`, `deprecated`, and `retired` inside the formal model. This must not imply new `.mdl` grammar; production lifecycle state remains external metadata.

## Transitions

Keep operations independent so TLC can explore their interleavings.

### AdmitVersion

Add a previously unknown exact declaration version. Canonical identity must be unique; existing versions remain unchanged.

### PublishVersion

Publish a known candidate and freeze its semantic fingerprint. No transition may replace the semantics associated with that exact published identity.

### RecordCompatibility

Record compatibility for two exact versions and a named profile. This abstracts the shipped compatibility engine rather than reproducing it.

### RecordUsage / RemoveUsage

Add or remove explicit consumer evidence for an exact version. Absence of evidence is not proof that a version is unused.

### DeprecateVersion

Move a published version to deprecated state. Existing consumers remain valid.

### ApproveRetirement

Record an explicit policy decision that available evidence is authoritative enough to permit retirement. This prevents an empty observed usage set from being interpreted as proof of safety.

### RetireVersion

Retire a deprecated version only when retirement is approved and no active recorded consumer references it.

### ResolveConsumer

Resolve a requirement to one exact version. Never resolve to an unknown or retired version, or to a version lacking an explicit compatible result for the requested profile. If several versions qualify, use an explicit deterministic ordering rule.

## Safety properties

TLC must check at least:

- **TypeOK** — every state variable stays inside its declared finite domain.
- **PublishedIsKnown** — every published version is known.
- **PublishedIdentityIsImmutable** — a published exact identity cannot acquire different semantics.
- **RetiredIsPublished** — a retired version was a published contract.
- **ActiveConsumerNeverReferencesRetired** — active recorded consumers never resolve to retired versions.
- **ResolutionIsExact** — persisted resolution is always an exact version, never a range or mutable tag.
- **CompatibilityIsExplicit** — missing compatibility information is never interpreted as compatible.
- **NoEvidenceIsNotSafety** — an empty observed usage set alone cannot authorize retirement.
- **DeterministicResolution** — identical state, requirement, and policy inputs produce one exact resolution.

## Liveness

Keep liveness deliberately small. Initial property:

```text
retirement requested
/\ retirement approved
/\ no active recorded consumers
~>
retired
```

Add fairness only for explicit Modelable guarantees. Operational scheduler assumptions do not belong here.

## Counterexample scenarios

The finite model must be capable of exposing:

1. publish -> consumer resolves -> retire while consumer remains;
2. publish v1 -> publish v2 -> resolve an incompatible consumer to v2;
3. publish -> replace the same exact identity with changed semantics;
4. no observed usage -> infer safe retirement without authoritative evidence;
5. compatible range -> multiple candidates -> nondeterministic resolution;
6. deprecate -> existing consumer remains valid;
7. retire -> new consumer attempts to resolve the retired version.

Reduce architectural bugs discovered by TLC to small regression configurations or documented invariants.

## Repository layout

```text
formal/
  tla/
    ModelLifecycle.tla
    ModelLifecycle.cfg
    README.md
```

Do not put TLA+ under `cli/src/modelable`; it is verification infrastructure, not runtime code.

The README must document the pinned TLA+ version, local TLC command, counterexample interpretation, CI state-space bounds, and how to add an invariant.

## Tooling

Pin the TLA+ tool distribution used by CI. Never fetch an unpinned `tla2tools.jar` as "latest" during validation.

Execution may be wrapped, but the underlying contract is equivalent to:

```bash
java -XX:+UseParallelGC -cp tla2tools.jar tlc2.TLC \
  -config ModelLifecycle.cfg ModelLifecycle.tla
```

The wrapper must return non-zero on invariant/liveness failure, keep TLC state outside source directories, use deterministic configuration, and impose a CI timeout/state-space budget.

## CI integration

Add a dedicated `formal-verification` validation job:

1. restore the pinned TLA+ tool;
2. run TLC against every committed configuration;
3. fail on invariant violation, unexpected deadlock, or liveness violation;
4. preserve counterexample/log output on failure;
5. enforce a bounded PR runtime.

CI must not depend on mutable remote artifacts.

## Relationship to production tests

```text
TLA+                     Python
----------------------   --------------------------------
architectural states     concrete compiler implementation
transition interleaving  parsing and semantic algorithms
invariants               protocol/schema conformance
counterexample traces    fixtures and regression tests
small exhaustive model   representative real-world data
```

For every formal invariant, identify a corresponding production test boundary where practical. Do not duplicate the TLA+ state machine in Python solely for testing.

Trace-to-test generation is a possible later slice only if mapping to public Modelable operations is explicit and deterministic.

## Follow-up models

Add further models only after `ModelLifecycle.tla` demonstrates useful counterexamples or protects a concrete invariant.

### `PackageResolution.tla`

Model tag discovery, immutable digest admission, lock pinning, cache/offline resolution, tag substitution, package-content/digest mismatch, and provenance preservation. This directly supports the active OCI package roadmap.

### `ConsequenceOrdering.tla`

Model change facts, usage edges, consequences, prerequisites, and action ordering. Do not model deployment execution.

### `ExtensionAdmission.tla`

Model pinned extension identity/hash, accepted plan versions, capability admission, trust allowlists, and rejection of changed implementations under an existing pin.

## Implementation slices

### Slice 1 — executable lifecycle model

- [ ] Add `formal/tla/ModelLifecycle.tla`.
- [ ] Add bounded `ModelLifecycle.cfg`.
- [ ] Encode the safety properties above.
- [ ] During development, deliberately break at least one transition and confirm TLC produces a useful counterexample; do not commit the broken form.
- [ ] Document local execution.

**Done when:** TLC exhaustively checks the configured finite state space and the model documents the lifecycle/usage assumptions being verified.

### Slice 2 — required CI gate

- [ ] Pin TLA+ tooling by version and digest.
- [ ] Add the `formal-verification` job.
- [ ] Preserve failure traces as CI artifacts.
- [ ] Add a runtime/state budget.

**Done when:** a PR violating a formal invariant fails without running Modelable runtime code.

### Slice 3 — implementation correspondence

- [ ] Map each formal transition to an existing compiler/protocol operation or mark it explicitly abstract.
- [ ] Map invariants to production tests where a concrete boundary exists.
- [ ] Add regression fixtures for bugs found by TLC.
- [ ] Document differences between the finite model and production implementation.

**Done when:** maintainers can identify exactly which production behavior each formal rule constrains.

### Slice 4 — package resolution

- [ ] Add `PackageResolution.tla` when OCI distribution implementation begins.
- [ ] Verify exact digest locking and offline resolution invariants.
- [ ] Cover mutable-tag substitution and corrupted-content traces.

**Done when:** the OCI package lifecycle has an executable formal model covering its stateful correctness properties.

## Acceptance criteria

Retain the TLA+ layer when:

- it models existing architectural rules rather than creating new product semantics;
- TLC finds violations when representative invariants are deliberately broken;
- normal product execution has zero dependency on TLA+;
- CI is deterministic, pinned, bounded, and actionable on failure;
- counterexamples translate cleanly into implementation regression tests;
- formal models remain materially smaller than the implementation they constrain;
- `docs/architecture.md` remains the source of product truth.

If a formal model becomes a second implementation of compatibility or Modelable semantics, reduce its scope.
