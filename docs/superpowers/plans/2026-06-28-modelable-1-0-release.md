# Modelable 1.0 Release Program Plan

This plan defines the path from the current public alpha to a Modelable 1.0
open-source release. It treats Modelable as the product source for model
definition, validation, compatibility, planning, and generated artifacts, while
using Observable as the external runtime conformance project.

Observable does not live in this repository. Modelable 1.0 can still require an
Observable release-candidate pass as release evidence, as long as the evidence is
recorded in the Modelable release issue, release notes, or linked PRs.

## Authoring Context

- Date: 2026-06-28.
- Current repository state: the roadmap shows the local compiler, registry,
  planner, compatibility, governance, emitters, CLI workflows, and hardening
  surfaces as recently shipped and still hardening (the roadmap uses "recently
  shipped, still hardening" framing, not a completed-milestone stamp).
- Current release state: Modelable is still presented as a public alpha, with
  package metadata and extension metadata on the 0.5.x line.
- Current release automation state: the release workflow builds artifacts, but
  package publishing remains disabled until the publishing trust path is ready.
- Open issues checked at authoring time: none.
- Runtime proof target: Observable at `https://github.com/ktjn/Observable`.

## Release Goal

Ship Modelable 1.0 as an open-source release with:

- a clearly documented stable support boundary;
- aligned package, extension, changelog, and release metadata;
- repeatable local and CI verification;
- a working publishing path;
- explicit open-source project hygiene;
- external runtime conformance evidence from Observable.

The release should not imply that all deferred hosted platform, adapter, or
runtime services are implemented inside this repository. If runtime execution is
part of the 1.0 claim, the claim must be scoped to Observable exercising the
generated contracts and a recorded conformance harness.

## Non-goals

- Do not vendor, mirror, or submodule Observable into this repository.
- Do not add product features to Observable from the Modelable release branch.
- Do not weaken immutable published-contract semantics for models or
  projections.
- Do not broaden runtime, materializer, adapter, or hosted platform scope unless
  the architecture and roadmap are updated first.
- Do not publish a 1.0 tag until the publishing path has been verified with the
  same artifacts that will be released.

## Operating Model

Each iteration should be a focused PR. Every PR should state the user-visible
release intent, touched files, verification evidence, skipped gates, and any
scope moved to a later iteration.

For implementation iterations, open GitHub issues first so that 1.0 scope is
visible and can be reviewed independently from code changes. Observable work
should happen in Observable branches and PRs, then be linked from the Modelable
release issue or release note.

## Iteration 0: Plan And Triage

Outcome: this plan is committed as the first release-program artifact.

Work:

- Add the release plan under `docs/superpowers/plans/`.
- Confirm the roadmap and product specification still describe the current
  source of truth.
- Confirm open issues before creating new 1.0 tracking issues.
- Identify the Observable migration and runtime proof as the main external
  conformance path.

Exit check:

- Documentation-only review passes.
- No product behavior changes are included.
- Follow-up issue list is ready to create after the plan PR is accepted.

## Iteration 1: Release Definition And Open-source Hygiene

Outcome: the repository can be understood, consumed, and governed as an
open-source project before 1.0 code hardening starts.

Work:

- Define the 1.0 support boundary in `README.md`, `ROADMAP.md`, and release
  notes. Be explicit about what is stable in 1.0 and what remains deferred.
- Check repository hygiene for a public open-source release:
  - license file and package metadata;
  - contributing guide;
  - security reporting policy;
  - code of conduct, if desired for the project;
  - issue and PR templates;
  - maintainer and release process documentation.
- Remove public-alpha wording only when the support boundary is final.
- Decide whether the VS Code extension is part of the 1.0 distribution or a
  companion artifact with separate marketplace timing.

Completed 2026-06-28:

- Added `## 1.0 stable surface` to `README.md` and `## Targeting 1.0` to
  `ROADMAP.md` with explicit in-scope and deferred boundaries.
- VS Code extension decision: ships as a VSIX companion artifact with the 1.0
  release; VS Code Marketplace distribution is post-1.0.
- Hygiene audit: `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, issue templates, and PR template are
  all present and current.
- Tracked as Iteration 5 work (not blockers): replace public-alpha wording in
  `README.md`, `CONTRIBUTING.md`, and `SECURITY.md`; update `SECURITY.md`
  supported-versions policy; update install instructions to published package.
- Added 1.0 release additional requirements to `docs/maintainers.md` section 8.

Exit check:

- Project entry points describe the same 1.0 contract. ✓
- `docs/maintainers.md` describes the final release workflow and PR policy. ✓
- Any missing open-source hygiene items are tracked as 1.0 blockers or explicit
  post-1.0 work. ✓

## Iteration 2: Compiler And Emitter Contract Hardening

Outcome: Observable and local samples can consume generated artifacts without
manual patches for known 1.0-blocking gaps.

Work:

- Create focused issues for the known Observable migration blockers:
  - duplicate `binding` declarations blocking clean full-workspace compile;
  - Rust enum emission represented as `String` where a generated enum contract
    is expected;
  - timestamp mappings emitted as Rust `String` where the target contract expects
    a temporal type decision;
  - TypeScript imports missing for cross-model named references;
  - nullable `Option<T>` versus omittable field semantics;
  - invalid TypeScript for `array<enum(...)>`;
  - array element adapter type support such as `rust.type`;
  - default-empty arrays in generated outputs;
  - numeric-prefixed enum members.
- Decide which blockers are true Modelable defects, which are modeling changes,
  and which are deferred compatibility decisions.
- Add focused regression fixtures before changing behavior.
- Keep emitter decisions documented in the language reference or emitter docs
  when they define a public contract.

Completed 2026-06-28:

- Issues opened: #87–#95 (nine blockers).
- Fixed in Modelable (PRs #96, #97, #98):
  - #87 Duplicate binding declarations — workspace deduplicates identical connector bindings; conflicts raise SEM diagnostic.
  - #88 Rust enum as String — Rust emitter generates `pub enum` types with serde derives.
  - #90 TypeScript missing cross-model imports — `ref<X>` resolves to stable interface name and emits `import type`.
  - #92 Invalid TypeScript for `array<enum(...)>` — union wrapped in parentheses: `('A' | 'B')[]`.
  - #93 `rust.type` ignored for array element — hint now applies inside `Vec<>`.
  - #94 Default-empty arrays — optional `array<T>` emits `Vec<T>` with `#[serde(default)]`.
- Decided, not fixed:
  - #89 Rust timestamp → `String` is by design; `@wire(rust.type: "chrono::DateTime<Utc>")` is the workaround. Closed.
  - #91 Nullable vs omittable — blocked on grammar; `Option<T>` covers both. Documented.
  - #95 Numeric-prefixed enum members — blocked on grammar. Test marked `xfail`.

Exit check:

- Each fixed blocker has a local test in Modelable. ✓
- Observable can remove or reduce local workarounds for the fixed items. ✓
- No compatibility behavior is changed without a documented versioning decision. ✓

## Iteration 3: Observable Conformance Harness

Outcome: Observable proves the Modelable release candidate against a real
runtime and generated-artifact consumer outside this repository.

Work in Observable:

- Create an Observable release-candidate branch or PR.
- Pin Observable's Modelable dependency to the Modelable release-candidate tag
  or commit.
- Regenerate the committed Modelable-derived artifacts.
- Review the generated Rust and TypeScript diffs as public-contract changes.
- Run the Observable model validation, generated artifact checks, and local
  Docker-backed smoke path that exercises Redpanda, Postgres, ClickHouse, and
  the application services.
- Record exact commands, logs, artifact diffs, and any accepted deviations in
  the Observable PR.

Work in Modelable:

- Link the Observable PR or release-candidate evidence from the Modelable 1.0
  release issue.
- If Observable cannot be public at release time, copy sanitized verification
  evidence into the Modelable release notes or a public tracking issue.
- Do not make Observable-only product decisions part of Modelable's public
  contract unless the Modelable specification is updated.

In progress 2026-06-28:

- Modelable 1.0 release tracking issue: #99.
- RC pinning commit for Observable: `ddaace7` (current `main` after Iteration 2).
  Observable install: `pip install git+https://github.com/ktjn/modelable.git@ddaace7`
- Observable work is pending; evidence will be linked from issue #99.

Exit check:

- Observable passes against the same Modelable candidate intended for release.
- Any Observable-only failures are either fixed in Observable or explicitly
  accepted as outside the Modelable 1.0 contract.
- Any Modelable-caused failure is fixed before release-candidate approval.

## Iteration 4: Release Candidate And Publishing Dry Run

Outcome: Modelable has a release candidate that can be built, verified, and
published through the intended path.

Work:

- Align versions across package metadata, extension metadata, changelog, tests,
  and release documentation.
- Register and verify the PyPI trusted publishing path, then remove the disabled
  publish guard only when publishing is ready.
- Run the complete local gate from `docs/maintainers.md`.
- Run focused gates for any changed compiler, compatibility, lineage,
  governance, emitter, or generated-artifact surface.
- Run the GitHub Validate workflow for the release-candidate branch.
- Produce release artifacts from the release workflow and inspect them before
  tagging final 1.0.

Exit check:

- The release workflow can publish from the intended tag or protected branch.
- Artifact contents match the changelog and package metadata.
- Observable conformance evidence is attached to the release issue.

## Iteration 5: 1.0 Final

Outcome: Modelable 1.0 is tagged, published, and documented.

Work:

- Create the final changelog entry with release date and support boundary.
- Tag the exact verified commit.
- Publish packages and extension artifacts according to the release process.
- Create the GitHub release with:
  - installation instructions;
  - compatibility and migration notes from 0.5.x;
  - Observable conformance evidence;
  - known limitations and deferred items;
  - verification commands and CI workflow links.
- Update README installation instructions from source install guidance to the
  published package path.

Exit check:

- Fresh install instructions work in a clean environment.
- Published artifacts report version 1.0.0.
- Release notes describe every accepted limitation.

## Iteration 6: Post-1.0 Follow-up

Outcome: the project moves from release stabilization to normal open-source
maintenance.

Work:

- Open follow-up issues for deferred runtime, adapter, materializer, hosted
  docs, and marketplace work.
- Document compatibility expectations for future 1.x releases.
- Keep Observable as an ongoing downstream conformance project, but decide
  whether a smaller public conformance fixture is needed for contributors who
  cannot access Observable.

Exit check:

- 1.1 work starts from tracked issues, not from leftover release ambiguity.
- Contributors can understand what is required to make a safe change.

## 1.0 Blocking Checklist

- Stable 1.0 contract documented.
- Open-source hygiene complete or explicitly deferred.
- Release workflow can publish.
- Version metadata aligned.
- Changelog complete.
- Local Modelable gate passing.
- Relevant emitter and generated-artifact gates passing.
- Observable conformance pass recorded.
- No unresolved blocker weakens published-contract immutability, governance,
  compatibility, lineage determinism, or PII protections.

## Review Questions For Each Iteration

- Does this change move Modelable closer to a releasable 1.0, or is it scope
  expansion?
- Does it change the public modeling, compatibility, lineage, governance, or
  generated-artifact contract?
- Is the verification evidence local, repeatable, and tied to the touched
  surface?
- If Observable exposed the need for the change, is the fix in the right
  repository?
- If a gate was skipped, is the reason documented and acceptable for 1.0?
