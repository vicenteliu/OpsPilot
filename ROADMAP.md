# Roadmap

Coarse-grained direction, not a commitment. Concrete work items live in
[GitHub Issues](https://github.com/vicenteliu/OpsPilot/issues) with milestones.

## Now — pre-public polish

- Repo hygiene: root cleanup, spec-only directories consolidated under `docs/`
- Docs restructure: English as canonical, Chinese translations under `docs/zh/`
  (`README.zh-CN.md` at root), plus `CONTRIBUTING.md` and `SECURITY.md`
- Web UI redesign: dark-first developer-tool theme, sidebar navigation

## Shipped — remote access foundation

Everything below requires remote, multi-device access to the API. The
foundation required by
[ADR-0010](docs/adr/0010-remote-access-foundation-before-channels.md) landed
as [ADR-0011](docs/adr/0011-remote-access-bearer-token-proxy-tls.md):

- ✅ Bearer-token authentication (fail-closed for non-loopback binds)
- ✅ TLS via reverse proxy (supported path) or uvicorn `--ssl-*` passthrough
- ✅ PII boundary re-evaluated for remote callers (redact-before-store holds;
  token gates reads, TLS protects transit)

## In progress — Channels

A **Channel** is an external messaging surface connected to OpsPilot.

- ✅ Telegram assist mode — long-polling adapter fronting the KB-augmented
  chat ([ADR-0012](docs/adr/0012-telegram-channel-long-polling.md),
  [docs/channels.md](docs/channels.md))
- Next platform: WeCom — deprioritized, now scheduled after work-item intake
- A Channel acting as a **Source** (message → Work item → pipeline) is a
  later phase

## Shipped — Work-item intake (Sources)

A **Source** is an external system of record OpsPilot pulls Work items from;
**Intake** is the poll → run → write-back loop
([ADR-0013](docs/adr/0013-jsm-intake-polling-comment-writeback.md),
[docs/sources.md](docs/sources.md)):

- ✅ Jira Service Management polling adapter (`opspilot source jsm`) —
  JQL-scoped auto-run, dedupe by issue key, suggestion posted back as a
  structured comment; comment-only, no field mutation
- ✅ Persistent state (`--state`), manual reruns (`--rerun`), cron-style
  `--once`, and `--replay` fixture mode for offline demo and CI regression
- Generic inbound webhook intake — later option for high-traffic deployments

## Later — mobile companion

- PWA-first: the SvelteKit web UI evolves toward installable/responsive; no
  separate codebase
- Voice input pipeline: ingest chat voice recordings and files from device
  storage → transcription → KB-augmented assisted answers
- A native app remains exploratory and is not committed
