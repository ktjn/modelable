# Modelable and Supercargo

> **Status:** External comparison for orientation only. This document
> describes how Modelable relates to [Supercargo](https://supercargo.dev/), a
> separate commercial product, to help readers place Modelable in the
> data-contract landscape. Supercargo details are drawn from its public
> website and the public
> [terraform-provider-supercargo](https://github.com/supercargo-dev/terraform-provider-supercargo)
> repository as of mid-2026; treat them as indicative, not authoritative, and
> verify against the vendor before relying on them. Nothing here implies
> affiliation, endorsement, or interoperability.

Modelable and Supercargo address the same problem — preventing schema and
contract drift from silently breaking downstream data consumers — from
opposite directions. Modelable is a contract-first, open-source compiler and
language server. Supercargo is a code-first, commercial governance layer that
also enforces contracts at runtime. The two are more complementary than
competitive.

## Shared Problem

Both tools exist because data contracts tend to fragment across application
types, database schemas, API definitions, and catalog metadata, and because
breaking changes are cheap to introduce and expensive to discover downstream.
Both classify changes as additive or breaking, gate breaking changes in CI,
and treat ownership and PII/classification as first-class governance concerns.

## How They Differ

### Source of Truth and Authoring Direction

Modelable is **contract-first**. The canonical model is authored directly in
the `.mdl` language and is the artifact you maintain; application types,
schemas, and other representations are generated from it. The cost is a
dedicated language to learn; the benefit is an expressive, versioned,
ownership-aware contract independent of any single implementation, plus an
editor experience (language server, VS Code) built around authoring it.

Supercargo is **code-first**. It extracts deterministic contracts from
existing application structs (reported as Go, Python, and Java, with YAML
also supported) rather than from a separate specification. The cost is that
the contract is bounded by what the source code expresses; the benefit is
lower authoring friction and no new language.

### Design Time Versus Run Time

Modelable operates entirely at **design time**: validate, resolve, check
compatibility, trace lineage, report governance gaps, and generate artifacts.
It produces no runtime component and moves no data. Runtime subscriptions,
adapters, replay, and materialization are explicitly deferred in
[ROADMAP.md](../ROADMAP.md).

Supercargo spans design time **and run time**. Beyond CI validation on each
pull request, it is described as deploying gateways (managed via a Terraform
provider) that act on data in motion — for example substituting PII with
"Sovereign Tokens" so cleartext never lands in BigQuery, while keeping raw
data inside the customer VPC. That runtime data plane is outside Modelable's
current scope.

### Outputs

Modelable's output is a broad set of generated artifacts — JSON Schema,
TypeScript, C#, Java, Python, Rust, Go, SQL DDL, dbt `schema.yml`, Markdown,
FHIR R4 profiles, OpenMetadata JSON, OpenLineage events, and ODCS — plus
compatibility, lineage, and governance reports. It is a code and schema
generator.

Supercargo's output is primarily an enforcement decision (block or allow a
change) and runtime governance behavior such as tokenization. It is not
positioned as a multi-target code generator.

### Distribution and Maturity

Modelable is open source under Apache 2.0, runs locally as a CLI and language
server, and is at an alpha 1.x stage centered on the local toolchain.

Supercargo is a commercial product from Supercargo Engineering AB; only its
Terraform provider is public. It is positioned for enterprise, BigQuery-centric
deployments with autoscaling for large workloads.

## Summary

| Dimension          | Modelable                                  | Supercargo                                       |
| ------------------ | ------------------------------------------ | ------------------------------------------------ |
| Category           | Contract compiler + language server        | Shift-left data governance layer                 |
| Source of truth    | `.mdl` DSL (contract-first)                | Application structs (code-first)                 |
| Scope              | Design time only                           | Design time + runtime gateway                    |
| Runtime data plane | None (deferred)                            | Yes — PII tokenization into BigQuery, in-VPC     |
| Primary output     | 14+ generated artifact targets + reports   | Enforcement decision + runtime governance        |
| CI enforcement     | `modelable check` / compatibility reports  | CLI blocks breaking changes per pull request     |
| Distribution       | Open source (Apache 2.0), local            | Commercial, enterprise, BigQuery-oriented        |

In short: Modelable is the place to **design and own** a versioned contract
and derive everything downstream from it; Supercargo's pattern is to **derive
and enforce** contracts from existing code, including at runtime. A team could
reasonably use a contract-first authoring tool for design and a runtime
governance layer for enforcement.

## See Also

- [Architecture and system specification](architecture.md) for Modelable's
  current and deferred boundaries.
- [External Integrations and Tool Alignment](integrations.md) for how
  Modelable positions itself against adjacent tools and ecosystems.
