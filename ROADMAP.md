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

## Later — Channels

A **Channel** is an external messaging surface connected to OpsPilot.

- Channel abstraction (one adapter contract, per-platform implementations)
- First platforms: Telegram (simplest bot API), then WeCom (closest fit for IT ops teams)
- Assist mode first: the Channel fronts the existing KB-augmented chat
- Work-item intake through a Channel (message → Work item → pipeline) is a later phase

## Later — mobile companion

- PWA-first: the SvelteKit web UI evolves toward installable/responsive; no
  separate codebase
- Voice input pipeline: ingest chat voice recordings and files from device
  storage → transcription → KB-augmented assisted answers
- A native app remains exploratory and is not committed
