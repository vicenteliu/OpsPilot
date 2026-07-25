# Telegram intake rides the channel adapter; explicit commands declare intent

Status: accepted (2026-07-25)

The first Channel-as-Source implementation (ROADMAP "later phase"; concepts
in ADR-0013) lets an allowlisted Telegram chat file a message as a Work item
and get the suggestion back as a reply. It is implemented **inside the
existing channel adapter**, not as a separate `opspilot source telegram`
process.

- **One poller per bot token.** Telegram's `getUpdates` offset is per-bot:
  two concurrent pollers steal updates from each other nondeterministically.
  A separate intake process on the same bot would silently drop chat
  messages (and vice versa), so intake must be a dispatch branch inside the
  one `TelegramChannel` loop. This deliberately breaks the "one adapter
  process per Source" symmetry of ADR-0013 — the constraint is Telegram's,
  not ours.
- **Explicit commands, no intent detection.** `/intake <text>` files with
  an undeclared type (Classification decides); `/incident <text>` and
  `/request <text>` declare the type and skip Classification. Plain
  messages remain KB chat. Auto-detecting "this chat message is really a
  ticket" would misfile conversations and burn tokens on false positives.
- **Reply is the comment.** The run result is rendered with the shared
  intake comment template (`render_comment` — one template, every
  destination) and sent back in the chat. A low-confidence classification
  replies with guidance to resend via `/incident` or `/request` instead of
  posting a possibly-wrong suggestion.
- **No intake state.** Telegram's update offset already delivers each
  message exactly once, and `work_item_ref` (`TG-<chat>-<message>`) is
  naturally unique — the JSM-style processed-key state and pending-comment
  queue are unnecessary here. A failed run is reported into the chat; the
  user resends if they still want it filed.

**Rejected:** a second bot token dedicated to intake (two bots to install
and allowlist, and the constraint returns the moment someone reuses a
token); NLP intent detection (misfiles chat, unpredictable cost); a
separate adapter process sharing the bot token (update contention, see
above).
