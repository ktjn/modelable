# Design: Distributed Data Lineage and Federated Registry

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** Eliminating the single point of failure in the registry and lineage store; enabling cross-team, cross-repository data lineage without a central authority

---

## Context

The baseline architecture stores all domain models, lineage edges, and compatibility metadata in a single `registry.db` SQLite file. This creates several single points of failure:

- **Storage SPOF:** One corrupt or missing file destroys all lineage metadata.
- **Ownership SPOF:** One repository and one team control all domain definitions. Cross-team contribution requires central coordination.
- **Availability SPOF:** Downstream projections cannot be validated if the single registry is unavailable.
- **Integrity gap:** Cross-domain references carry only a logical name and version number; there is no mechanism to verify that the referenced model is the one that was originally depended on.

This spec defines a **Federated Registry Network** — a set of cooperating registry nodes that each own a subset of domains, share lineage facts via an append-only distributed event log, and verify cross-domain dependencies using content-addressed model signatures.

---

## 1. Design Goals

1. **No central authority.** Any registry node can be lost and the system continues operating from surviving nodes and local caches.
2. **Tamper-evident lineage.** Lineage chains are verifiable without querying the original registry.
3. **Team autonomy.** Each team publishes and evolves its own domains independently.
4. **Offline-first compilation.** The local compiler works with cached foreign model replicas; no live network call is required to compile or validate.
5. **Incremental adoption.** A single-node workspace is a degenerate case of a federated registry and requires no new configuration to keep working.
6. **Transport-agnostic propagation.** Lineage events can flow over Kafka, NATS JetStream, shared git, or plain HTTP webhooks, depending on the deployment environment.

---

## 2. Core Concepts

### 2.1 Registry Node

A registry node is a running instance of the Modellable registry for a specific team or service boundary.

A node:

- **Owns** one or more domains. It is the authoritative source for those domains' model versions, compatibility history, and access policies.
- **Mirrors** foreign domains as read-only replicas. A mirror is refreshed from the owning node on demand or on a schedule.
- **Participates** in lineage event propagation, both as a producer (when one of its projections maps a foreign field) and as a consumer (when a foreign projection maps one of its fields).

A node does **not**:

- Modify foreign domain definitions.
- Override another node's access policies.
- Serve as a relay or broker between other nodes.

### 2.2 Content-Addressed Model Signature

Every published model version receives a deterministic **content signature** — a SHA-256 hash computed over the canonical form of the model definition.

**Canonical form** is the normalised, whitespace-collapsed, deterministically serialised MDL representation of the model block. It covers:

- Domain name.
- Model name and kind (`entity`, `aggregate`, `event`, `value`).
- Version number and `changeKind`.
- All field definitions (names, types, annotations, optionality).
- Order of fields (sorted by field name to remove authoring order as a variable).

The signature is stored on the `model_versions` table alongside the version number.

**Fully qualified model reference with signature:**

```
customer.Customer@3#a3f8b2c1d4e5f6a7
```

The short form (without `#`) is still valid for local references. The hash suffix is required when referencing a model across registry boundaries.

### 2.3 Lineage Event

A lineage event is an immutable, timestamped fact about a relationship in the data model. Events are the source of truth for distributed lineage; `lineage.db` is derived from them.

**Event types:**

| Event type | When emitted |
| :--- | :--- |
| `ModelPublished` | A model version is published on any node. |
| `ProjectionPublished` | A projection version is published on any node. |
| `FieldMapped` | The compiler resolves a field mapping from a target field to a source field. |
| `CrossRegistryRef` | A field mapping spans two different registry nodes. |
| `ForeignModelMirrored` | A node caches a replica of a foreign domain model. |
| `ModelDeprecated` | A model version is marked deprecated on the owning node. |

**Common envelope fields (all event types):**

| Field | Type | Description |
| :--- | :--- | :--- |
| `eventId` | `uuid` | Unique identifier for this event. |
| `eventType` | `string` | One of the types listed above. |
| `timestamp` | `timestamp` | UTC time of emission. |
| `registryId` | `string` | Identifier of the emitting registry node. |
| `eventHash` | `string` | SHA-256 of the canonical JSON of this event (excluding `eventHash` itself). |
| `prevHash?` | `string` | Hash of the immediately preceding event in this registry's log, forming a hash chain. |

**`FieldMapped` payload:**

