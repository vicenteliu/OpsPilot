# Remote access: single-user bearer token, TLS at the proxy, fail-closed binding

Status: accepted (2026-07-01) — supersedes the no-auth/local-only part of ADR-0002; delivers the foundation required by ADR-0010.

Channels and the mobile companion need remote, multi-device access to the API. We stay **single-user** (per ADR-0002's positioning) and add the minimum trustworthy remote surface:

- **Authentication:** one static bearer token (`OPSPILOT_API_TOKEN` env or `api_token` in config.yaml), checked by middleware with a constant-time compare on every endpoint except `/health`. `/metrics` is deliberately not exempt — it leaks usage patterns.
- **TLS:** terminated by a reverse proxy (nginx/caddy — the supported path, config in `deploy/`); `opspilot serve --ssl-certfile/--ssl-keyfile` passes through to uvicorn for direct exposure. The app never manages certificates.
- **Fail-closed binding:** `opspilot serve` refuses to bind a non-loopback host without a token configured — the same refuse-rather-than-degrade philosophy as the L3 sandbox (ADR-0009). Loopback stays token-optional so local dev has zero friction.
- **PII boundary under remote access:** redaction still happens before storage, so remote responses carry only redacted content; the token gates who can read sessions/artifacts, TLS protects transit. Nothing else changes.

**Rejected alternatives:** multi-user accounts (no current need; meaningful refactor — revisit when Channels require per-channel identity) and OIDC/OAuth (external dependency at odds with local-first). The web UI sends the token from localStorage — acceptable for a single-user tool; revisit if XSS surface grows.
