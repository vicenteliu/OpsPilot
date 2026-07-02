# Security policy

## Deployment model — read this first

OpsPilot is currently designed for **single-user, local-only** operation
([ADR-0002](docs/adr/0002-stage2-single-user-no-auth.md)):

- The API has **no authentication** — anything that can reach it can use it.
- **Do not expose the API or web UI to the internet** (including via tunnels
  such as ngrok or Cloudflare Tunnel). Every safety property below assumes a
  trusted local caller.
- A remote-access foundation (authentication + TLS) is the prerequisite for
  any remote surface and is tracked on the [roadmap](ROADMAP.md)
  ([ADR-0010](docs/adr/0010-remote-access-foundation-before-channels.md)).

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
