# Project Governance

This document defines how the Modelable project is managed and how decisions
are made. Modelable is an open-source project that prioritizes stability,
traceability, and domain ownership.

## 1. Roles

### 1.1 Maintainers

Maintainers are responsible for the project's technical direction, release
management, and the overall health of the codebase and community. They have
write access to the repository and are responsible for merging pull requests.

Maintainers are expected to:
- Review pull requests in a timely manner.
- Ensure changes align with the [System Specification](docs/modelable-system-spec.md).
- Uphold the [Code of Conduct](CODE_OF_CONDUCT.md).
- Manage the project roadmap and milestones.

### 1.2 Contributors

Contributors are individuals who contribute code, documentation, or other
improvements to the project. Contributions are welcome from everyone.

Contributors are expected to:
- Follow the [Contributing Guidelines](CONTRIBUTING.md).
- Participate in discussions and provide feedback.
- Help other community members.

### 1.3 Users

Users are individuals or organizations that use Modelable to define and govern
their data models. Their feedback and use cases drive the project's evolution.

## 2. Decision Making

Modelable follows a consensus-seeking decision-making process.

### 2.1 Specification Changes

Changes to the `.mdl` language grammar, core system concepts, or product
semantics (as defined in `docs/`) require:
1. An open issue for discussion.
2. A design document or updated specification describing the change.
3. Consensus among Maintainers.
4. Approval of a corresponding implementation or prototype.

### 2.2 Implementation Changes

Routine bug fixes, documentation improvements, and performance enhancements
can be merged through the standard pull request process with at least one
Maintainer approval.

### 2.3 Breaking Changes

As Modelable prioritizes immutable contracts, breaking changes to the
underlying specification or the CLI's behavior are handled with extreme care.
Incompatible changes must be clearly communicated and may require a major
version bump for the tools themselves.

## 3. Product Principles in Governance

The project governance enforces the core principles of the Modelable system:
- **Domain Ownership:** The project itself respects the ownership of its
  sub-components.
- **Immutable Contracts:** Once a tool version or specification is released,
  it is treated with the same stability expectations as a published model
  version.
- **Traceability:** Decision-making processes are recorded in GitHub issues
  and pull requests for historical traceability.

## 4. Agent Governance

Automated agents and AI assistants participating in the repository must adhere
to the [Agent Governance](docs/agent-governance.md) policy.

## 5. Becoming a Maintainer

New Maintainers are appointed by existing Maintainers based on their
sustained contributions and commitment to the project's principles. The
process is informal but documented through repository access changes.

## 6. Conflict Resolution

Conflicts are resolved through discussion and consensus. If consensus cannot
be reached, the Maintainers will make a final decision based on the best
interests of the project and its alignment with the System Specification.
