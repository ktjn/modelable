# Ownership and Permissions Specification

## 1. Purpose

This specification defines how ownership and access permissions are declared on models, entities, and individual properties within Modelable, and how those declarations remain authoritative when model definitions or derived artifacts are transferred to external systems.

Ownership and permissions are first-class metadata on definitions, not runtime-only policies. They travel with the model artifact so that any system consuming a Modelable-exported schema retains the original access intent without requiring a live connection to the Modelable registry.

## 2. Design Principles

### 2.1 Ownership Is Declared, Not Inferred

Every model must declare an explicit owner. Properties may optionally declare their own owner when they differ from the model owner—for example, a field contributed by a different domain or a computed field maintained by a different team.

### 2.2 Permissions Are Definition-Time Contracts

Permissions are attached to the model version or projection version at definition time. Once a version is published, its declared permissions are immutable—just like field definitions. Changes to permissions require a new version.

### 2.3 Portable by Default

Ownership and permission metadata must be included in every generated artifact (JSON Schema extensions, Avro metadata, Protobuf options, event envelope fields). External systems that ingest these artifacts can reference the original ownership declaration and enforce access intent without querying the Modelable registry at runtime.

### 2.4 Property-Level Granularity

Permissions may be declared at the model level and overridden at the property level. A model may be broadly readable while specific properties—such as PII fields—carry narrower access grants.

### 2.5 Permissions Propagate Through Lineage

When a projection derives a field from a source field, the derived field inherits the source field's permission constraints. A permission grant in the projection may narrow but must not broaden access beyond what the source field permits.

### 2.6 Ownership Survives Transfer

When a model definition or artifact is transferred to an external system, the ownership record and permission declarations travel with it. The receiving system is expected to honour them; the portable ownership record establishes the authoritative intent regardless of whether the issuing registry is reachable.

## 3. Ownership Model

### 3.1 Entity Ownership

Each model version declares exactly one owner identified by a structured principal reference.

```yaml
domain: customer
model: Customer
version: 2
ownership:
  owner:
    kind: team
    id: customer-platform
  steward:
    kind: role
    id: data-steward
  contact: data@customer-platform.example
  declaredAt: "2026-05-13T00:00:00Z"
```

Required fields:

- `owner.kind`: Principal type. One of `domain`, `team`, `service`, `user`, `role`.
- `owner.id`: Principal identifier within the declaring system.

Optional fields:

- `steward`: Secondary responsible party (governance contact, data steward).
- `contact`: Human-readable contact reference (email address, team channel).
- `declaredAt`: ISO 8601 timestamp of the ownership declaration.

### 3.2 Property-Level Ownership

Properties inherit the model owner unless explicitly overridden. Override is appropriate when:

- A field originated in a different domain and was imported into this model.
- A computed or derived field is maintained by a different team.

```yaml
fields:
  customerId:
    type: string
    required: true
  taxIdentifier:
    type: string
    classification: confidential
    ownership:
      owner:
        kind: team
        id: legal-and-compliance
      note: "Sourced and maintained by the legal-and-compliance team."
```

Property-level ownership declarations must reference a valid, registered principal.

### 3.3 Ownership Chain

When a projection derives a field from a source field, the lineage record includes the ownership chain so that any downstream system can answer "who owns the original source of this data?" across any number of transformation steps.

```text
billing.BillingCustomer.v1.invoiceEmail
  <- customer.Customer.v2.email          [owner: team/customer-platform]
```

### 3.4 Ownership Transfer

Ownership may be transferred between principals. A transfer event must be recorded as an explicit, versioned action—not a silent mutation.

Transfer rules:

- Only the current owner or a designated steward may initiate a transfer.
- Transfer creates a new ownership record referencing the prior owner.
- Published model versions retain the ownership record that was active at the time of publication.
- Transfer does not retroactively alter any published version.

```yaml
ownershipHistory:
  - owner:
      kind: team
      id: legacy-data
    period:
      from: "2024-01-01T00:00:00Z"
      to: "2026-05-13T00:00:00Z"
    transferredTo:
      kind: team
      id: customer-platform
    transferredBy:
      kind: user
      id: admin@example.com
    reason: "Team consolidation."
  - owner:
      kind: team
      id: customer-platform
    period:
      from: "2026-05-13T00:00:00Z"
```

## 4. Permission Model

### 4.1 Principal Types

Permissions are granted to principals. Supported principal kinds:

| Kind | Description |
|------|-------------|
| `domain` | A Modelable domain. |
| `team` | An organisational team. |
| `role` | A named role, independent of team boundaries. |
| `service` | A machine identity (service account, application). |
| `user` | A specific human identity. |
| `*` | Wildcard — any authenticated principal. |

### 4.2 Permission Types

