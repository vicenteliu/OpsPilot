# d8-v1 on the label set's Incidents: the engines compared

39 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every Incident 3 times; the figures pool the runs.

Labelled: worked_around 10, slowed 8, stopped 21. Always answering stopped would be 53.8% right.

| Engine | Calls ok/failed | Accuracy | Within one level | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 117/0 | 74.4% | 94.9% | 0.169 | $0.000019 | 74 ms | 156 ms |
| playbook:anthropic/claude-haiku-5-5 | 117/0 | 69.2% | 95.7% | 0.190 | $0.000068 | 701 ms | 2284 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | worked_around | slowed | stopped |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | worked_around (30) | 15 | 9 | 6 |
| typesafe:jev-1.13.0 | slowed (24) | 3 | 9 | 12 |
| typesafe:jev-1.13.0 | stopped (63) | 0 | 0 | 63 |
| playbook:anthropic/claude-haiku-5-5 | worked_around (30) | 13 | 12 | 5 |
| playbook:anthropic/claude-haiku-5-5 | slowed (24) | 6 | 11 | 7 |
| playbook:anthropic/claude-haiku-5-5 | stopped (63) | 0 | 6 | 57 |

## Threshold: the lowest probability at which the levels decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.930 | 46/117 (39.3%) | 95.7% |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 35/117 (29.9%) | 97.1% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.
