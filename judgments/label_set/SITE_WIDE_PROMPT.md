You write synthetic IT service-desk Work items for a small evaluation set: one
for each slot you are given. Each reports a problem that affects **everyone**
at a site or in the organisation: a service everyone uses is down or broken
for all of them. A person will later read each one, without knowing what you
intended, and judge how many people it affects and how much it stops their
work.

## How to write them

- The way real people write to a service desk: hurried, partial, sometimes
  wrong about what is wrong. Some writers say plainly that everyone is hit;
  others only hint at it ("nobody on the floor can…", "the whole office…").
- Stay inside the slot's topic.
- Vary how hard it stops work, as the slot says:
  - `stopped`: nobody can do the work it blocks;
  - `slowed`: people can still work, slowly or with errors;
  - `worked_around`: people have a way round it for now.
- A subject (it may be empty) and a body of at most 150 words.
- A channel: `email`, `portal` or `chat`.
- Use only example.com or example.org for any domain. No real names, email
  addresses, phone numbers, IP addresses or hostnames that look real.

## Output

Only this JSON, one row per slot, in the same order:

```json
{"rows": [{"slot": "<the slot id>", "subject": "...", "body": "...", "channel": "chat"}]}
```
