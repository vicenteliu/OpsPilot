# d3-v1 on its items: the engines compared

78 items is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same items it is reported on. Each engine answered every item 3 times; the figures pool the runs. 39 items repeat one of their five open Work items, the duplicates drafted for this (SPEC §5); the rest repeat none.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 234/0 | 92.7% | 0.052 | $0.000037 | 83 ms | 163 ms |
| playbook:anthropic/claude-haiku-5-5 | 234/0 | 94.9% | 0.053 | $0.000145 | 1097 ms | 2183 ms |

## What each engine answered, by label

| Engine | Labelled | Named the match | Said none | Named another |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | a match (117) | 117 | 0 | 0 |
| typesafe:jev-1.13.0 | none (117) | – | 100 | 17 |
| playbook:anthropic/claude-haiku-5-5 | a match (117) | 117 | 0 | 0 |
| playbook:anthropic/claude-haiku-5-5 | none (117) | – | 105 | 12 |

## Threshold: the lowest probability at which the matches named are at least 95.0% right

A match that clears it is named in the comment, for a person to link; anything else says nothing.

| Engine | Threshold | Matches named | Right among them | Labelled matches, named | Labelled none, named a match |
|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 0.790 | 122/234 | 95.1% | 116/117 | 6/117 |
| playbook:anthropic/claude-haiku-5-5 | 0.720 | 123/234 | 95.1% | 117/117 | 6/117 |