#### Entity-Level Permissions

| Permission | Description |
|------------|-------------|
| `read` | Read model definitions and metadata from the registry. |
| `project` | Define a projection that sources from this model. |
| `subscribe` | Create a subscription to stream this model's events. |
| `write` | Publish, deprecate, or retire model versions. |
| `transfer` | Initiate an ownership transfer. |
| `manage_access` | Modify the model's access policy. |

#### Property-Level Permissions

| Permission | Description |
|------------|-------------|
| `read` | Include this property in projections and queries. |
| `derive` | Use this property as a source in computed expressions. |
| `redact` | Replace this property's value with a redaction marker. |
| `write` | Modify this property's definition (classification, metadata). |

### 4.3 Permission Grant Syntax

Permissions are declared in a model version's `access` block.

In `.mdl`, the same structure is expressed with version-scoped `access { ... }` blocks containing `entity` and `property` grant statements.

```yaml
access:
  entity:
    - principal:
        kind: domain
        id: billing
      permissions: [read, project, subscribe]
    - principal:
        kind: role
        id: data-engineer
      permissions: [read, project]
    - principal:
        kind: "*"
      permissions: [read]
  properties:
    taxIdentifier:
      - principal:
          kind: role
          id: legal-reader
        permissions: [read]
    email:
      - principal:
          kind: domain
          id: billing
        permissions: [read, derive]
      - principal:
          kind: role
          id: data-engineer
        permissions: [read]
```

### 4.4 Default Permissions

When no `access` block is declared, the following defaults apply:

- Entity `read`, `project`, `subscribe`: permitted to any principal within the same domain.
- Entity `write`, `transfer`, `manage_access`: permitted only to the declared owner.
- Property permissions inherit entity-level defaults.

An explicit `access` block completely replaces defaults. There is no implicit merging of declared and default rules.

### 4.5 Deny Overrides Grant

Where an explicit deny rule exists alongside a grant for the same principal, deny takes precedence. Deny rules use the same syntax with a `deny` key.

```yaml
access:
  properties:
    ssn:
      - principal:
          kind: "*"
        deny: [read, derive]
      - principal:
          kind: role
          id: kyc-service
        permissions: [read]
```

### 4.6 Permission Inheritance in Projections

When a projection field maps from a source field:

1. The projecting domain must hold at least `read` permission on the source property.
2. If the source property restricts `derive`, the projection field may not use it in computed expressions.
3. The projected field inherits the source field's most restrictive classification.
4. The projected field may not be granted permissions broader than the source field permits.

In Phase 1, the planner records these conditions as governance findings and keeps the ownership, access, classification, and lineage metadata reproducible. A later configured policy layer may promote selected findings to blocking errors.

The current Phase 1 planner reports findings when a projection omits explicit `project` or `read` grants, or when a computed projection field uses a source field without documented derivation policy metadata for the consuming domain.

### 4.7 Permission Scoping Across Domains

When a consumer domain defines a projection over a model in another domain:

- The consumer's domain identity is evaluated against the source model's `access` block.
- If the source model grants `project` to the consumer domain, the projection may proceed.
- Each source property is checked individually for `read` (and `derive` where required).

A domain that is not granted `project` or `read` on a source model is reported as having an insufficiently documented projection, including indirectly through a chain of projections. Real authorization remains a governance process until a later policy enforcement layer is defined.

## 5. Portable Ownership Record

### 5.1 Definition

A portable ownership record (POR) is a self-contained artifact that embeds ownership and permission metadata. It travels with the model definition or generated schema artifact so external systems can verify and honour access intent without querying the Modelable registry at runtime.

### 5.2 Structure

```json
{
  "por_version": "1",
  "model": "customer.Customer.v2",
  "ownership": {
    "owner": { "kind": "team", "id": "customer-platform" },
    "contact": "data@customer-platform.example",
    "declaredAt": "2026-05-13T00:00:00Z"
  },
  "permissions": {
    "entity": [
      {
        "principal": { "kind": "domain", "id": "billing" },
        "permissions": ["read", "project", "subscribe"]
      }
    ],
    "properties": {
      "email": [
        {
          "principal": { "kind": "domain", "id": "billing" },
          "permissions": ["read", "derive"]
        }
      ]
    }
  },
  "issuedAt": "2026-05-13T00:00:00Z",
  "issuer": "modelable-registry.customer-platform.example",
  "signature": "<base64url-encoded-signature>"
}
```

Required POR fields:

- `por_version`: POR schema version.
- `model`: Fully qualified model reference (`domain.Model.vVersion`).
- `ownership.owner`: Owner principal.
- `issuedAt`: Timestamp the POR was generated.
- `issuer`: Identifier of the registry that issued the POR.

