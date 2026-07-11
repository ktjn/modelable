# Rust Emitter Correctness Fixes — Design

Date: 2026-07-11

## 1. Purpose

`ktjn/observable`, a downstream consumer of Modelable's Rust target, tracks
three "known limitations" in its `AGENTS.md` that require manual
post-processing after every `modelable compile --target rust` run (see
`AGENTS.md` § "Modelable Emitter Limitations (Manual Patches Required)" in
that repo). Two of the three turn out to be live bugs in this repository with
a clear root cause; the third is already fixed in 1.1.0 but was never
reclassified downstream. This document records root cause and accepted fix
for each, so Observable's manual-patch list can shrink from three items to
one narrower one.

This is a design decision, not an implementation plan — see
`docs/superpowers/plans/` for the implementation slice this design unlocks.

## 2. Finding 1 — `_pascalize` does not re-case fully-uppercase tokens (real bug)

**Symptom (Observable):** `.mdl` enum values written in SCREAMING_SNAKE_CASE
(the correct choice when the wire value must match an external wire format —
here, OpenTelemetry's `SpanKind`/`StatusCode` string values, e.g.
`models/tracing.mdl` line 28: `spanKind: enum(INTERNAL, SERVER, CLIENT,
PRODUCER, CONSUMER)`) are emitted as Rust enum variants named `INTERNAL`,
`SERVER`, etc. instead of idiomatic `Internal`, `Server`. This trips
`clippy::upper_case_acronyms`, forcing Observable to hand-maintain
`#![allow(clippy::upper_case_acronyms)]` in the generated `tracing.rs` module
and re-add it after every regeneration — a hand-edit to a `@generated` file,
which is exactly the failure mode Observable's own tooling guidance warns
against for every other kind of change.

**Root cause:** every emitter that produces PascalCase identifiers
(`cli/src/modelable/emitters/rust.py:168-170`, and duplicated verbatim in
`java.py:36-38`, `csharp.py:31-33`, `go.py:31-33`, `python.py:31-33`,
`typescript.py:49-51`) defines:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:] for part in parts) or "Generated"
```

This uppercases only the first character of each token and leaves the rest
untouched. For a token that already contains an internal separator
(`internal_server`, `internalServer`) that's correct — each split part is
lowercase or mixed-case, so `part[1:]` is already what a human would write.
But for a token that is a single all-uppercase word — the exact shape
SCREAMING_SNAKE_CASE enum values in a domain that mirrors an external wire
format always take — `part[1:]` is *also* all-uppercase, so the function is a
no-op: `_pascalize("INTERNAL")` returns `"INTERNAL"`, not `"Internal"`.

`rust.py`'s enum emission (`_enum_member_name`, line 707) already does the
right thing on the *wire* side — it calls `_pascalize` for the Rust
identifier and falls back to `#[serde(rename = "<original>")]` when the
identifier differs from the source value (line 714-726), so the wire
contract is never at risk. The bug is purely that "differs from the source
value" is false today for all-caps tokens, when it should be true.

**Blast radius:** every emitter listed above is affected by the same helper,
but the practical severity differs sharply by target-language convention:

| Target | All-caps enum variant name | Convention violated? |
|---|---|---|
| Rust | `INTERNAL` | Yes — `clippy::upper_case_acronyms` (hard CI failure for `-D warnings` consumers) |
| C# | `INTERNAL` | Yes — .NET naming guidelines expect `PascalCase`, analyzers (CA1707/IDE1006) flag this |
| Go | `INTERNAL` | Technically legal (exported identifiers just need a capital first letter) but unconventional |
| Java | `INTERNAL` | **Not a bug** — `SCREAMING_SNAKE_CASE` is the idiomatic Java enum-constant convention |
| Python | `INTERNAL` | **Not a bug** — PEP 8 also prescribes `SCREAMING_SNAKE_CASE` for enum members |
| TypeScript | `'INTERNAL'` (string literal union, no identifier) | **Not applicable** — TS emitter doesn't synthesize an identifier for enum values, only a literal-type union |

**Decision:** fix `_pascalize` to correctly title-case a token regardless of
its input casing, by lowercasing the remainder of each split part before
re-applying the capital:

```python
def _pascalize(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value) if part]
    return "".join(part[:1].upper() + part[1:].lower() for part in parts) or "Generated"
```

