# WeCom channel starts as notify mode over the group-robot webhook

Status: accepted (2026-07-25)

The first WeCom integration is **notify mode**: intake suggestions are
pushed into a WeCom group through the group-robot webhook. There is no
conversational assist mode yet, and that is a platform constraint, not an
oversight.

- **WeCom has no long-polling API.** Telegram's outbound-only `getUpdates`
  (ADR-0012) has no WeCom equivalent: receiving messages requires a
  self-built app with a public HTTPS callback — admin-configured URL, AES
  encryption handshake, IP allowlist. That forces every WeCom-assist user
  through the remote-access deployment (ADR-0011) and adds a crypto
  dependency. The group-robot webhook, by contrast, is outbound-only:
  any group member can create one, and OpsPilot just POSTs to it.
- **Notify is a new Channel mode.** A Channel so far meant a conversational
  surface (assist) that may also file Work items (intake, ADR-0014).
  Notify mode is push-only: OpsPilot delivers, nobody replies. The
  glossary gains the mode distinction; the Channel concept itself is
  unchanged.
- **Best-effort by design.** The notifier fires after a suggestion comment
  is delivered to the Source; a notification failure logs and never fails
  the intake pass or touches intake state. The durable record is the
  comment on the work item — the group message is a courtesy copy, and
  WeCom outages must not stall intake.
- **The webhook URL is a secret.** It embeds the robot key; anyone holding
  it can post into the group. It is read from `WECOM_WEBHOOK_URL` only,
  never accepted as a CLI argument — same rule as every other credential.

**Rejected for now:** assist mode via self-built-app callback (public
HTTPS + AES handshake + admin setup; revisit as its own slice when a
deployment actually runs remote-exposed and wants it — the webhook-intake
endpoint (ADR-0015) already established the inbound pattern it would
follow); pushing every Session result rather than intake results only
(noise — interactive users are already looking at the answer).
