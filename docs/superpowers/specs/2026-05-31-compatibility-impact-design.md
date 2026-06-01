# Compatibility Impact Analysis Design

**Date:** 2026-05-31  
**Status:** Draft for review  
**Scope:** Cross-domain dependency traversal and projection impact analysis for `modelable diff`

## Goal

Extend the `modelable diff` command to identify and report which downstream projections across the entire workspace are broken or affected by a change in a source model version.

## Context

Currently, `modelable diff` only compares two versions of the same model and reports field-level compatibility. While the planner identifies if a projection "requires revalidation" when a source is marked breaking, this information is not surfaced to a user comparing model versions.

The Modelable registry already contains `lineage_edges` and `projection_sources` that can be used to traverse the dependency graph.

## Recommended Approach

Enhance `modelable diff` to perform a workspace-wide impact scan using the compiled registry.

### Why this approach

- It provides immediate feedback to model authors about the cost of a breaking change.
- It leverages the existing SQLite registry for fast cross-domain queries.
- It aligns with the "broader compatibility follow-on" goal mentioned in Phase 1 plans.

## Design

### 1. Registry Querying

Add a new helper in `modelable.registry.resolver` or `modelable.compat.checker` to find dependents:

```python
def find_impacted_projections(
    workspace: Workspace,
    domain_name: str,
    model_name: str,
    version: int,
) -> list[str]:
    """Find all projections that depend on the specified model version."""
    # Query registry.db for projection_sources where
    # source_model = f"{domain_name}.{model_name}" AND
    # source_version matches version (via version range resolution)
```

### 2. Impact Classification

Distinguish between "Broken" and "Affected" dependents:
- **Broken:** The change is `breaking` AND the projection uses a field that was removed, renamed, or changed in an incompatible way.
- **Affected:** The change is `breaking` OR `additive`, but the projection is still structurally valid (e.g., an optional field was added that the projection doesn't use yet).

### 3. CLI Output

The `modelable diff` command should add an "Impact Analysis" section:

```text
customer.Customer@1 -> customer.Customer@2
status: breaking
- removed_field email

Impacted Projections:
- [BROKEN] billing.BillingCustomer@1 (uses removed field 'email')
- [AFFECTED] shipping.ShippingLabel@2 (source version is now marked breaking)
```

## Non-Goals

- Automatic migration of downstream projections.
- Multi-hop impact analysis (e.g., impact on a projection of a projection).
- Impact on external non-Modelable consumers (e.g., generated types in other repos).

## Testing Strategy

- Add a new scenario `10-impact-analysis` with a model and several downstream projections in different domains.
- Add unit tests for `find_impacted_projections`.
- Add integration tests for `modelable diff` asserting on the impact section.

## Success Criteria

The design is complete when `modelable diff` can:
- find all direct downstream projections across domains,
- classify them as broken or affected based on the change set,
- and print a clear impact summary in the CLI.
