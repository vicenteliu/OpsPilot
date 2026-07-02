# Telegram channel: long polling, not webhooks; adapter as API client

Status: accepted (2026-07-02)

The first Channel (Telegram, assist mode) uses **long polling** (`getUpdates`) instead of webhooks, and runs as a **separate process that calls the OpsPilot HTTP API** rather than importing the orchestrator in-process.

- **Long polling** means outbound connections only: the bot works from behind any NAT with zero inbound exposure, no public HTTPS endpoint, no certificate. This preserves the local-first deployment story — a laptop running `opspilot serve` + `opspilot channel telegram` is a complete setup. Webhooks would force every channel user through the remote-access deployment (ADR-0011) first. Webhook mode can be added later for high-traffic deployments without changing the adapter contract.
- **Adapter-as-API-client** keeps one chat code path for the web UI and all channels, honors the bearer-token auth like any other caller, and lets the channel run on a different machine from the server.
- **Fail-closed allowlist:** the adapter refuses to start without explicit `--chat-id` values, and silently drops (logs, no reply) messages from unknown chats — replying "not authorized" would confirm the bot is alive to probers.

**Rejected:** the `python-telegram-bot` dependency (the two Bot API calls we need are ~40 lines of httpx against a stable public API); webhook-first (couples every channel setup to public HTTPS).
