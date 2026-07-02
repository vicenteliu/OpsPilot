# Remote access foundation gates Channels and the mobile companion

Status: accepted (2026-07-01)

ADR-0002 deliberately scoped OpsPilot to single-user, no-auth, local deployment — the API trusts everything that can reach it. The public roadmap adds **Channels** (Telegram, WeCom, …) and a **mobile companion**, both of which mean remote, multi-device access to that API.

**Decision:** neither Channels nor the mobile companion may ship against the unauthenticated local API. A remote-access foundation — authentication, TLS, and a re-evaluation of the PII-redaction boundary for remote surfaces — is an explicit prerequisite work item for both. When that foundation lands, it supersedes ADR-0002 via a new ADR; until then, ADR-0002 remains in force and the deployment model stays local-only.

**Rejected alternative:** exposing the existing local API through a tunnel (ngrok/Cloudflare Tunnel) to get bots working quickly. Rejected because it silently converts a deliberately-local trust boundary into an internet-exposed one — every safety property in ADR-0002, ADR-0005, and the redaction layer assumes a trusted local caller.
