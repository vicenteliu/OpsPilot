# d6-v1 on the label set's Incidents: the engines compared

39 Incidents is not a benchmark: synthetic, English, labelled by one person, and the threshold is set on the same rows it is reported on; there is no held-out split at this size. Each engine answered every Incident 3 times; the figures pool the runs.

Labelled: network 7, systems 32. Always answering systems would be 82.1% right.

| Engine | Calls ok/failed | Accuracy | Brier on the answer | Cost/call | p50 | p95 |
|---|---|---|---|---|---|---|
| typesafe:jev-1.13.0 | 117/0 | 100.0% | 0.002 | $0.000019 | 104 ms | 213 ms |
| playbook:anthropic/claude-haiku-5-5 | 117/0 | 100.0% | 0.031 | $0.000055 | 772 ms | 1580 ms |

## What each engine answered, by label

| Engine | Labelled (answers) | network | systems |
|---|---|---|---|
| typesafe:jev-1.13.0 | network (21) | 21 | 0 |
| typesafe:jev-1.13.0 | systems (96) | 0 | 96 |
| playbook:anthropic/claude-haiku-5-5 | network (21) | 21 | 0 |
| playbook:anthropic/claude-haiku-5-5 | systems (96) | 0 | 96 |

## Threshold: the lowest probability at which the answers decided are at least 95.0% right

| Engine | Threshold | Decided without a person | Right among them |
|---|---|---|---|
| typesafe:jev-1.13.0 | 0.790 | 117/117 (100.0%) | 100.0% |
| playbook:anthropic/claude-haiku-5-5 | 0.550 | 117/117 (100.0%) | 100.0% |

The stage applies its threshold to the primary engine's probability; an answer from the fallback always goes to a person.
