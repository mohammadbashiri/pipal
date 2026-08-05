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
- task definitions and daemon behavior
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
- set `PIPAL_AUTH_TOKEN` to a long random value
- run behind network controls (VPN/firewall/reverse proxy auth/TLS)
- do not expose unauthenticated `pipal serve` on the public internet

Pre-exposure verification checklist:
1. Server bind is intentional (`--host 0.0.0.0` or non-loopback only when needed).
2. `PIPAL_AUTH_TOKEN` is set and kept secret.
3. External access is filtered (firewall/VPN/reverse proxy policy).
4. TLS is enabled at ingress/reverse proxy for untrusted networks.
5. You have tested that unauthenticated requests are rejected.

## Hardening notes

Current server behavior:
- loopback binds may run without authentication
- non-local binds require `PIPAL_AUTH_TOKEN` (or `AUTH_TOKEN`)
- CORS is permissive for developer convenience; treat non-local exposure accordingly
