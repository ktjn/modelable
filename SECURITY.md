# Security Policy

## Supported versions

Modelable is in public alpha. Security fixes are applied to the latest
released minor version. Older pre-1.0 versions may be asked to upgrade rather
than receive a backport.

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
