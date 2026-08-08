# Security Policy

## Scope and deployment model

`pipal` is primarily designed for local, single-user workflows as a thin layer over `pi`.

The optional HTTP/WebSocket server (`pipal serve`) can expose access to agent sessions and prompt execution. Treat it as sensitive.

## Supported versions

Security fixes are applied on the latest released version on the default branch.

## Reporting a vulnerability

Please report vulnerabilities privately by opening a GitHub security advisory:
- https://github.com/mohammadbashiri/pipal/security/advisories/new

If that is unavailable, open an issue with minimal exploit detail and request a private contact channel.

## Threat model (current)

Security-sensitive assets:
- agent files (`AGENTS.md`, `IDENTITY.md`, `POLICY.md`, `USER.md`, `MEMORY.md`)
- session history and summaries
- delegation jobs, transcripts, and reports
- provider/model configuration (`llm.json`)

Primary risks:
- accidental server exposure beyond localhost
- weak/guessable bearer tokens
- accidental leakage of local filesystem context through agent/tool usage

Out of scope (for now):
- multi-tenant isolation guarantees
- hardened sandboxing against a malicious local OS user
- enterprise controls (SSO/SAML, formal compliance controls)

## Security guidance

For local use:
- use default localhost bind (`pipal serve` without `--host`)

For any non-local exposure:
- set `PIPAL_AUTH_TOKEN` to a random value of at least 32 characters (shorter tokens are refused)
- configure the exact browser origins that need API access with `PIPAL_CORS_ORIGINS` (comma-separated); wildcard origins are refused
- run behind network controls (VPN/firewall/reverse proxy auth/TLS)
- do not expose unauthenticated `pipal serve` on the public internet

Pre-exposure verification checklist:
1. Server bind is intentional (`--host 0.0.0.0` or non-loopback only when needed).
2. `PIPAL_AUTH_TOKEN` is a random value of at least 32 characters and is kept secret.
3. `PIPAL_CORS_ORIGINS` contains only the exact HTTPS origins that need browser access (if any; HTTP is only appropriate for local development).
4. External access is filtered (firewall/VPN/reverse proxy policy).
5. TLS is enabled at ingress/reverse proxy for untrusted networks.
6. You have tested that unauthenticated requests are rejected.

## Hardening notes

Current server behavior:
- loopback binds may run without authentication
- non-local binds require a `PIPAL_AUTH_TOKEN` (or `AUTH_TOKEN`) of at least 32 characters
- when a token is configured, every REST endpoint (including `/health`) and WebSocket connection requires an exact `Authorization: Bearer <token>` header; WebSocket query-string tokens are refused to avoid URL/log leakage
- cross-origin browser access is disabled by default and is only enabled for explicit `PIPAL_CORS_ORIGINS`; credentials/cookies are not enabled. CORS is not authentication and does not restrict non-browser clients.
- WebSocket connections with an `Origin` header must match `PIPAL_CORS_ORIGINS`. Native browser WebSocket clients cannot set `Authorization`; use a same-origin reverse proxy that authenticates/injects the header, or a WebSocket client that supports custom headers.