This is a one-line change per copy, applied to **Rust and C# only** — the two
targets where the current behavior is a convention violation. Go, Java, and
Python are explicitly left unchanged: Go's convention is ambiguous enough
that "fixing" it is a judgment call outside this design's scope, and
Java/Python are not bugs at all — changing them would be a regression
(`INTERNAL` → `Internal` is *wrong* for a Java enum constant). Do not extract
a shared `_pascalize` into `emitters/base.py` under the illusion that one
correct implementation serves all targets — the correct casing for a token
is target-convention-dependent, not a single universal function. Each
emitter keeps its own copy; only the Rust and C# copies change.

**Consequence for `mixedCase` domain/name identifiers:** `_pascalize` is also
used for domain, model, and field names (`_stable_type_name`, line
180-181), which are typically already `camelCase`/`snake_case`/`kebab-case`
in `.mdl` source, not `SCREAMING_SNAKE_CASE`. The fix does not change
behavior for those inputs (`.lower()` on an already-lowercase remainder is a
no-op); it only changes behavior for tokens that were entirely uppercase to
begin with. No `.mdl` corpus in the workspace's test fixtures uses
all-uppercase domain or model names, so this is enum-value-only in practice.

**Testing:** add a wire-golden fixture case
(`cli/tests/fixtures/wire_golden/`, per `wire-format-contract.md`'s existing
regression mechanism) with an enum declared `enum(INTERNAL, SERVER)` and
assert the Rust output emits `Internal`/`Server` variants with
`#[serde(rename = "INTERNAL")]`/`#[serde(rename = "SERVER")]`, and that the
wire value round-trips unchanged. Add the equivalent for C#. Add a unit test
for `_pascalize` directly in `cli/tests/test_emit_rust.py` (and
`test_emit_csharp.py`) covering: single all-caps token, `SCREAMING_SNAKE`
multi-token, already-correct `PascalCase`, and `camelCase` input, to lock the
casing contract independent of full-pipeline golden fixtures.

**Downstream effect:** once this ships, Observable can delete the
`#![allow(clippy::upper_case_acronyms)]` line from
`libs/domain/src/generated/tracing.rs` and remove that bullet entirely from
its `AGENTS.md` known-limitations list — the manual patch stops being
necessary because there is nothing left to suppress.

## 3. Finding 2 — `compile --target` has no per-domain scope, so EMIT003 fires for domains that were never going to use the target (real gap)

**Symptom (Observable):** issue #120 added an `EMIT003`
(`missing_metadata`) warning when the Rust emitter encounters a `NamedType`
field reference it can't resolve. Observable's `scripts/regenerate-models.sh`
runs `modelable compile models/ --target rust --out <tmp>` against the
*entire* `models/` workspace, then copies only the domains that have a
matching `libs/domain/src/generated/<domain>/` directory (`logs`, `tracing`)
into the tree — `nlq`, `dashboards`, `alerts`, and every other TS-only
domain are compiled to Rust and discarded. Any `NamedType` reference in
those discarded domains that doesn't resolve under `--target rust` still
prints an `EMIT003` warning to the terminal, even though that Rust output is
never used. Compiling nine domains to see warnings relevant to two trains
whoever reads the output to skim past `EMIT003` lines rather than read them
— defeating the purpose issue #120 fixed the warning for in the first place.

**Root cause:** `compile` (`cli/src/modelable/commands/compile.py`,
registered via `register_compile_commands`) takes `SOURCE`, `--target`,
`--out`, `--registry`, `--registry-ids`, `--allow-orphaned-registry-ids` —
no flag scopes compilation to a subset of domains. `--target rust` means
"compile every domain in the workspace as if it were going to be consumed by
Rust," with no way to declare that a given domain's Rust output is
speculative/unused and its warnings should be suppressed accordingly.

**Decision:** add a repeatable `--domain <name>` option to `compile` that
restricts compilation (and therefore diagnostics) to the named domain(s);
omitting it keeps today's whole-workspace behavior, so this is additive and
non-breaking. `modelable compile models/ --target rust --domain logs
--domain tracing --out <tmp>` becomes the correct invocation for a consumer
that only wants Rust for two of nine domains, and the flag can be combined
with per-domain output directories in a follow-up if needed. This is
deliberately a CLI-level filter, not a new `.mdl` "targets:" declaration on
the domain itself — a domain doesn't inherently "belong" to a target, a
*consumer* decides which domains it needs for which target, and different
consumers of the same workspace can make different choices (Observable's
`crypto-aggregator` demo, for instance, only wants the `pipeline` domain out
of the same workspace).

