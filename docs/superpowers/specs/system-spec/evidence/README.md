# Characterization evidence

- `characterization.txt`: actual local pytest output, 2026-10-31, product revision `0fead2321bdef11c72b2746eb57f3a8b0e327c94`.
- Result: 221 passed, 2 skipped; skips are Windows directory-symlink cases, not passes.
- Exact invocation, scope and requirement mappings: [onboarding README](../README.md).
- Source/test/environment and log hashes: [baseline.json](../baseline.json).
- No production data, remote credentials or native save directories were used; tests use fixture workspaces and unique temp state.
- Metadata validator output is stored separately as `validation.json`; it is not product release evidence.
