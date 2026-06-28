# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✓ current |
| < 1.0   | ✗ upgrade to 1.0 |

Security fixes are applied to the latest supported release. Older major
versions are not backported.

## Reporting a vulnerability

Use **Report a vulnerability** on the repository's GitHub Security page. This
creates a private report visible only to maintainers. Do not open a public
issue or pull request for an undisclosed vulnerability.

Include the affected version, impact, reproduction steps, and any suggested
mitigation. A maintainer will acknowledge the report, assess severity, and
coordinate a fix and disclosure through a GitHub security advisory.

Security-sensitive areas include generated artifacts, model/projection access
metadata, redaction, LLM provider integration, runtime adapters, release
artifacts, and code executed by the language server.