```json
{
  "projectionRef": "billing.BillingCustomer@1",
  "targetField": "invoiceEmail",
  "kind": "direct",
  "sourceRef": "customer.Customer@2.email",
  "sourceModelSignature": "a3f8b2c1d4e5f6a7",
  "expression": null
}
```

**`CrossRegistryRef` payload:**

```json
{
  "projectionRef": "billing.BillingCustomer@1",
  "projectionRegistry": "billing-registry",
  "targetField": "invoiceEmail",
  "sourceRef": "customer.Customer@2.email",
  "sourceRegistry": "customer-platform-registry",
  "sourceModelSignature": "a3f8b2c1d4e5f6a7"
}
```

### 2.4 Lineage Event Log

Each registry node maintains a local **lineage event log** — an append-only sequence of NDJSON records, one per line, stored in `.modellable/lineage-log/`.

Log files are named by date: `2026-05-14.ndjson`. A new file is started each day. Files from previous days are never modified.

The log is the durable source of truth. `lineage.db` is a derived index, rebuilt from the log by `modellable compile` exactly like `registry.db` is rebuilt from `.mdl` files.

Committing the `lineage-log/` directory to the same git repository as the `.mdl` files provides a free, replicated, versioned backup without any additional infrastructure.

### 2.5 Merkle Hash Chain

Events within a single registry's log form a **Merkle hash chain**: each event's `prevHash` field references the `eventHash` of the previous event. This creates a tamper-evident sequence.

A verifier can confirm that no event has been inserted, deleted, or modified by recomputing the hash chain from any known checkpoint.

Cross-registry lineage also forms a **directed acyclic graph (DAG)** of content-addressed edges. A downstream team can verify the integrity of an upstream model without contacting the upstream registry, as long as they hold the upstream model's content signature.

---

## 3. Federated Registry Architecture

### 3.1 Registry Node Topology

```
┌─────────────────────────────────┐      ┌─────────────────────────────────┐
│   customer-platform-registry    │      │       orders-registry           │
│                                 │      │                                 │
│  owns: customer, billing        │      │  owns: orders, shipping         │
│  mirrors: orders (read-only)    │◄────►│  mirrors: customer (read-only)  │
│                                 │      │                                 │
│  registry.db   (owned)          │      │  registry.db   (owned)          │
│  mirror.db     (foreign)        │      │  mirror.db     (foreign)        │
│  lineage.db    (derived)        │      │  lineage.db    (derived)        │
│  lineage-log/  (source of truth)│      │  lineage-log/  (source of truth)│
└────────────┬────────────────────┘      └──────────────┬──────────────────┘
             │ CrossRegistryRef events                  │
             │◄────────────────────────────────────────►│
             │                                          │
             └───────────────┐       ┌──────────────────┘
                             │       │
                   ┌─────────▼───────▼──────────┐
                   │    analytics-registry       │
                   │                             │
                   │  owns: analytics            │
                   │  mirrors: customer, orders  │
                   │                             │
                   │  projects across both       │
                   └─────────────────────────────┘
```

### 3.2 Peer Discovery

Peers are declared in the `workspace.mdl` file using a `registry` block (see Section 5 for IDL syntax). The declared endpoint is the base URL of the peer's Registry API.

Nodes do not broadcast or auto-discover; the workspace manifest is the explicit, version-controlled record of the federation topology.

### 3.3 Foreign Model Mirroring

When a node needs a foreign model (referenced in a projection or by a `import domain` declaration), it:

1. Checks `mirror.db` for a cached replica.
2. If no cache or if `sync: eager` is configured, fetches the model version from the peer's Registry API.
3. Verifies the fetched model's content signature against the declared `#hash` in the reference (if present).
4. Stores the replica in `mirror.db` with a `mirrored_at` timestamp.
5. Emits a `ForeignModelMirrored` event to the local lineage log.

If the peer is unreachable and a cache exists, the node uses the cached replica and logs a warning. If no cache exists, compilation fails with a descriptive error.

**Sync modes:**

| Mode | Behaviour |
| :--- | :--- |
| `eager` | Mirror all models from the peer at registry startup and on any `compile`. |
| `lazy` | Mirror on first reference (default). |
| `pinned` | Always use the local cache; never contact the peer. For air-gapped or offline environments. |

### 3.4 Cross-Registry Lineage Propagation

