# Design: Distributed Data Lineage and Federated Registry

**Date:** 2026-05-14  
**Status:** Approved  
**Scope:** Eliminating the single point of failure in the registry and lineage store; enabling cross-team, cross-repository data lineage without a central authority or any running server infrastructure

---

## Context

The baseline architecture stores all domain models, lineage edges, and compatibility metadata in a single `registry.db` SQLite file. This creates several single points of failure:

- **Storage SPOF:** One corrupt or missing file destroys all lineage metadata.
- **Ownership SPOF:** One repository and one team control all domain definitions. Cross-team contribution requires central coordination.
- **Availability SPOF:** Downstream projections cannot be validated if the single registry is unavailable.
- **Integrity gap:** Cross-domain references carry only a logical name and version number; there is no mechanism to verify that the referenced model is the one that was originally depended on.

This spec defines a **Federated Registry Network** where every registry is a node in a directed dependency graph, the transport between nodes is plain git, and the CLI owns graph traversal and sync automatically at compile time. No running server is required for dev-time use.

---

## 1. Design Goals

1. **No central authority.** Any registry node can be lost and the system continues operating from the remaining nodes and local caches.
2. **No server required at dev time.** The only infrastructure needed is a git remote — the same one every team already has.
3. **CLI-owned sync.** The developer runs `modellable compile`. The CLI resolves the dependency graph, fetches foreign models, compiles, and writes back lineage. No manual sync step.
4. **Every node is both producer and consumer.** A repo that owns domain A and imports domain B is a master for A and a slave to B simultaneously. The graph has no fixed hierarchy.
5. **Tamper-evident lineage.** Lineage chains are verifiable without querying the original registry.
6. **Incremental adoption.** A single-node workspace is a degenerate case of the graph and requires no new configuration.

---

## 2. Core Concepts

### 2.1 Registry Node

A registry node is a **git repository** containing `.mdl` source files, a `workspace.mdl` that declares its identity and peer edges, and a `.modellable/` output directory.

A node:

- **Owns** one or more domains — it is the authoritative source for those domains' model versions, compatibility history, and access policies.
- **Imports** foreign domains from peer nodes — the compiler fetches these via `git fetch` into a local `mirror/` directory.
- **Writes back** to peer repos at compile time — consumer registration entries and lineage events flow back to the repos they depend on.

A node does **not**:

- Modify foreign domain definitions.
- Override another node's access policies.
- Require a running HTTP service for dev-time compilation.

### 2.2 The Registry Graph

Every federation is a **directed acyclic graph (DAG)** of registry nodes. An edge `A → B` means A imports at least one domain from B.

A node can have both incoming and outgoing edges. Owning domain X and importing domain Y makes a node simultaneously a master (for X) and a slave (to Y). There is no global root.

```
iam-registry            (master: iam)
      ↓
customer-registry       (master: customer    slave: iam)
      ↓           ↘
orders-registry         (master: orders      slave: customer)
      ↓
analytics-registry      (master: analytics   slave: customer + orders)
```

`customer-registry` is a master to `orders` and `analytics`, a slave to `iam`. Cycles are a hard error detected at compile time.

### 2.3 Content-Addressed Model Signature

Every published model version receives a deterministic **content signature** — a SHA-256 hash computed over the canonical form of the model definition.

**Canonical form** covers:

- Domain name.
- Model name and kind (`entity`, `aggregate`, `event`, `value`).
- Version number and `changeKind`.
- All field definitions (names, types, annotations, optionality), sorted by field name.

The signature is stored on the `model_versions` table and written into `mirror/` files and plan documents.

**Fully qualified model reference with signature:**

```
customer.Customer@3#a3f8b2c1d4e5f6a7
```

The short form is valid for local references. The hash suffix is written by the compiler into all cross-registry references, plan documents, and lineage events.

### 2.4 Lineage Event Log

Each registry node maintains an **append-only lineage event log** — NDJSON files in `.modellable/lineage-log/`, one per day. The log is committed to the same git repository as the `.mdl` source files.

The log is the durable source of truth. `lineage.db` is a derived index rebuilt from it by `modellable compile`, exactly like `registry.db` is rebuilt from `.mdl` files.

**Event types:**

