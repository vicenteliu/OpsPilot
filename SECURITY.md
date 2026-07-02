# Security policy

## Deployment model — read this first

OpsPilot is a **single-user** tool
([ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md)). Remote access is
supported through the remote-access foundation
([ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md)):

- **Local (loopback) use needs no auth** — the default bind is `127.0.0.1`.
- **Remote binding is fail-closed**: `opspilot serve` refuses any
  non-loopback host unless an API token is configured
  (`OPSPILOT_API_TOKEN`). With a token set, every endpoint except `/health`
  requires `Authorization: Bearer <token>` (constant-time compare).
- **Always put TLS in front of a remote deployment** — a reverse proxy
  (nginx/caddy) is the supported path; see
  [docs/deployment.md](docs/deployment.md#remote-access). A bearer token
  over plain HTTP is trivially sniffable.
- There is still **one user and one token** — no accounts, roles, or
  audit-per-identity. Do not share a deployment across trust boundaries.

## Safety layers

| Layer | What it does | What it is not |
|---|---|---|
| **Redaction** | Strips PII from work-item text before it reaches any model or the KB; placeholders are content-hashed per session | Not a substitute for manually sanitizing what you paste in |
| **Sandbox L2** | AI-proposed shell actions run in an ephemeral hardened Docker container: read-only rootfs, `cap-drop ALL`, no-new-privileges, seccomp, tmpfs workdir, no host mounts, `--network=none` by default | — |
| **Sandbox L3** | Adds gVisor (`runsc`) user-space-kernel isolation; **fail-closed** — refuses to run rather than downgrade to L2 | — |
| **Approval gate** | Flags risky command patterns (`rm -rf`, `DROP TABLE`, fork bombs, prod-env or network-opening actions) for human sign-off before apply | **Not a security boundary** — a defense-in-depth signal and audit aid ([ADR-0005](docs/adr/0005-approval-gate-is-defense-signal-not-boundary.md)). The boundary is the container + network policy |

## Secrets

- API keys are resolved from environment variables only — never committed.
  `.gitleaks.toml` configures the repo's secret scanning; run
  `gitleaks git .` before publishing forks.
- The MCP client performs best-effort inline-secret detection in server
  configs (env/args/url/headers) — a footgun guard, not a guarantee. Keep
  secrets in the environment.
- Session traces and artifacts are stored locally under
  `~/.opspilot/sessions/` and may contain redacted-but-sensitive context.
  Treat the state directory as confidential.

## Reporting a vulnerability

Please report vulnerabilities privately via
[GitHub private vulnerability reporting](https://github.com/vicenteliu/OpsPilot/security/advisories/new)
— do **not** open a public issue. Include reproduction steps and the commit
or version affected. You should receive an acknowledgement within a week.