When the compiler resolves a field mapping that spans registry boundaries, it:

1. Records a `CrossRegistryRef` event in the local lineage log.
2. If the peer is reachable, sends the event to the peer's `/lineage/ingest` API endpoint.
3. The peer stores the event in its own lineage log as an incoming cross-registry edge.
4. The peer can now answer "which downstream registries depend on this model?" without contacting the downstream node.

If the peer is unreachable, the event is queued for delivery. Queued events are retried with exponential backoff (2 s, 4 s, 8 s, 16 s, then per-hour indefinitely). The local lineage store remains complete regardless.

### 3.5 Conflict Resolution

Model version immutability eliminates most conflicts: once published, a version's content signature never changes.

The only conflict scenario is **duplicate event IDs** during log merges (e.g., when two nodes independently discover the same upstream change and both emit `ForeignModelMirrored` for it). These are resolved by deduplication on `eventId` during log replay.

---

## 4. Storage Model (Distributed Mode)

The distributed storage layout extends the local layout with three additions:

```
.modellable/
  registry.db                        # owned domains — derived from .mdl files
  mirror.db                          # foreign model replicas — derived from peer syncs
  lineage.db                         # lineage index — derived from lineage-log/
  lineage-log/
    2026-05-14.ndjson                 # append-only lineage events (source of truth)
    2026-05-13.ndjson
  plans/
    billing.BillingCustomer.v1.plan.json
  artifacts/
    billing/
      BillingCustomer.v1.json
      BillingCustomer.v1.ts
      BillingCustomer.v1.md
```

### 4.1 `mirror.db` Schema (additions)

| Table | Key columns | Purpose |
| :--- | :--- | :--- |
| `registry_peers` | `peer_id`, `endpoint`, `sync_mode` | Declared peer registry nodes. |
| `mirrored_domains` | `domain`, `peer_id`, `mirrored_at` | Which foreign domains have been mirrored. |
| `mirrored_model_versions` | `domain`, `model`, `version`, `content_signature`, `raw_mdl` | Cached foreign model versions with integrity proofs. |

### 4.2 `lineage.db` Schema (additions to `lineage_edges`)

Two columns are added to the existing `lineage_edges` table:

| Column | Type | Description |
| :--- | :--- | :--- |
| `source_content_signature` | `text` | Content hash of the source model version at mapping time. |
| `is_cross_registry` | `boolean` | True when source and target are owned by different registry nodes. |
| `source_registry_id` | `text?` | Owning registry of the source model (null for local). |
| `event_hash` | `text` | Hash of the originating lineage event. Ties back to the log. |

### 4.3 Rebuild Guarantee

The same guarantee as for `registry.db` applies: deleting all derived databases (`.db` files) and re-running `modellable compile` from the `.mdl` source files plus the `lineage-log/` directory must produce an identical result.

The `lineage-log/` directory is therefore the only artifact that must be preserved in source control or backed up externally.

---

## 5. IDL Changes

### 5.1 Registry Block in `workspace.mdl`

A `registry` block declares this workspace as a registry node and lists peer nodes.

```mdl
workspace "ecommerce-platform" {
  description: "E-commerce platform model registry."

  registry {
    id: "billing-registry"
    owns: ["billing"]
    endpoint: "https://reg.billing.example.com"
  }

  peers: [
    { id: "customer-platform-registry", endpoint: "https://reg.customer-platform.example.com", sync: lazy  },
    { id: "orders-registry",            endpoint: "https://reg.orders.example.com",            sync: eager }
  ]

  generate {
    docs       -> "./generated/docs/"
    typescript -> "./generated/types/"
    jsonschema -> "./generated/jsonschema/"
  }
}
```

**`registry` block fields:**

| Field | Required | Description |
| :--- | :--- | :--- |
| `id` | Yes | Stable, unique identifier for this registry node. Used as the `registryId` in lineage events. |
| `owns` | Yes | Array of domain names this node is authoritative for. |
| `endpoint` | No | Base URL of this node's Registry API. Required if peers need to sync from this node. |

**`peers` entry fields:**

| Field | Required | Description |
| :--- | :--- | :--- |
| `id` | Yes | Peer registry identifier. Used in `import … from registry "…"` declarations. |
| `endpoint` | Yes | Base URL of the peer's Registry API. |
| `sync` | No | `eager`, `lazy` (default), or `pinned`. |

