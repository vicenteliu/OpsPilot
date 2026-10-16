You write duplicates for a small evaluation set of synthetic IT service-desk
Work items. For each Work item you are given, write one more: the same problem,
reported separately by a different person, such as someone else hit by the same
fault, or a colleague reporting it for someone. A person will later read it
beside a few open Work items, without knowing which one you wrote it from, and
say whether one of them is the same problem.

## What makes it the same problem

- The same underlying fault: the same system, the same symptom. A service-desk
  agent who read both would link them.
- Told by a different person, in their own words and with their own details
  where natural: their device, when they noticed, what they tried. Do not copy
  phrases from the item you are given, and do not mention it.

## How to write it

- The way real people write to a service desk: hurried, partial, sometimes
  wrong about what is wrong.
- A subject (it may be empty) and a body of at most 150 words.
- A channel: `email`, `portal` or `chat`.
- Use only example.com or example.org for any domain. No real names, email
  addresses, phone numbers, IP addresses or hostnames that look real.

## Output

Only this JSON, one row per item you are given, in the same order:

```json
{"rows": [{"of": "<the id you were given>", "subject": "...", "body": "...", "channel": "email"}]}
```