| Event type | When emitted |
| :--- | :--- |
| `ModelPublished` | A model version is published. |
| `ProjectionPublished` | A projection version is published. |
| `FieldMapped` | The compiler resolves a field mapping within this registry. |
| `CrossRegistryRef` | A field mapping spans two different registry nodes. |
| `ForeignModelMirrored` | The compiler fetched and cached a foreign model. |
| `ConsumerRegistered` | This node wrote a consumer entry to a peer repo. |
| `ModelDeprecated` | A model version is deprecated. |

**Common envelope fields:**

| Field | Type | Description |
| :--- | :--- | :--- |
| `eventId` | `uuid` | Unique identifier. |
| `eventType` | `string` | One of the types above. |
| `timestamp` | `timestamp` | UTC time of emission. |
| `registryId` | `string` | Emitting registry node identifier. |
| `eventHash` | `string` | SHA-256 of the canonical JSON of this event (excluding `eventHash`). |
| `prevHash?` | `string` | Hash of the previous event in this log, forming a hash chain. |

### 2.5 Merkle Hash Chain

Events in a single registry's log form a Merkle hash chain via `prevHash`. Any insertion, deletion, or modification of a past event breaks the chain and is detectable by recomputing from a known checkpoint.

Cross-registry lineage forms a content-addressed DAG: each `CrossRegistryRef` event embeds the source model's content signature, so the lineage chain is verifiable without contacting the upstream registry.

### 2.6 Consumer Registration

When the compiler resolves a cross-registry field mapping it writes a small MDL file into the upstream peer's `consumers/` directory:

```
<peer-repo>/
  consumers/
    analytics-registry/
      CustomerOrderSummary@1.mdl
```

This file declares the dependency from the upstream repo's perspective. The upstream team sees their dependents by reading their own `consumers/` directory — no central catalog query required.

The upstream team can gate breaking changes behind all `consumers/` entries being updated to the new version before the breaking model version is merged.

---

## 3. CLI Graph Traversal

The CLI owns sync entirely. The developer only ever runs `modellable compile`.

### 3.1 Steps on Every `compile`

1. **Parse workspace.mdl** — read the node's `registry` block and `peers` list.
2. **Resolve import declarations** — collect all `import domain … from registry "…"` statements across all `.mdl` files in the workspace.
3. **Build the dependency subgraph** — construct the adjacency list of nodes reachable from this workspace via import edges.
4. **Topological sort** — order nodes so every dependency is synced before the node that needs it.
5. **Cycle detection** — if a cycle exists, abort with a clear error naming the cycle.
6. **Sync in order** — for each peer in dependency order: `git fetch <remote>`, sparse-checkout the peer's `.mdl` files and `lineage-log/` into `mirror/<peer-id>/`.
7. **Verify signatures** — for any pinned import (`at Model@v#hash`), recompute the hash of the fetched model and reject on mismatch.
8. **Compile owned domains** — build `registry.db` from local `.mdl` files as normal.
9. **Compile projections** — resolve foreign field references against `mirror/`.
10. **Write lineage events** — append `FieldMapped` and `CrossRegistryRef` events to today's log file.
11. **Write consumer entries** — for each new cross-registry edge, write the `consumers/<this-registry-id>/<Projection>@<v>.mdl` file into the peer's working copy (staged, not yet pushed).
12. **Push write-backs** — commit and push the consumer entries to the relevant peer remotes (or open a PR if the peer requires review — controlled by `writeback: commit | pr`).

Steps 11–12 are the **two-way binding**: git is both the source (pull) and the sink (push) for registry metadata.

### 3.2 Cycle Detection

The compiler uses Kahn's algorithm over the peer graph. A cycle produces an error like:

```
error: circular registry dependency detected
  analytics-registry → orders-registry → analytics-registry
  Break the cycle by removing one of these import declarations.
```

### 3.3 Peer Graph Visualisation

```bash
modellable registry graph
```

Prints the DAG of all reachable peers with sync state and last-fetched timestamps:

```
iam-registry              git@github.com:acme/iam-models.git         ✓ synced 2m ago
  └─ customer-registry    git@github.com:acme/customer-models.git    ✓ synced 2m ago
       ├─ orders-registry git@github.com:acme/orders-models.git      ✓ synced 1m ago
       │    └─ (this)     analytics-registry
       └─ (this)          analytics-registry
```

---

## 4. IDL Changes

### 4.1 `registry` Block in `workspace.mdl`

The `registry` block declares this workspace as a named node and lists peer nodes by git remote.

