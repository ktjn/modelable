# Future Direction

> **Status:** Directional research, not committed roadmap work.
>
> Items in this document describe plausible product evolution and ecosystem
> alignment. They move into `ROADMAP.md` only when a concrete consumer, GitHub
> issue, and accepted design make the work actionable.

## Product thesis

Modelable should evolve from a model compiler into a **compiler for data
contracts and their consequences**.

The durable product loop is:

```text
contract change
    -> semantic facts
    -> affected usage
    -> consequences
    -> required actions
```

The schema itself is not the differentiated product. The differentiated product
is being able to answer, reproducibly and before deployment:

- what changed semantically;
- which application-visible contract surfaces are affected;
- which consumers are affected and why;
- which actions are required;
- which actions can be generated safely;
- which actions still require application-specific decisions.

The near-term offline registry, usage graph, consequence graph, explicit
evolution intent, and generated conversion work in `ROADMAP.md` establish the
foundation. This document covers the larger directions that should remain
outside the committed roadmap until validated.

## Design principles

1. **Compiler facts remain authoritative.** Compatibility, lineage, usage,
   consequences, signatures, and loss diagnostics come from the normalized
   semantic graph.
2. **Policy does not redefine facts.** Policy decides what blocks CI or requires
   review.
3. **Normal compilation remains offline and reproducible.** Network access is an
   explicit update/publish/verification operation.
4. **External systems remain external.** Modelable integrates with registries,
   catalogs, brokers, databases, CI systems, and observability tools without
   becoming them.
5. **Generated work is proof-driven.** Never infer a migration, inverse
   transformation, or consumer dependency because names happen to look
   similar.
6. **Open formats beat a required hosted service.** Modelable should be usable
   with Git, files, CI artifacts, OCI registries, and existing schema/catalog
   products.
7. **Observed evidence augments declared intent.** Runtime/build evidence may
   refine consequence analysis, but source contracts and exact dependency
   snapshots remain reproducible inputs.

## Ecosystem alignment

Modelable spans several existing product categories. It should align with the
strongest concepts in each without becoming a clone of any one product.

| Ecosystem | Useful concept to align with | Modelable direction |
|---|---|---|
| Smithy | extensible traits and explicit model-evolution rules | evolve typed namespaced annotations toward a declared extension meta-model with compatibility and propagation semantics |
| Buf | modules, dependency resolution, lock-like reproducibility, breaking-change checks | make registry snapshots feel like a dependency manager and define a portable distributable contract package |
| Apollo GraphOS | usage-aware schema checks based on actual client operations | add optional consumer-usage evidence so theoretical breakage can be distinguished from demonstrated impact |
| Confluent Schema Registry | familiar backward/forward/full and transitive compatibility vocabulary | optionally expose policy aliases that lower into Modelable's richer source/wire/storage/rebuild/governance consequence model |
| ODCS / Data Contract tooling | executable contract assertions | define a verification-adapter boundary where Modelable emits assertions and external adapters execute them |
| OpenMetadata / DataHub | organization-level catalog and lineage graph | export Modelable usage/consequence facts rather than building another catalog |
| Backstage | Component/System/Domain/API/Resource ownership graph | emit organization-level catalog relations from Modelable workspace/application usage manifests |

Compatibility should be conceptual and artifact-level. `.mdl` remains the
canonical semantic source of truth.

## Candidate direction 1 — consumer usage evidence

The offline registry snapshot establishes **declared dependency evidence**:
which exact external contracts an application compiles against.

A future evidence layer could answer a stronger question:

> Which exact fields, operations, variants, or values does the consumer
> demonstrably depend on?

Possible evidence classes:

```text
declared     .mdl references and resolved registry snapshots
generated    generated SDK/schema manifests
static       language/compiler analysis
build        candidate contract compiled/tested by the consumer
runtime      optional observed operations/fields/variants
manual       externally managed consumer declarations
```

Evidence must retain provenance, timestamp, contract signature, application
identity, and confidence. It must never silently replace declared dependency
facts.

Example consequence path:

```text
customer.Customer@3.email
  -> customer.CustomerReply@3.email
  -> customer API getCustomer response
  -> billing-service snapshot
  -> observed billing-web field usage
```

This would let Modelable distinguish:

```text
breaking in theory
breaking for a declared consumer
breaking for an observed consumer
no known consumer impact
```

Do not use absence of runtime evidence as proof that a dependency is safe to
remove.

## Candidate direction 2 — portable contract package and distribution protocol

The offline snapshot design needs no hosted Modelable service. A future
portable package could make contracts distributable through existing artifact
systems.

Conceptual package contents:

```text
manifest
canonical normalized semantic IR
source .mdl
canonical signatures
content hashes
exact dependency metadata
usage/publication metadata
generated target manifests where useful
```

Potential transports:

```text
file/directory
Git
OCI artifact registry
HTTP artifact endpoint
Apicurio or another schema registry adapter
```

Requirements:

- immutable/content-addressed identity;
- deterministic package bytes or deterministic logical manifest;
- exact dependencies;
- optional signatures/attestations;
- offline verification after retrieval;
- no dependency on one vendor registry;
- source registry adapters remain replaceable.

The package is a distribution unit, not a second source language.

