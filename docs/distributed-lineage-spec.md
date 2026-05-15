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

This spec defines a **Federated Registry Network** where every registry is a node in a directed dependency graph, each node is a git repository, and the CLI owns graph traversal and sync automatically at compile time. Git provides tamper-evidence, temporal history, and replication for free. No running server is required for dev-time use.

---

## 1. Design Goals

1. **No central authority.** Any registry node can be lost and the system continues from surviving nodes and local mirrors.
2. **No server required at dev time.** The only infrastructure is a git remote — one every team already has.
3. **CLI-owned sync.** `modelable compile` resolves the graph, fetches foreign models, compiles, and writes back consumer registrations. No manual sync step.
4. **Every node is both producer and consumer.** A repo that owns domain A and imports domain B is a master for A and a slave to B simultaneously. The graph has no fixed hierarchy.
5. **Tamper-evident lineage via git.** Git's content-addressed object model provides integrity guarantees. No separate hash chain needed.
6. **Single derived database.** One `registry.db` is built from all sources. Deleting it and recompiling always reproduces the same result.
7. **Incremental adoption.** A workspace without a `registry` block continues to work exactly as before.

---

## 2. Core Concepts

### 2.1 Registry Node

A registry node is a **git repository** containing `.mdl` source files, a `workspace.mdl` that declares its identity and peer edges, and a `.modelable/` build output directory.

A node:

- **Owns** one or more domains — authoritative source for those domains' model versions, compatibility history, and access policies.
- **Imports** foreign domains from peer nodes — the CLI fetches these via `git fetch` into a local `mirror/` directory.
- **Writes back** to peer repos — consumer registration entries flow back to upstream repos at compile time, recording who depends on what.

A node does **not** modify foreign domain definitions or override another node's access policies.

### 2.2 The Registry Graph

Every federation is a **directed acyclic graph (DAG)** of registry nodes. An edge `A → B` means A imports at least one domain from B. A node can have both incoming and outgoing edges; there is no global root.

```
iam-registry            (master: iam)
      ↓
customer-registry       (master: customer    slave: iam)
      ↓           ↘
orders-registry         (master: orders      slave: customer)
      ↓
analytics-registry      (master: analytics   slave: customer + orders)
```

Cycles are a hard error caught at compile time by topological sort.

### 2.3 Content-Addressed Model Signature

Every published model version receives a deterministic **content signature** — a SHA-256 hash computed over the canonical form of the model definition.

**Canonical form** covers:

- Domain name, model name, and kind (`entity`, `aggregate`, `event`, `value`).
- Version number and `changeKind`.
- All field definitions (names, types, annotations, optionality), sorted by field name.

The signature is stored in `registry.db` alongside the version and written into plan documents and all cross-registry references.

**Fully qualified model reference with signature:**

```
customer.Customer@3#a3f8b2c1d4e5f6a7
```

The short form is valid for local references. The compiler always writes the `#hash` suffix into plan documents and lineage records.

### 2.4 Consumer Registration

When the compiler resolves a cross-registry field mapping it writes a small MDL file into the **upstream** repo's `consumers/` directory:

```
<upstream-repo>/
  consumers/
    analytics-registry/
      CustomerOrderSummary@1.mdl
```

This file declares the dependency from the upstream repo's perspective. The upstream team reads `consumers/` to understand their downstream blast radius — no catalog query required. Git history records when each entry was added or updated.

---

## 3. CLI Graph Traversal

The CLI owns all sync. The developer only runs `modelable compile`.

### 3.1 Steps on Every `compile`

1. **Parse `workspace.mdl`** — read the `registry` block and `peers` list.
2. **Resolve imports** — collect all `import domain … from registry "…"` statements across every `.mdl` file.
3. **Build the dependency subgraph** — adjacency list of all reachable nodes.
4. **Topological sort + cycle detection** — abort with a clear error naming any cycle.
5. **Sync peers in dependency order** — for each peer: `git fetch <remote>`, sparse-checkout `.mdl` files into `.modelable/mirror/<peer-id>/`.
6. **Verify pinned signatures** — for any `at Model@v#hash`, recompute the hash of the fetched model and reject on mismatch.
7. **Compile owned domains** — build `registry.db` from local `.mdl` files.
8. **Compile projections** — resolve foreign field references against `mirror/`.
9. **Write lineage into `registry.db`** — record `lineage_edges` for every resolved field mapping.
10. **Write consumer entries** — for each new cross-registry edge, write `consumers/<this-registry-id>/<Projection>@<v>.mdl` into the peer's working copy.
11. **Push write-backs** — commit and push (or open a PR) the consumer entries to each peer remote, controlled by the `writeback` field.

Git provides the audit trail (commit history), tamper evidence (SHA chain), and replication (remotes) for all of this. No separate event log is needed.

### 3.2 Cycle Detection

```
error: circular registry dependency detected
  analytics-registry → orders-registry → analytics-registry
  Break the cycle by removing one of these import declarations.
```