```mdl
workspace "analytics-platform" {
  description: "Analytics registry — projects across customer and orders."

  registry {
    id:   "analytics-registry"
    owns: ["analytics"]
  }

  peers: [
    {
      id:        "customer-platform-registry"
      git:       "git@github.com:acme/customer-models.git"
      branch:    "main"
      sync:      eager
      writeback: pr
    },
    {
      id:        "orders-registry"
      git:       "git@github.com:acme/orders-models.git"
      branch:    "main"
      sync:      eager
      writeback: commit
    }
  ]

  generate {
    docs         -> "./generated/docs/"
    typescript   -> "./generated/types/"
    jsonschema   -> "./generated/jsonschema/"
  }
}
```

**`registry` block fields:**

| Field | Required | Description |
| :--- | :--- | :--- |
| `id` | Yes | Stable unique name for this node. Used as `registryId` in lineage events and as the directory name in peer `consumers/` trees. |
| `owns` | Yes | Domains this node is authoritative for. |

**`peers` entry fields:**

| Field | Required | Description |
| :--- | :--- | :--- |
| `id` | Yes | Peer registry identifier. Matches the peer's own `registry.id`. |
| `git` | Yes | Git remote URL. The compiler runs `git fetch` against this remote. |
| `branch` | No | Branch to track (default: `main`). |
| `sync` | No | `eager` — sync on every `compile`; `lazy` — sync on first reference; `pinned` — never sync, use local mirror only. Default: `lazy`. |
| `writeback` | No | `commit` — push consumer entries directly; `pr` — open a pull request; `none` — skip write-back. Default: `commit`. |

A workspace without a `registry` block operates in **local mode** — no sync, no write-back, lineage stored only in `lineage.db`. This is the default for single-team workspaces.

### 4.2 `import domain` Declaration

Placed at the top of any `.mdl` file that references a foreign domain:

```mdl
import domain customer from registry "customer-platform-registry"
import domain orders   from registry "orders-registry"
```

A pinned import locks to a specific model version and content signature:

```mdl
import domain customer from registry "customer-platform-registry"
  at customer.Customer@3#a3f8b2c1d4e5f6a7
```

The compiler rejects the import if the fetched model does not hash to the declared value.

### 4.3 Content Signature Suffix in References

Any `from … @` version reference may include `#<hash>` to pin to a specific content:

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
{
  billingCustomerId  <- c.customerId
  invoiceEmail       <- c.email
}
```

The `#` suffix is optional in hand-authored files. The compiler always writes it into plan documents and lineage records.

---

## 5. Storage Layout (Distributed Mode)

```
<workspace>/
  workspace.mdl
  <domain files>.mdl
  consumers/
    <peer-registry-id>/
      <Projection>@<v>.mdl        # written here by peer compilers (two-way write-back)

.modellable/
  registry.db                     # owned domains — derived from .mdl files
  mirror/
    customer-platform-registry/   # sparse checkout of peer's .mdl files
      customer.mdl
      lineage-log/
        2026-05-14.ndjson
    orders-registry/
      orders.mdl
      lineage-log/
        2026-05-14.ndjson
  lineage.db                      # lineage index — derived from lineage-log/
  lineage-log/
    2026-05-14.ndjson             # append-only (source of truth for this node)
  plans/
    analytics.CustomerOrderSummary.v1.plan.json
  artifacts/
    analytics/
      CustomerOrderSummary.v1.json
      CustomerOrderSummary.v1.ts
```

### 5.1 `mirror/` Directory

The `mirror/` directory is a read-only snapshot of each peer's `.mdl` files and lineage log, written by the CLI during sync. It is a build artifact — never edited by hand, fully rebuildable by re-running `modellable compile` (subject to peer availability).

### 5.2 `mirror.db` Schema

| Table | Key columns | Purpose |
| :--- | :--- | :--- |
| `registry_peers` | `peer_id`, `git_remote`, `branch`, `sync_mode`, `writeback_mode` | Declared peer nodes. |
| `mirrored_domains` | `domain`, `peer_id`, `fetched_at`, `git_sha` | Which foreign domains are cached and at what git SHA. |
| `mirrored_model_versions` | `domain`, `model`, `version`, `content_signature`, `raw_mdl` | Cached foreign model versions with integrity proofs. |

### 5.3 `lineage_edges` Schema (additions)