**Testing:** add `cli/tests/test_cli_compile.py` (or extend the existing
compile command test module) coverage for: `--domain` restricting the
domain set compiled and diagnosed; multiple `--domain` flags being additive;
an unrecognized `--domain` name producing a clear compile-time error rather
than silently compiling nothing; and no `--domain` flag preserving the
current whole-workspace behavior byte-for-byte (regression guard via the
existing wire-golden fixtures).

**Downstream effect:** Observable's `scripts/regenerate-models.sh` adds
`--domain logs --domain tracing` (and similarly a `pipeline`-only invocation
for the `crypto-aggregator` demo copy step) to its two `modelable compile`
calls. `EMIT003` output becomes fully actionable — every warning printed is
for a domain whose Rust output is actually consumed — which is what
Observable's `AGENTS.md` bullet on this issue was asking for even though it
described the symptom as "the warning fires even for models not targeting
Rust" rather than "there's no way to say which models target Rust."　This
narrows, but does not eliminate, that `AGENTS.md` bullet: `--domain` removes
the noise; it does not add import resolution for `NamedType`s that are
legitimately unresolvable within the requested domain set (that remains
correct, intentional behavior — issue #120 already covers those with
`EMIT003`).

## 4. Finding 3 — ClickHouse Row enum-to-String coercion (not a bug — reclassify)

Observable's `AGENTS.md` lists "Rust ClickHouse enum serialization (issue
#119, partially fixed)" as a limitation requiring
`scripts/regenerate-models.sh` to apply a patch "automatically after
regeneration." Reading the current emitter
(`cli/src/modelable/emitters/rust.py:391-393` forces `String` for any
ClickHouse-`Row`-bound enum field, and lines 547-548 generate the explicit
`match` arm converting the domain enum to that `String` in the `From` impl)
against Observable's actual generated output
(`libs/domain/src/generated/tracing/tracing_span_row_v1.rs`) shows this is
already fully automatic — the emitter generates both the `String` field and
the complete `match`-based `From` impl with no post-processing step. There
is no patch left for `regenerate-models.sh` to apply for this item; the
`.mdl` comment in Observable's `models/tracing.mdl` ("the From<Span> impl
... performs the enum→string conversion, which modelable cannot generate
today") is stale relative to the current 1.1.0 emitter.

**Decision:** no emitter change. This finding exists in this document only
so Observable can move the bullet from "known limitations" to "resolved" and
correct the stale `.mdl` comment — that edit belongs in `ktjn/observable`,
not here. The underlying constraint (`clickhouse-rs` 0.15 panics on
`serialize_unit_variant` for `String`-typed columns, so a typed Rust enum
can never be the `Row` struct's field type directly) is a `clickhouse-rs`
limitation, not a Modelable one; there's nothing to fix upstream here unless
`clickhouse-rs` itself adds enum support, which is out of this project's
control.

## 5. Sequencing

| Order | Finding | Version | Notes |
|---|---|---|---|
| 1 | `_pascalize` casing fix (Rust, C#) | 1.1.1 (patch — bug fix, no grammar/IR change) | Independent, small, no dependency |
| 2 | `--domain` compile filter | 1.2.0 (minor — new CLI surface) | Independent of finding 1 |
| — | ClickHouse enum coercion | n/a | No code change; downstream doc fix only |

Both findings are additive/non-breaking and can ship independently in either
order; they're sequenced here only because finding 1 is a one-line patch
release and finding 2 is a new (if small) CLI option, and patch releases
should not be blocked on a CLI surface review.

## 6. Out of scope

- Extending `--domain` filtering to `validate`, `diff`, or `docs` — this
  design only covers `compile`, where the downstream pain point was
  reported. A follow-up can generalize if the same need shows up elsewhere.
- Fixing `_pascalize`'s all-caps handling for Go or Java — see Finding 1's
  blast-radius table; Java/Python are correct as-is, Go is a judgment call
  deferred to a future design if a consumer reports it as a problem.
- Resolving `NamedType` references *across* an excluded domain when
  `--domain` is used (e.g., a requested domain referencing a type that lives
  only in an excluded domain) — this should be a compile-time error
  (dangling reference), not silently resolved by reaching outside the
  requested set. Confirm this is already `validate`'s behavior before
  implementing `--domain`; if not, that's a prerequisite bug, not part of
  this design.
