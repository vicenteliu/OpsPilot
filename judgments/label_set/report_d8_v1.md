# d8-v1 on the label set's Incidents: the engines compared

51 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every one 3 times; the figures pool the runs.

Labelled: worked_around 13, slowed 12, stopped 26. Always answering stopped would be 51.0% right.

| Engine | Calls ok/failed | Accuracy | Within one level | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 153/0 | 78.4% | 96.1% | 0.141 | $0.000019 | 77 ms | 156 ms |
| playbook:anthropic/claude-haiku-5-5 | 153/0 | 76.5% | 96.7% | 0.151 | $0.000064 | 692 ms | 2204 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | worked_around | slowed | stopped |
|---|---|---|---|---|
| typesafe:jev-1.13.0 | worked_around (39) | 24 | 9 | 6 |
| typesafe:jev-1.13.0 | slowed (36) | 6 | 18 | 12 |
| typesafe:jev-1.13.0 | stopped (78) | 0 | 0 | 78 |
| playbook:anthropic/claude-haiku-5-5 | worked_around (39) | 22 | 12 | 5 |
| playbook:anthropic/claude-haiku-5-5 | slowed (36) | 6 | 23 | 7 |
| playbook:anthropic/claude-haiku-5-5 | stopped (78) | 0 | 6 | 72 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.860 | 83/153 (54.2%) | 95.2% |
| playbook:anthropic/claude-haiku-5-5 | 0.700 | 70/153 (45.8%) | 98.6% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.
