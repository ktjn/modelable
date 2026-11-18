---
name: ddd
description: Apply strategic Domain-Driven Design (event storming, bounded contexts, context mapping, aggregates) to discover capabilities, invariants, components and domains. Use in greenfield phases 1–4, brownfield reverse discovery steps 3–4 and modernization re-derivation; not for tactical code design inside a component.
---

# Domain-Driven Design

Rules: [constitution § Components](../../../CONSTITUTION.md#components). Format: [`spec.md`](../../../spec.md) §§ 2–5.

## Mapping

| DDD | Metamodel |
|---|---|
| Bounded context | `system.domains` entry; `Component.domain` |
| Customer–supplier | Customer domain `uses` the supplier (acyclic, `DOM-02`, `DOM-03`); customer components `requires` the supplier's capabilities |
| Conformist | As customer–supplier; the consumer adopts the supplier's model as is: its copies are `derived_from` the supplier's data models, with no translating component |
| Anti-corruption layer | Component in the consumer domain providing a technology-independent capability over the supplier (or an `external` component); its own data models are `derived_from` the supplier's |
| Open host service, published language | Supplier capability with an `interface` and request/response data models; a shared contract package sits in the lowest layer |
| Shared kernel | A shared domain, or a `domain_neutral` layer (`DOM-04`), that is technical or vocabulary only (see [BROWNFIELD.md § Architecture rules](../../../BROWNFIELD.md#architecture-rules)); shared data ownership stays a `shared-data-ownership` waiver below release, not a target |
| Ports and adapters | Contract in the lowest layer; where the port must stay with its consumer, `Capability.defined_by` and `contract_paths` (`CAP-05`) with the adapter as a lower-layer provider |
| Aggregate | Consistency boundary: `Component.consistency: strong`, its `owns_data` |
| Aggregate invariant | `capabilities.invariants` |
| Command | Capability with `preconditions`, `postconditions`, `failure_modes` |
| Domain event | Capability with `interface.mode: async`; payload as a `DataModel` |
| Policy (when X then Y) | Requirement on the reacting capability |
| Ubiquitous language | Capability, invariant, data model and field IDs; definitions in `Domain.terms`, checked with `--report duplicates` |

Tactical patterns (entities, value objects, repositories) stay inside the component's implementation; they are not specified.

Technical systems (engines, protocol stacks, infrastructure): domains are subsystems (concurrency control, recovery, replication, storage), and context-map relations reduce to `Domain.uses` and capabilities; aggregates, commands and events apply only where the subsystem has them. The glossary (`Domain.terms`) still applies: `term`, `epoch`, `commit` or `lease` often mean different things in different subsystems.

## Steps

1. **Event storming**: list domain events, the commands causing them and the policies reacting to them → capability stubs and failure modes. Brownfield: derive events from writes, messages and logs; record observed behavior only.
2. **Invariants**: for each command, the rules that must hold before and after → `preconditions`, `postconditions`, `invariants`.
3. **Aggregates**: group commands sharing an invariant that needs strong consistency → one component each; invariants spanning components become eventual and need a requirement.
4. **Contexts**: group components sharing a language → `domains`; record relations as `uses`; a cycle means a missing context or misplaced component.
5. **Validate**: `metamodel.py <spec> --stage architecture`.

## Rules

- Names come from the domain, not technology (no `kafka-consumer` component).
- A renamed ID is a breaking change; in a baseline import, declare it (`id_prefix`, `allow_fields`, `refinements`).
- Brownfield: map as-is contexts first; record leaks (shared tables, cycles) as waivers before proposing target contexts ([MODERNIZATION.md](../../../MODERNIZATION.md)).

## Prompt

"Run an event storm of `<domain>`: list events, commands, policies and the invariants each command protects; group commands into aggregates by strong-consistency invariant and aggregates into bounded contexts with their relations. Map to capabilities, components and domains; do not name technologies."