A workspace without a `registry` block operates in **local mode**: lineage is stored only in `lineage.db` (no log files, no peer syncs). This is the default for single-team workspaces and requires no migration.

### 5.2 `import domain` Declaration

The `import domain` declaration makes a foreign domain available within the current workspace's `.mdl` files.

```mdl
import domain orders   from registry "orders-registry"
import domain customer from registry "customer-platform-registry"
```

Import declarations appear at the top of any `.mdl` file that uses a foreign domain, before any `domain`, `projection`, or `binding` block.

After an import, the foreign domain's models are referenceable using the standard `domain.Model@version` syntax and the `ref<domain.Model>` type.

A pinned import (for audit and reproducibility) includes the content signature:

```mdl
import domain customer from registry "customer-platform-registry"
  at customer.Customer@3#a3f8b2c1d4e5f6a7
```

The `at` clause pins the import to a specific model version and signature. The compiler rejects the import if the fetched model does not match the declared signature.

### 5.3 Content Signature in Cross-Domain References

When a projection or model field references a foreign model, the content signature may be appended to strengthen the dependency:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
{
  billingCustomerId  <- c.customerId
  invoiceEmail       <- c.email
}
```

The `#` suffix is optional in authoring but is always written by the compiler into generated plan documents and lineage records.

---

## 6. CLI Extensions

### 6.1 Registry Management

```bash
# Initialise this workspace as a named registry node
modellable registry init --id "billing-registry" --owns billing

# Add a peer registry
modellable registry peer add \
  --id "customer-platform-registry" \
  --endpoint "https://reg.customer-platform.example.com" \
  --sync lazy

# List known peers and their sync state
modellable registry peers

# Sync (re-mirror) all foreign domains from their owning peers
modellable registry sync

# Sync a specific domain
modellable registry sync --domain customer
```

### 6.2 Lineage Verification

```bash
# Verify the full lineage chain for a projection or model
# Re-computes content signatures and checks the hash chain in the log
modellable lineage verify billing.BillingCustomer@1

# Cross-registry lineage: show upstream and downstream across all known nodes
modellable lineage billing.BillingCustomer@1 --cross-registry

# Show all downstream dependents of a model, including foreign registries
modellable lineage customer.Customer@2 --downstream --cross-registry
```

Sample output of `modellable lineage verify billing.BillingCustomer@1`:

```
billing.BillingCustomer@1 — lineage verification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  billingCustomerId  [direct]
    customer.Customer@2.customerId
    ✓ signature a3f8b2c1d4e5f6a7 matches cached mirror

  invoiceEmail  [direct]
    customer.Customer@2.email
    ✓ signature a3f8b2c1d4e5f6a7 matches cached mirror

  isBillable  [computed]  customer.status == "active"
    customer.Customer@2.status
    ✓ signature a3f8b2c1d4e5f6a7 matches cached mirror

  totalSpent  [aggregation]  sum(orders.Order@3.totalAmount)
    orders.Order@3.totalAmount
    ✓ signature f9d2e1b3a4c5d6e7 matches cached mirror

Hash chain integrity: ✓  (12 events, no gaps)
Cross-registry edges: 2  (customer-platform-registry, orders-registry)
```

### 6.3 Lineage Log Export

```bash
# Export lineage log as NDJSON for ingestion into an external catalog
modellable lineage export --format ndjson --output lineage-export.ndjson

# Export only cross-registry edges
modellable lineage export --format ndjson --cross-registry-only

# Replay the log into a fresh lineage.db (disaster recovery)
modellable lineage rebuild
```

---

## 7. Failure Modes and Resilience

| Failure scenario | System behaviour |
| :--- | :--- |
| Registry node disk failure | Rebuild `registry.db` from `.mdl` files and `lineage.db` from `lineage-log/` (both in source control). Foreign mirror data is re-fetched from peers on next compile. |
| Peer registry unreachable at compile time | Use cached `mirror.db` replica. Compilation succeeds. A warning is logged. |
| Peer registry unreachable for lineage push | Queue the `CrossRegistryRef` event locally. Retry with exponential backoff. Full local lineage remains complete. |
| Content signature mismatch on mirror fetch | Compilation fails with an integrity error. The cached replica is kept but flagged as unverified. The operator must investigate. |
| `lineage-log/` directory deleted | Lineage history is lost. `lineage.db` cannot be rebuilt. `registry.db` and compiled artifacts remain intact. Mitigation: commit `lineage-log/` to git or back up to object storage. |
| Split-brain (two nodes claim to own the same domain) | The compiler rejects the configuration at validate time. Domain ownership must be declared in exactly one `registry.owns` list per federation. |
| Event deduplication conflict | `eventId` uniqueness is enforced on log replay. Duplicate events are skipped and logged. |