### 3.3 Peer Graph Visualisation

```bash
modelable registry graph
```

```
iam-registry              git@github.com:acme/iam-models.git         ✓ synced 2m ago
  └─ customer-registry    git@github.com:acme/customer-models.git    ✓ synced 2m ago
       ├─ orders-registry git@github.com:acme/orders-models.git      ✓ synced 1m ago
       │    └─ (this)     analytics-registry
       └─ (this)          analytics-registry
```

---

## 4. Storage Layout

```
<workspace>/                         # source-controlled
  workspace.mdl
  *.mdl
  consumers/
    <peer-registry-id>/
      <Projection>@<v>.mdl           # written by peer compilers (two-way write-back)

.modelable/                         # build artifacts — gitignore everything except noted
  registry.db                        # single derived database (see Section 4.1)
  mirror/
    <peer-registry-id>/              # sparse checkout of peer .mdl files
      *.mdl
  plans/
    <domain>.<Model>.v<n>.plan.json
  artifacts/
    <domain>/
      <Model>.v<n>.json
      <Model>.v<n>.ts
      <Model>.v<n>.md
```

**Sources of truth that must be committed to git:**

- All `.mdl` files (local domain definitions).
- `consumers/` entries (incoming write-backs from downstream registries).

Everything under `.modelable/` is a build artifact and can be regenerated by running `modelable compile`.

### 4.1 `registry.db` Schema

One database holds all derived data. The existing tables are unchanged. Distributed mode adds:

**New tables:**

| Table | Key columns | Purpose |
| :--- | :--- | :--- |
| `registry_peers` | `peer_id`, `git_remote`, `branch`, `sync_mode`, `writeback_mode`, `last_fetched_at`, `last_git_sha` | Declared peer nodes and their last sync state. |
| `mirrored_model_versions` | `domain`, `model`, `version`, `content_signature`, `raw_mdl`, `peer_id`, `git_sha` | Cached foreign model versions with integrity proofs. |
| `consumers` | `source_model`, `source_version`, `consumer_registry`, `consumer_projection`, `consumer_version`, `registered_at` | Downstream dependents derived from `consumers/` directory. |

**Additions to `lineage_edges`:**

| Column | Type | Description |
| :--- | :--- | :--- |
| `source_content_signature` | `text` | Content hash of the source model version at mapping time. |
| `is_cross_registry` | `boolean` | True when source and target are owned by different nodes. |
| `source_registry_id` | `text?` | Owning node of the source model (null for local). |

### 4.2 Rebuild Guarantee

`registry.db` and `mirror/` are fully rebuildable by running `modelable compile` from:

- Local `.mdl` source files.
- `consumers/` directory (committed to git).
- Peer git remotes (fetched on demand).

No other artifact needs to be backed up or committed.

---

## 5. IDL

See [idl-design-spec.md](idl-design-spec.md) Section 6 for the full IDL syntax. Summary:

**`workspace.mdl` with federation:**

```mdl
workspace "analytics-platform" {
  registry {
    id:   "analytics-registry"
    owns: ["analytics"]
  }

  peers: [
    { id: "customer-platform-registry", git: "git@github.com:acme/customer-models.git", sync: eager, writeback: pr     },
    { id: "orders-registry",            git: "git@github.com:acme/orders-models.git",   sync: eager, writeback: commit }
  ]
}
```

**Import declaration (in any `.mdl` file using a foreign domain):**

```mdl
import domain customer from registry "customer-platform-registry"
  at customer.Customer@3#a3f8b2c1d4e5f6a7
```

**Content signature in projection references:**

```mdl
projection BillingCustomer @ 1
  from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
{ ... }
```

**Consumer entry (written by the CLI, committed to the upstream repo):**

```mdl
consumer {
  registry:   "analytics-registry"
  projection: "analytics.CustomerOrderSummary@1"
  uses: ["customer.Customer@3#a3f8b2c1d4e5f6a7"]
  registeredAt: "2026-05-14T09:05:00Z"
}
```

---

## 6. CLI Reference

### 6.1 `modelable compile`

Handles the full graph traversal, sync, compile, and write-back automatically.

```bash
modelable compile           # full cycle
modelable compile --dry-run # show what would be synced and written back
```

### 6.2 Registry Management

```bash
modelable registry init --id "analytics-registry" --owns analytics

modelable registry peer add \
  --id  "customer-platform-registry" \
  --git "git@github.com:acme/customer-models.git" \
  --sync eager \
  --writeback pr

modelable registry graph    # print the DAG with sync state
modelable registry sync     # force-sync all peers regardless of sync mode
modelable registry sync --peer customer-platform-registry
```

### 6.3 Lineage Commands

```bash
# Show lineage for a model or projection
modelable lineage analytics.CustomerOrderSummary@1

# Show all downstream consumers (reads consumers/ across the workspace)
modelable dependents customer.Customer@3

# Verify content signatures against cached mirrors
modelable lineage verify analytics.CustomerOrderSummary@1

# Export lineage as NDJSON for external catalog ingestion (reads registry.db)
modelable lineage export --format ndjson --output lineage-export.ndjson
```

