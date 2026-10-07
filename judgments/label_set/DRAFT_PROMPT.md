You write synthetic IT service-desk Work items for a small evaluation set. A
person will later label each one, without seeing what you intended, as an
incident or a service request, and as a security issue or not. Write them the
way real people write to a service desk: hurried, partial, sometimes wrong
about what is wrong.

You are given a list of slots. Write exactly one Work item per slot, in the
same order, and keep to every attribute the slot sets. The slots set the mix;
do not rebalance it.

## What each attribute means

**intent**, what you mean the item to be:
- `incident`: something is broken or degraded. It worked, or should work, and
  doesn't.
- `service_request`: an ask for something standard: access, an account,
  software, hardware, a change to a mailbox or group. Nothing is broken.
- `ambiguous`: a reader could fairly call it either. For example: "I can't
  access X" (broken, or never granted?), "I need X working again", "X isn't set
  up for me", a request written as a complaint, a break written as a request.
  Do not resolve the ambiguity in the text.

**security**:
- `yes`: the item could involve compromise or exposure: a suspicious link or
  attachment, an unexpected sign-in or MFA prompt, a lost or stolen device,
  malware behaviour, credentials shared or requested, data sent to the wrong
  place. The writer need not realise it is a security matter.
- `no`: none of those signals appear.

**topic**: the area the item is about. Stay inside it.

**form**:
- `one_liner`: a subject only with an empty body, or a body under 12 words.
- `long_rambling`: a body of 100 to 150 words, with the real issue in the
  middle, not the first sentence.
- `non_native`: written by someone whose English is a second language:
  natural non-native phrasing, not broken or mocking.
- `pasted_error`: includes error text pasted from a screen or a log.
- `forwarded_email`: a forwarded email: the ask at the top, then a quoted
  thread below it. The channel must be `email`.
- `two_issues`: two separate problems in one item; one of them is the one that
  would drive the ticket.
- `ordinary`: none of the above.

**channel**: choose `email`, `portal` or `chat` to suit the form. Chat items
often have an empty subject.

## Rules

- Bodies are at most 150 words.
- No real company, employer, colleague, customer, internal system or incident.
  People are obviously fictional and named by first name or role only.
- Public product names are fine: Microsoft 365, Okta, Jamf, GlobalProtect,
  Zoom, and the like.
- The only domains are `example.com` and `example.org`, and hostnames sit under
  them (`vpn.example.com`).
- The text must pass a PII redactor unchanged, so it must contain none of:
  - email addresses, even under `example.com` (name the person, or say "the
    service desk mailbox"); in a forwarded thread, write `From: Priya (Finance)`
  - IP or MAC addresses
  - phone numbers, or any run of eight or more digits (write error codes such
    as `0x800704cf` with letters in them, or leave them out)
  - clock times with seconds (write `09:15`, not `09:15:30`)
  - passwords, keys or tokens, even fake ones
  - hostnames ending in `.corp`, `.internal`, `.intra`, `.lan` or `.local`
- English only.
- Each item is different from the others: no two items on the same topic with
  near-identical subjects.

## Output

Return one JSON object and nothing else:

```json
{"rows": [
  {"slot": "S01", "subject": "...", "body": "...", "channel": "email",
   "topic": "<the slot's topic, verbatim>", "draft_intent": "<the slot's intent>",
   "draft_security": "<the slot's security>"}
]}
```
