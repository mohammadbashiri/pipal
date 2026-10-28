# Running tests

Use Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 22+.
From the repository root:

```sh
npm ci
uv run --locked pytest -q
uv run --locked pytest -q -m integration
```

`npm ci` installs the pinned development-only tooling from `package-lock.json`.
The ephemeral delegation lifecycle test uses this local esbuild installation to
compile the real TypeScript extension, then exercises it with a fake native Pi
without provider calls. It fails with setup instructions if Node.js or esbuild
is missing instead of silently skipping. No global Pi dependency layout is
assumed. Node.js/esbuild are not added to Pipal's Python runtime dependencies.

Integration tests require Pi/Pipal installed; see the CI workflow for setup.
CI installs the extension test dependencies on both macOS and Linux.