## Candidate direction 3 — deployment and evolution plans

Once Modelable knows consequences and explicit evolution intent, it can derive
an **action dependency graph** without executing deployments.

Example:

```text
Customer@2 -> Customer@3

1. producer can emit/read both versions
2. deploy fraud-service with v3 support
3. rebuild reporting projection
4. run storage backfill
5. switch producer default to v3
6. verify v2 has no required consumers
7. retire v2
```

A future command might expose:

```bash
modelable plan --from old --to new
```

Output should be machine-readable and contain prerequisites rather than a flat
checklist.

Modelable must not become a deployment orchestrator. CI/CD, migration tools,
brokers, and operators execute the plan.

## Candidate direction 4 — verification adapter protocol

Modelable already knows structural contracts, value constraints, ownership,
classification, and target mappings. It could define a stable assertion format
that external adapters verify against reality.

Possible assertions:

```text
schema/table/topic exists
field/column type matches
presence/nullability
uniqueness
accepted enum values
numeric/string constraints
referential integrity
freshness/SLA
wire/event conformance
```

Conceptual flow:

```text
.mdl -> compiler assertions -> adapter -> observed system -> evidence report
```

Adapters could target PostgreSQL, Kafka, warehouse platforms, generated API
clients, or external data-quality tools.

The compiler owns assertion semantics. Adapters own credentials, network I/O,
queries, sampling, retries, and system-specific execution.

## Candidate direction 5 — generated conformance and contract-test corpus

Modelable can generate more than production types. A canonical test-data target
could make compatibility and migrations executable in consumer repositories.

Prefer data-first artifacts:

```text
valid/
invalid/
boundary/
compat/
migration/
wire/
```

Possible generated cases:

- representative valid instances;
- invalid instances for each declared constraint;
- boundary values;
- old/new compatibility fixtures;
- serialization golden fixtures;
- migration input/output pairs;
- property-based generator metadata.

Framework-specific adapters may then expose JUnit, xUnit, pytest, Vitest,
proptest, or other idioms without making the core compiler depend on those
frameworks.

## Candidate direction 6 — organization graph federation

An application's usage manifest can be aggregated without copying full contract
bodies into a central Modelable service.

Organization tooling could consume:

```text
application identity
owned contracts
exact consumed contract signatures
provided APIs/events
consumed APIs/events
field-level lineage summaries
consequence paths
ownership/classification facts
```

Likely integrations include Backstage, OpenMetadata, DataHub, and general graph
stores.

Modelable should export facts and stable identities. It should not implement a
new service catalog UI as a prerequisite for compiler use.

## Candidate direction 7 — familiar compatibility policy aliases

Modelable's compatibility model is intentionally richer than a single
backward/forward flag because a change can independently affect source code,
wire format, storage migration, projection rebuild, and governance review.

For adoption, policy configuration could optionally support familiar aliases
such as:

```text
backward
backward-transitive
forward
forward-transitive
full
full-transitive
```

These must lower into explicit Modelable rules. They must not replace or hide
Modelable-specific consequence axes.

## Candidate direction 8 — runtime conformance evidence

External collectors or verification adapters could report observed contract
usage without requiring Modelable to run in the data path.

Example report shape:

```json
{
  "contract": "customer.CustomerEvent@3",
  "signature": "sha256:...",
  "producer": "customer-service",
  "observed": 8927362,
  "invalid": 3,
  "lastObserved": "..."
}
```

Potential uses:

- identify apparently unused versions;
- detect invalid producers;
- strengthen consumer evidence;
- support retirement review;
- correlate deployment changes with contract adoption.

Runtime evidence is advisory unless policy explicitly says otherwise. Historical
absence is not proof of safety.

## Candidate direction 9 — extension meta-model

Typed namespaced annotations in `ROADMAP.md` are the first prerequisite. A
later extension system could let an extension declare:

```text
namespace/version
annotation schema
valid targets
propagation rules
compatibility significance
canonical rendering
validation hooks
emitter mappings
loss behavior
```

This should resemble a compiler trait system rather than arbitrary plugins
mutating the semantic graph.

Security rule: extensions must not execute arbitrary code during ordinary
validation merely because a workspace references an annotation namespace.
Prefer declarative extension metadata and explicitly installed/trusted code
where execution is unavoidable.

## Non-goals

Do not turn Modelable into a:

- hosted schema registry requirement;
- service catalog;
- API gateway;
- CDC engine;
- event broker;
- migration executor;
- deployment orchestrator;
- data-quality scheduler;
- observability backend;
- dbt replacement;
- SDK hosting platform.

Those systems can consume or execute Modelable facts and plans through adapters.

## Promotion criteria

A candidate moves into `ROADMAP.md` only when it has:

1. a concrete consumer/problem;
2. a clear compiler-owned responsibility;
3. a defined boundary to external runtime/tooling;
4. deterministic offline behavior where applicable;
5. machine-readable output from the first slice;
6. compatibility and provenance semantics;
7. conformance/regression fixtures;
8. a GitHub issue and accepted design.

This keeps the roadmap focused while preserving the longer-term architecture:

```text
semantic graph
    -> exact dependency state
    -> usage/evidence graph
    -> consequence graph
    -> generated actions/plans
    -> external execution and observed evidence
```
