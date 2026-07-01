# Public Conformance Fixture

The public conformance fixture gives contributors a local substitute for the
private Observable conformance checks that informed the 1.0 release. It is not a
full runtime harness; it pins generated-artifact contracts that are easy to
regress when changing emitters.

The fixture lives in `samples/conformance/` and currently covers:

- Rust enum emission: `enum(...)` fields generate Rust enum types.
- Rust optional arrays: `optional array<T>` fields generate `Vec<T>` with
  `#[serde(default)]`, not `Option<Vec<T>>`.
- TypeScript cross-model references: `ref<domain.Model>` fields generate stable
  imported interface types.
- TypeScript array-of-enum fields: `array<enum(...)>` generates a parenthesized
  union array type.

Run the public conformance gate from `cli/`:

```bash
uv run pytest tests/test_conformance_fixture.py --tb=short
```

To validate only the sample definitions:

```bash
uv run modelable validate ../samples/conformance
```

## Adding A Case

Add a conformance case when a generated-artifact behavior is part of the stable
1.x surface and a contributor should be able to verify it without private
repository access.

1. Extend or add a `.mdl` file under `samples/conformance/`.
2. Keep the fixture small and realistic; prefer one domain concept over a
   synthetic field list.
3. Add assertions to `cli/tests/test_conformance_fixture.py` against the
   generated public artifact shape.
4. Run the conformance gate and the normal CLI gate before opening a PR.

Do not use this fixture for exploratory or implementation-private details. Those
belong in focused unit tests next to the affected emitter.