---

## 8. Security Considerations

### 8.1 Peer Authentication

Requests between registry nodes must be authenticated. Supported mechanisms:

- **Mutual TLS (mTLS):** Each node presents a client certificate. Recommended for production.
- **Shared bearer token:** Simpler for intranet deployments.
- **No auth:** Permitted only for local development (`endpoint: "http://localhost:…"`).

The `peers` declaration accepts an optional `auth` field:

```mdl
peers: [
  {
    id:       "orders-registry"
    endpoint: "https://reg.orders.example.com"
    sync:     lazy
    auth:     "mtls"
  }
]
```

### 8.2 Signature Pinning

Pinning content signatures in `import … at …` declarations provides a supply-chain integrity guarantee equivalent to hash-pinning in package managers (e.g., `go.sum`, npm lockfiles). Pinning should be enforced in CI pipelines that validate model definitions.

### 8.3 Lineage Log Tamper Detection

The Merkle hash chain allows any party with the log to detect:

- **Inserted events:** The chain breaks at the insertion point.
- **Deleted events:** A gap in `prevHash` references is detected.
- **Modified events:** The `eventHash` of the modified event no longer matches its content.

Detection requires a known-good checkpoint hash. Nodes should publish checkpoint hashes out-of-band (e.g., in a shared git commit or a transparency log) to enable independent verification.

---

## 9. Migration Path

### 9.1 Single-Node Workspace (No Change)

A workspace without a `registry` block continues to work exactly as before. No migration is required. All lineage is stored in `lineage.db` only. `lineage-log/` is not created.

### 9.2 Enabling the Event Log on an Existing Single-Node Workspace

1. Add a `registry { id: "…" owns: ["…"] }` block to `workspace.mdl`.
2. Run `modellable compile`. The compiler creates `lineage-log/` and backfills one `FieldMapped` event per existing lineage edge (with `timestamp` set to the compilation time and `prevHash: null` for the first entry).
3. Commit `.modellable/lineage-log/` to source control.

### 9.3 Splitting a Single Registry into Multiple Nodes

1. Create separate workspace directories for each owning team.
2. Add `registry` blocks declaring ownership and peer references.
3. Add `import domain` declarations in projection files that reference foreign domains.
4. Run `modellable compile` on each workspace. The compiler syncs foreign models and re-resolves lineage.
5. Distribute the `lineage-log/` export to each new node as the historical baseline.

---

## 10. Example Lineage Record (Distributed Form)

A field mapping that crosses registry boundaries produces the following lineage record in `lineage.db`:

| Column | Value |
| :--- | :--- |
| `target_model` | `billing.BillingCustomer` |
| `target_version` | `1` |
| `target_field` | `invoiceEmail` |
| `source_model` | `customer.Customer` |
| `source_version` | `2` |
| `source_field` | `email` |
| `kind` | `direct` |
| `source_content_signature` | `a3f8b2c1d4e5f6a7` |
| `is_cross_registry` | `true` |
| `source_registry_id` | `customer-platform-registry` |
| `event_hash` | `7f3a9b2c1d4e5f6a` |

And the corresponding event in the log file:

```json
{
  "eventId": "01906c3e-8b2a-7f4d-a9c1-3e5f8d2b4a1c",
  "eventType": "CrossRegistryRef",
  "timestamp": "2026-05-14T10:23:45.123456Z",
  "registryId": "billing-registry",
  "eventHash": "7f3a9b2c1d4e5f6a8b9c0d1e2f3a4b5c",
  "prevHash": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d",
  "payload": {
    "projectionRef": "billing.BillingCustomer@1",
    "projectionRegistry": "billing-registry",
    "targetField": "invoiceEmail",
    "sourceRef": "customer.Customer@2.email",
    "sourceRegistry": "customer-platform-registry",
    "sourceModelSignature": "a3f8b2c1d4e5f6a7"
  }
}
```
