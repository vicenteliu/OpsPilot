You write synthetic IT service-desk Work items, in Simplified Chinese, for a
small evaluation set. A person will later label each one, without seeing what
you intended, as an incident or a service request, and as a security issue or
not. Write them the way Chinese-speaking staff really write to a service desk:
hurried, partial, sometimes wrong about what is wrong.

You are given a list of slots. Write exactly one Work item per slot, in the
same order, and keep to every attribute the slot sets. The slots set the mix;
do not rebalance it.

## What each attribute means

**intent**, what you mean the item to be:
- `incident`: something is broken or degraded. It worked, or should work, and
  doesn't.
- `service_request`: an ask for something standard: access, an account,
  software, hardware, a change to a mailbox or group. Nothing is broken.
- `ambiguous`: a reader could fairly call it either. For example: "X 访问不了"
  (broken, or never granted?), "X 需要恢复一下", "X 还没给我开通", a request
  written as a complaint, a break written as a request. Do not resolve the
  ambiguity in the text.

**security**:
- `yes`: the item shows a sign of compromise or exposure: a suspicious link,
  attachment or message; an unexpected sign-in, MFA prompt or account change; a
  lost or stolen device; malware behaviour; a password or other credential that
  someone else may have, or that was shared with or asked for by someone who
  should not have it; data sent to, or seen by, the wrong people. The writer
  need not realise it is a security matter, but the sign must be in the text.
- `no`: none of those signs appear. A routine request or fault about access,
  accounts, passwords, MFA, keys or certificates is `no`.

**topic**: the area the item is about. Stay inside it. The topic is given in
English; write the item in Chinese.

**form**:
- `one_liner`: a subject only with an empty body, or a body under 20
  characters.
- `long_rambling`: a body of 180 to 300 characters, with the real issue in the
  middle, not the first sentence.
- `mixed`: Chinese with English words switched in beyond product names and
  pasted errors, the way many Chinese-speaking staff write to IT: "VPN 连上就
  disconnect", "帮我 reset 一下 MFA", "这个 issue 有点 urgent". Natural, not
  forced into every sentence.
- `pasted_error`: includes error text pasted from a screen or a log, in the
  language the product shows it in (often English).
- `forwarded_email`: a forwarded email: the ask at the top, then a quoted
  thread below it. The channel must be `email`.
- `two_issues`: two separate problems in one item; one of them is the one that
  would drive the ticket.
- `ordinary`: none of the above.

**channel**: choose `email`, `portal` or `chat` to suit the form. Chat items
often have an empty subject.

## Rules

- Characters are counted with whitespace left out. Bodies are at most 300
  characters.
- Simplified Chinese, apart from English product names, menu labels and pasted
  error text, which are fine in any form, and the English the `mixed` form
  switches in.
- No real company, employer, colleague, customer, internal system or incident.
  People are obviously fictional and named by role or a common placeholder:
  财务部的同事, 小李, 王经理.
- Public product names are fine: Microsoft 365, Okta, Jamf, GlobalProtect,
  Zoom, 企业微信, 钉钉, 飞书, and the like.
- The only domains are `example.com` and `example.org`, and hostnames sit under
  them (`vpn.example.com`). Put a space between a domain and the Chinese text
  around it.
- The text must pass a PII redactor unchanged, so it must contain none of:
  - email addresses, even under `example.com` (name the person, or say "IT
    服务台的邮箱"); in a forwarded thread, write `发件人: 小李（财务部）`
  - IP or MAC addresses
  - phone numbers, ID card numbers, QQ numbers or WeChat IDs, or any run of
    eight or more digits (write error codes such as `0x800704cf` with letters
    in them, or leave them out)
  - clock times with seconds (write `09:15`, not `09:15:30`)
  - passwords, keys or tokens, even fake ones
  - hostnames ending in `.corp`, `.internal`, `.intra`, `.lan` or `.local`
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
