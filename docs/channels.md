# Channels

A **Channel** is an external messaging surface connected to OpsPilot. In
assist mode a channel fronts the KB-augmented chat — ask a question in your
messenger, get a KB-grounded answer back. The Telegram channel also doubles
as a **Source**: explicit commands file a message as a Work item
([ADR-0014](adr/0014-telegram-intake-rides-channel-adapter.md), concepts in
[docs/sources.md](sources.md)).

Channels run as separate processes and talk to a running `opspilot serve`
over HTTP, so they honor the API token (ADR-0011) and can live on a
different machine than the server.

## Telegram (assist mode)

Long-polling, outbound-only — works from behind any NAT with no public
endpoint ([ADR-0012](adr/0012-telegram-channel-long-polling.md)).

### 1. Create a bot

Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` →
copy the bot token.

### 2. Find your chat id

Send any message to your new bot, then:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool | grep -A2 '"chat"'
```

The numeric `id` under `chat` is your chat id.

### 3. Run

```bash
export TELEGRAM_BOT_TOKEN="<token from BotFather>"
opspilot serve &                                  # if not already running
opspilot channel telegram --chat-id 123456789
```

The adapter picks up `OPSPILOT_API_TOKEN` automatically when the API
requires one; point `--api-url` at a remote deployment if the server runs
elsewhere.

### Commands in the chat

| Command | Effect |
|---|---|
| `/start` | Greeting + usage hint |
| `/reset` | Clear the rolling conversation history |
| `/intake <text>` | File as a Work item (type decided by Classification), reply with the suggestion |
| `/incident <text>` | Same, with the type declared as incident |
| `/request <text>` | Same, with the type declared as service request |
| anything else | Answered via KB-augmented chat |

### Work-item intake from the chat

An intake command runs the full pipeline on the message text (redact →
classify → summarise/fulfill → validate) and replies with the same
structured suggestion the JSM adapter posts as a comment: summary, suggested
Severity, Tasks with Tiers, KB citations. The `work_item_ref` is
`TG-<chat id>-<message id>`. When Classification is not confident, the bot
asks you to resend with `/incident` or `/request` instead of guessing. Each
filing is a full LLM run — the chat-id allowlist is also the cost boundary.

### Security notes

- **The allowlist is mandatory** — the adapter refuses to start without
  `--chat-id`, and messages from unknown chats are dropped without a reply.
- The bot token is read from the environment only; never pass it as a CLI
  argument (it would land in shell history and process listings).
- Conversation history is kept in memory per chat (last 20 turns) and
  vanishes when the adapter stops. Answers may quote redacted KB content —
  treat the Telegram chat with the same sensitivity as the web UI.