Optional but recommended:

- `permissions`: Full access block snapshot for offline enforcement.
- `signature`: Cryptographic signature over the canonical JSON of all other fields.

### 5.3 Embedding in Generated Artifacts

The POR reference must be embedded in every generated artifact.

**JSON Schema extension:**

The POR reference is embedded alongside the standard `x-modelable-*` vendor extensions. A complete generated schema looks like:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "modelable://customer/Customer/v2",
  "title": "customer.Customer.v2",
  "type": "object",
  "required": ["customerId", "email"],
  "properties": {
    "customerId": {
      "type": "string",
      "format": "uuid",
      "x-modelable-field": "customer.Customer.v2.customerId"
    },
    "email": {
      "type": "string",
      "x-modelable-classification": "pii",
      "x-modelable-field": "customer.Customer.v2.email"
    }
  },
  "x-modelable": {
    "kind": "Model",
    "domain": "customer",
    "name": "Customer",
    "version": 2
  },
  "x-modelable-por": {
    "model": "customer.Customer.v2",
    "issuer": "modelable-registry.customer-platform.example",
    "issuedAt": "2026-05-13T00:00:00Z"
  }
}
```

**Avro schema metadata:**

```json
{
  "type": "record",
  "name": "Customer",
  "namespace": "customer.v2",
  "doc": "customer.Customer.v2",
  "fields": ["..."],
  "modelable.por": "{\"model\":\"customer.Customer.v2\",\"issuer\":\"...\",\"issuedAt\":\"...\"}"
}
```

**Change event envelope extension:**

```json
{
  "domain": "customer",
  "model": "Customer",
  "version": 2,
  "por": {
    "model": "customer.Customer.v2",
    "issuer": "modelable-registry.customer-platform.example",
    "issuedAt": "2026-05-13T00:00:00Z"
  }
}
```

Where a generated format supports per-field metadata (e.g., JSON Schema field annotations, Avro field `doc`), property-level ownership and classification must also be embedded.

### 5.4 Verifying a POR on Ingestion

When an external system receives an artifact carrying a POR:

1. Parse and extract the POR from the artifact.
2. Confirm that `issuer` and `model` match expectations for the declared source.
3. If cryptographic verification is enabled, verify `signature` against the issuer's public key.
4. Enforce the embedded `permissions` for all downstream use within that system.

Verification failures must result in one of the following, depending on the configured enforcement mode:

- `strict`: Block ingestion entirely.
- `warn`: Log a governance alert and allow ingestion.
- `off`: Skip verification.

### 5.5 Cross-System Transfer Invariants

When a Modelable model or artifact is transferred to an external system, the following invariants must hold:

1. **Origin is traceable.** The POR names the issuing registry and fully qualified model reference.
2. **Owner is preserved.** The ownership declaration in the POR is not modified by the receiving system.
3. **Permissions are advisory.** The receiving system is expected to honour embedded permissions; Modelable cannot enforce them externally, but the POR establishes the authoritative intent of record.
4. **Property constraints survive.** Per-property classifications and restrictions remain readable in the artifact after transfer.
5. **History is non-repudiable.** The ownership history documents prior owners, enabling audit after transfer.

## 6. Governance Integration

### 6.1 Audit Log Requirements

The registry must append an audit event for every ownership and permission change:

- Ownership declaration.
- Ownership transfer.
- Access policy creation, update, or deletion.
- POR issuance.

Each audit event must include:

- Actor principal.
- Target (model reference and, where applicable, property name).
- Action type.
- Before and after state for updates.
- Timestamp.
- Request trace identifier.

### 6.2 Policy Validation at Planning

The planner must evaluate permissions before accepting a projection definition:

- Confirm the projecting domain holds `project` permission on every source model.
- Confirm the projecting domain holds `read` (and `derive` where needed) on every referenced source property.
- Reject the projection if any required permission is absent.
- Include the specific missing permission and the failing principal in the error response.

### 6.3 Classification Propagation

Field classifications flow through projections. A projected field must carry at least the classification of its most restrictive source field.

| Source Classification | Minimum Projected Classification |
|-----------------------|----------------------------------|
| `public` | `public` |
| `internal` | `internal` |
| `confidential` | `confidential` |
| `pii` | `pii` |
| `sensitive` | `sensitive` |
| `restricted` | `restricted` |

A projection may raise the classification of a derived field but must not lower it below the source.

### 6.4 Redaction Rules

A field for which a consuming principal holds only `redact` permission must have its value replaced by a sentinel rather than transmitted in plaintext:

- Scalar string: `"[REDACTED]"`.
- Numeric type: `null` with a companion `_redacted: true` boolean field.
- Nested object: `{}` with a companion `_redacted: true` field.

Redaction rules applicable to a given consumer must be embedded in the POR so the receiving system can apply the same logic without querying the registry.

## 7. Storage Model Extensions

The registry entities defined in the main system specification must be extended with:

- `ownership_declarations` — one record per model version, storing owner, steward, contact, and `declaredAt`.
- `ownership_history` — append-only log of ownership transfers per model.
- `access_policies` — one or more permission grant or deny rows per model version, keyed by model version, principal kind, principal id, scope (entity or property name), and permission type.
- `por_log` — append-only log of issued PORs, storing model reference, issuer, issued timestamp, and signature if present.

Published definitions stored as immutable documents must include the full `ownership` and `access` blocks as they existed at publication time.

## 8. API Extensions

The registry API must expose:

- `declareOwnership(domain, model, version, ownershipBlock)` — set or update the ownership declaration for a draft model version.
- `transferOwnership(domain, model, transferRecord)` — record an ownership transfer; only callable by current owner or steward.
- `setAccessPolicy(domain, model, version, accessBlock)` — set the permission grants for a draft model version.
- `issuePOR(domain, model, version)` — generate and return a portable ownership record for a published model version.
- `getOwnership(domain, model, version)` — retrieve ownership declaration and history for a model version.
- `checkPermission(principal, domain, model, version, permission, property?)` — evaluate whether a given principal holds a permission on an entity or property.

## 9. MVP Scope

The first implementation should include:

- Entity-level ownership declaration (`owner`, `steward`, `contact`, `declaredAt`).
- Property-level ownership override.
- Permission grants for `read`, `project`, `subscribe`, and `write` at entity and property level as structured metadata.
- Default same-domain access assumptions when no `access` block is declared.
- Planner governance findings for projections that lack documented entity or property grants, expose governed fields, or lower/omit source classification metadata.
- Portable ownership record structure and issuance (without cryptographic signing).
- POR reference embedded in JSON Schema output and the change event envelope.
- Reproducible ownership and access metadata in the local registry index.
- `checkPermission` helper semantics for evaluating documented grants in tests and future policy wrappers.

Phase 1 treats governance as a visibility and process-support concern. The compiler detects structural governance issues visible in `.mdl` files and generated artifacts, but it does not claim to enforce real-world organizational authorization. CI policy wrappers or later registry phases may choose to fail builds on selected findings.

Defer to a later phase:

- Cryptographic POR signing and signature verification by external systems.
- Deny override rules.
- Cross-system POR verification protocol and enforcement modes.
- Hard authorization enforcement by identity provider, role registry, or approval workflow.
- Ownership transfer workflow and `ownershipHistory`.
- Automated classification propagation warnings at planning time.
- Fine-grained `derive` and `redact` permissions.
- Domain-level default policies applied to all models in a domain.
- Visual ownership and permission browsing in a UI.

## 10. Open Design Decisions

POR signing remains intentionally unresolved. The MVP must keep POR metadata structured and reproducible, but must not commit to a signing algorithm or trust model until the following choices are made:

- Whether POR signatures use a symmetric shared secret or asymmetric key pairs per registry instance.
- Whether permission grants support expiry timestamps.
- Whether `role` and `team` principal kinds are defined externally (e.g., via OIDC claims) or registered within Modelable.
- Whether domain-level policies can declare default grants that apply to all models in that domain.
- Whether projections inherit a permission set from the source model or must redeclare all grants explicitly.
- Whether permission conflicts across multiple source models in a join projection are resolved by union, intersection, or explicit consumer override.
- Whether the POR should be signed by the registry private key alone or co-signed by the owner principal.

## 11. Acceptance Criteria

The MVP ownership and permissions model is complete when:

- A model version can declare an owner, steward, and contact.
- A model version can declare an `access` block with entity and property-level permissions.
- The planner emits a governance finding for a projection from a domain that lacks a documented `project` grant on the source model.
- The planner emits a governance finding for inclusion of a source property where the consuming domain lacks a documented `read` grant.
- The planner emits a governance finding for use of a source property in a computed expression where documented derivation policy metadata is absent or incompatible with source restrictions.
- The planner emits a governance finding when a projection exposes a governed source field while lowering or omitting classification metadata.
- A generated JSON Schema includes the POR reference fields (`model`, `issuer`, `issuedAt`).
- A change event envelope includes the POR reference.
- `issuePOR` returns a valid POR for any published model version.
- `checkPermission` correctly evaluates grant and default rules for entity and property scope.
- Ownership and access metadata are reproducibly written to the local registry index.

Full policy enforcement is complete in a later phase when:

- Governance findings can be promoted to blocking policy decisions by a configured policy layer.
- Audit log entries are written for every ownership declaration and access policy change.
- An ownership history entry is created when ownership is transferred.


