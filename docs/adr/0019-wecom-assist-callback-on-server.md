# WeCom assist: callback rides the API server, answers via active send

Status: accepted (2026-07-25)

ADR-0016's deferred half ships: conversational KB chat in WeCom through a
self-built app. WeCom has no long-polling API, so this is the one Channel
that requires inbound exposure — and the design leans on patterns the
codebase already established rather than inventing new ones.

- **Callback on the API server, not a separate adapter.** ADR-0012's
  adapter-as-separate-process pattern exists to keep channels outbound-
  only; a WeCom callback is inherently inbound, and the server already
  owns the inbound story — remote access (ADR-0011: bearer token
  fail-closed, TLS via proxy) and an inbound endpoint precedent
  (ADR-0015 webhook intake). A second HTTPS listener process would
  duplicate that posture for nothing. Note the WeCom callback itself is
  authenticated by its own signature + AES envelope, not the bearer
  token — WeCom's servers can't send one.
- **Acknowledge, then answer via active send.** WeCom's passive-reply
  window is a few seconds; a KB chat takes tens. The POST handler
  verifies, decrypts, schedules a background task, and returns
  immediately — the answer goes out through ``message/send`` with a
  cached access token. Same accept-async stance as ADR-0015.
- **Fail-closed configuration.** Five env variables (corp id, agent id,
  app secret, callback token, EncodingAESKey); if any is missing the
  callback routes answer 404 and nothing else about the server changes.
  Secrets are environment-only, as everywhere else.
- **Offline verification stance.** The envelope crypto (documented
  WXBizMsgCrypt algorithm: sorted-sha1 signature, AES-CBC with
  key-derived IV, length-framed padded plaintext) is tested by
  encrypt→decrypt round trips, an independent signature recomputation,
  and tamper/mismatch rejection — a real WeCom enterprise cannot be
  exercised from CI. Live end-to-end verification is a documented
  post-deployment step in docs/channels.md.

**Rejected:** a separate callback adapter process (duplicates the
server's inbound posture); passive XML replies (the reply window is far
too short for an LLM answer); polling any WeCom API for messages (none
exists for self-built apps); embedding the official sample ciphertext as
test vectors from memory (a mistyped blob would fake confidence — the
round-trip + independent-recomputation tests verify the same algorithm
honestly).