| Column | Type | Description |
| :--- | :--- | :--- |
| `source_content_signature` | `text` | Content hash of the source model version at mapping time. |
| `is_cross_registry` | `boolean` | True when source and target are owned by different nodes. |
| `source_registry_id` | `text?` | Owning node of the source model (null for local). |
| `event_hash` | `text` | Hash of the originating lineage event. |

### 5.4 `consumers/` Directory

The `consumers/` directory holds incoming write-backs from downstream registries. Each entry is a small MDL file declaring the dependency:

```mdl
// consumers/analytics-registry/CustomerOrderSummary@1.mdl
// Written by analytics-registry compiler during modellable compile.
// Do not edit by hand.

consumer {
  registry:   "analytics-registry"
  projection: "analytics.CustomerOrderSummary@1"
  uses: [
    "customer.Customer@3#a3f8b2c1d4e5f6a7"
  ]
  registeredAt: "2026-05-14T09:05:00Z"
}
```

Ownership teams use this directory to understand their downstream blast radius:

```bash
modellable dependents customer.Customer@3
# reads consumers/ recursively across the workspace
```

### 5.5 Rebuild Guarantee

Deleting all derived files (`.db` files, `mirror/`, `artifacts/`) and re-running `modellable compile` must produce an identical result, subject to peer availability. The only sources of truth that must be preserved are:

- `.mdl` source files (including `consumers/`).
- `.modellable/lineage-log/` NDJSON files.

Both must be committed to the repository's git history.

---

## 6. CLI Reference

### 6.1 `modellable compile`

The primary command. No flags needed for sync — the CLI resolves the graph automatically.

```bash
modellable compile
```

Internally: build graph → topological sort → cycle check → sync peers in order → compile → write lineage → write-back consumer entries.

Add `--dry-run` to preview what would be synced and written back without making any changes.

### 6.2 Registry Management

```bash
# Declare this workspace as a registry node
modellable registry init --id "analytics-registry" --owns analytics

# Add a peer (writes the peers entry into workspace.mdl)
modellable registry peer add \
  --id  "customer-platform-registry" \
  --git "git@github.com:acme/customer-models.git" \
  --sync eager \
  --writeback pr

# Print the full dependency graph with sync state
modellable registry graph

# Force-sync all peers regardless of sync mode
modellable registry sync

# Force-sync a specific peer
modellable registry sync --peer customer-platform-registry
```

### 6.3 Lineage Commands

```bash
# Show lineage for a model or projection (cross-registry aware)
modellable lineage analytics.CustomerOrderSummary@1

# Show all downstream consumers across the graph
modellable lineage customer.Customer@3 --downstream

# Verify content signatures and hash chain integrity
modellable lineage verify analytics.CustomerOrderSummary@1

# List registered consumers of a model (reads consumers/ directory)
modellable dependents customer.Customer@3

# Export lineage log as NDJSON
modellable lineage export --format ndjson --output lineage-export.ndjson

# Rebuild lineage.db from the event log (disaster recovery)
modellable lineage rebuild
```

Sample output of `modellable lineage verify analytics.CustomerOrderSummary@1`:

```
analytics.CustomerOrderSummary@1 — lineage verification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  customerId     [direct]   customer.Customer@3.customerId
                            ✓ #a3f8b2c1 matches mirror (git sha abc123)

  email          [direct]   customer.Customer@3.email
                            ✓ #a3f8b2c1 matches mirror (git sha abc123)

  totalSpentCents [aggregation] sum(orders.Order@3.totalAmountCents)
                            ✓ #f9d2e1b3 matches mirror (git sha def456)

Hash chain integrity: ✓  (13 events, no gaps)
Cross-registry edges: 2  (customer-platform-registry, orders-registry)
```

---

## 7. Failure Modes and Resilience

| Failure scenario | System behaviour |
| :--- | :--- |
| Registry node disk failure | Rebuild `registry.db` from `.mdl` files and `lineage.db` from `lineage-log/` (git history). `mirror/` is rebuilt by re-running `compile`. |
| Peer git remote unreachable at compile time | Use cached `mirror/` snapshot. Compilation succeeds with a warning if mirror exists. Fails with a clear error if no mirror and sync is not `pinned`. |
| Content signature mismatch on mirror fetch | Compilation fails with an integrity error. Cached mirror is kept but flagged. The operator must investigate whether the upstream model was legitimately changed. |
| `lineage-log/` directory deleted | Lineage history is lost for this node. `registry.db` and compiled artifacts are intact. Mitigation: `lineage-log/` must be committed to git. |
| Split-brain (two nodes claim to own the same domain) | `modellable compile` detects the conflict during graph resolution and aborts with a clear error. |
| Cycle in the dependency graph | `modellable compile` detects the cycle during topological sort and aborts, naming the cycle. |
| Write-back push rejected by peer remote | The consumer entry is staged locally and a warning is printed. The developer must resolve the push conflict or open a PR manually. |
| Event deduplication conflict | `eventId` uniqueness is enforced on log replay. Duplicate events (e.g., from mirror merges) are skipped with a log entry. |