Sample output of `modelable lineage verify analytics.CustomerOrderSummary@1`:

```
analytics.CustomerOrderSummary@1 — lineage verification
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  customerId      [direct]      customer.Customer@3.customerId
                                ✓ #a3f8b2c1 matches mirror (git sha abc123)

  email           [direct]      customer.Customer@3.email
                                ✓ #a3f8b2c1 matches mirror (git sha abc123)

  totalSpentCents [aggregation] sum(orders.Order@3.totalAmountCents)
                                ✓ #f9d2e1b3 matches mirror (git sha def456)

Cross-registry edges: 2  (customer-platform-registry, orders-registry)
```

---

## 7. Failure Modes and Resilience

| Failure scenario | System behaviour |
| :--- | :--- |
| Registry node disk failure | Rebuild `registry.db` and `mirror/` by running `modelable compile`. All source of truth is in git. |
| Peer git remote unreachable at compile time | Use cached `mirror/`. Compilation succeeds with a warning if mirror exists; fails with a clear error if no mirror and `sync` is not `pinned`. |
| Content signature mismatch on mirror fetch | Compilation fails with an integrity error. Cached mirror is kept but flagged. Investigate whether the upstream model was legitimately republished. |
| `consumers/` directory deleted | Re-generated on the next `modelable compile` by write-back from downstream registries. Historical entries recoverable from git history. |
| Split-brain (two nodes claim to own the same domain) | `modelable compile` detects the conflict during graph resolution and aborts. |
| Cycle in the dependency graph | `modelable compile` detects the cycle during topological sort and aborts, naming the cycle. |
| Write-back push rejected by peer remote | Consumer entry is staged locally and a warning is printed. The developer resolves the push conflict or opens a PR manually. |

---

## 8. Security

### 8.1 Peer Authentication

Authentication uses the host machine's git credential configuration — SSH keys, HTTPS tokens, or git credential helpers. No additional auth configuration in `workspace.mdl`. Access control is enforced by the git hosting provider using mechanisms teams already manage.

### 8.2 Write-back Permissions

`writeback: commit` requires write access to the peer remote. `writeback: pr` requires only read access to fetch; the PR is opened via the git hosting API using `GH_TOKEN` / `GITLAB_TOKEN`.

### 8.3 Signature Pinning

Pinning content signatures in `import … at …` is equivalent to hash-pinning in `go.sum` or `package-lock.json`. Enforce in CI:

```bash
modelable validate --require-pinned-imports
```

### 8.4 Tamper Evidence

Git's SHA chain covers all `.mdl` source files and `consumers/` entries. Any modification to a committed model definition changes the commit SHA and is immediately visible in `git log`. The content signature stored in `registry.db` provides a second layer: the compiler detects if a mirrored model's content no longer matches its recorded signature.

---

## 9. Migration Path

### 9.1 Single-Node Workspace (No Change)

No `registry` block → local mode. No migration needed.

### 9.2 Enabling Federation on an Existing Workspace

1. Add `registry { id: "…" owns: ["…"] }` to `workspace.mdl`.
2. Add `peers` entries for each upstream dependency.
3. Add `import domain` declarations to projection files.
4. Run `modelable compile`. The CLI fetches mirrors and writes consumer entries.
5. Commit `consumers/` to source control.

### 9.3 Splitting a Monorepo into Multiple Nodes

1. Create separate git repositories per owning team; move domain `.mdl` files.
2. Add `registry` and `peers` blocks to each `workspace.mdl`.
3. Add `import domain` declarations for cross-team references.
4. Run `modelable compile` on each workspace to wire up mirrors and consumer write-backs.

---

## 10. Example: Two-Way Binding in Practice

```
modelable compile  (analytics-registry)

  → parse workspace.mdl
  → build graph: analytics → customer, analytics → orders
  → topological order: [customer, orders, analytics]
  → git fetch git@github.com:acme/customer-models.git main
      mirror/customer-platform-registry/ updated  (git sha abc123)
  → git fetch git@github.com:acme/orders-models.git main
      mirror/orders-registry/ updated  (git sha def456)
  → verify: customer.Customer@3#a3f8b2c1 ✓   orders.Order@3#f9d2e1b3 ✓
  → compile analytics.CustomerOrderSummary@1
  → write lineage_edges in registry.db  (cross-registry = true)
  → write consumers/analytics-registry/CustomerOrderSummary@1.mdl
      staged in mirror/customer-platform-registry/  →  PR opened (writeback: pr)
      staged in mirror/orders-registry/             →  pushed    (writeback: commit)
  → compile complete
```

The customer team now sees `consumers/analytics-registry/CustomerOrderSummary@1.mdl` in their own repo via the merged PR. When they plan `customer.Customer@4 (breaking)`, `modelable dependents customer.Customer@3` lists the analytics projection, and CI can gate the breaking version on the analytics team updating their pinned import.