---

## 8. Security

### 8.1 Peer Authentication

Authentication to peer git remotes uses the host machine's normal git credential configuration — SSH keys, HTTPS tokens, or git credential helpers. No additional auth configuration is needed in `workspace.mdl`.

This means access control is enforced by the git hosting provider (GitHub, GitLab, etc.) using mechanisms teams already manage.

### 8.2 Write-back Permissions

For `writeback: commit`, the compiler needs write access to the peer remote. For `writeback: pr`, only read access is required to fetch; the PR is opened via the git hosting API using the standard `GH_TOKEN` / `GITLAB_TOKEN` environment variables.

### 8.3 Signature Pinning

Pinning content signatures in `import … at …` declarations is analogous to hash-pinning in `go.sum` or `package-lock.json`. It should be enforced in CI:

```bash
# CI step: verify no unsigned cross-registry imports exist
modellable validate --require-pinned-imports
```

### 8.4 Lineage Log Tamper Detection

The Merkle hash chain lets any party with the log detect insertions, deletions, or modifications by recomputing `eventHash` and `prevHash` from a known checkpoint. Checkpoint hashes can be embedded in git commit messages for out-of-band verification.

---

## 9. Migration Path

### 9.1 Single-Node Workspace (No Change)

A workspace without a `registry` block continues to work exactly as before. No migration needed.

### 9.2 Enabling the Event Log on an Existing Workspace

1. Add `registry { id: "…" owns: ["…"] }` to `workspace.mdl`.
2. Run `modellable compile`. The compiler creates `lineage-log/` and backfills one `FieldMapped` event per existing lineage edge.
3. Commit `.modellable/lineage-log/` to source control.

### 9.3 Splitting a Monorepo Registry into Multiple Nodes

1. Create a separate git repository per owning team and move the relevant `.mdl` files.
2. Add `registry` and `peers` blocks to each `workspace.mdl`.
3. Add `import domain` declarations in files that reference foreign domains.
4. Run `modellable compile` on each workspace. The CLI builds the graph, syncs mirrors, and writes consumer entries.
5. Use `modellable lineage export` from the original repo to seed the historical `lineage-log/` baseline in each new node.

---

## 10. Example: Two-Way Binding in Practice

When the analytics team runs `modellable compile` for the first time after publishing `CustomerOrderSummary@1`:

```
modellable compile
  → parse workspace.mdl
  → build graph: analytics → customer, analytics → orders
  → topological order: [customer, orders, analytics]
  → git fetch git@github.com:acme/customer-models.git main
      → mirror/customer-platform-registry/ updated (git sha abc123)
  → git fetch git@github.com:acme/orders-models.git main
      → mirror/orders-registry/ updated (git sha def456)
  → verify signatures: customer.Customer@3#a3f8b2c1 ✓  orders.Order@3#f9d2e1b3 ✓
  → compile analytics.CustomerOrderSummary@1
  → append to lineage-log/2026-05-14.ndjson:
      CrossRegistryRef  analytics.CustomerOrderSummary@1.email  ← customer.Customer@3.email
      CrossRegistryRef  analytics.CustomerOrderSummary@1.totalSpentCents ← orders.Order@3.totalAmountCents
      ... (one event per cross-registry field)
  → write consumers/analytics-registry/CustomerOrderSummary@1.mdl
      into mirror/customer-platform-registry/  (staged for push)
      into mirror/orders-registry/             (staged for push)
  → git push git@github.com:acme/customer-models.git  (writeback: commit)
  → open PR  git@github.com:acme/orders-models.git    (writeback: pr)
  → compile complete
```

The customer team now sees `consumers/analytics-registry/CustomerOrderSummary@1.mdl` in their own repo. When they plan `customer.Customer@4 (breaking)`, `modellable dependents customer.Customer@3` lists the analytics projection and CI can enforce that the analytics team has updated their projection before the breaking version is merged.
